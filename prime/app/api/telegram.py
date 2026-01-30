"""Telegram webhook handler."""

import logging
from fastapi import APIRouter, Request, HTTPException, Header, BackgroundTasks
from pydantic import BaseModel
from typing import Optional, Dict, List
import uuid

from app.config import settings
from app.services.telegram_service import telegram_service
from app.core.brain import think
from app.grpc_server import daemon_registry

logger = logging.getLogger(__name__)

router = APIRouter()

# Simple conversation memory per chat
conversation_memory: Dict[int, List[dict]] = {}


class TelegramUpdate(BaseModel):
    """Telegram update model."""
    update_id: int
    message: Optional[dict] = None
    callback_query: Optional[dict] = None


# Pending confirmations storage
pending_confirmations: dict = {}


def is_user_allowed(user_id: int) -> bool:
    """Check if user is in the whitelist."""
    if not settings.telegram_allowed_user_ids:
        # No whitelist configured, allow all in dev (warn in logs)
        logger.warning(f"No user whitelist configured - allowing user {user_id}")
        return True
    return user_id in settings.telegram_allowed_user_ids


@router.post("/webhook")
async def telegram_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_telegram_bot_api_secret_token: Optional[str] = Header(None),
):
    """Handle incoming Telegram updates."""
    # Verify webhook secret
    if settings.telegram_webhook_secret:
        if x_telegram_bot_api_secret_token != settings.telegram_webhook_secret:
            logger.warning("Invalid webhook secret received")
            raise HTTPException(status_code=403, detail="Invalid webhook secret")
    
    # Parse update
    try:
        data = await request.json()
        update = TelegramUpdate(**data)
    except Exception as e:
        logger.error(f"Failed to parse update: {e}")
        raise HTTPException(status_code=400, detail=f"Invalid update: {e}")
    
    # Handle message
    if update.message:
        message = update.message
        user_id = message.get("from", {}).get("id")
        chat_id = message.get("chat", {}).get("id")
        text = message.get("text", "")
        message_id = message.get("message_id")
        
        # Check user whitelist
        if not is_user_allowed(user_id):
            logger.warning(f"Unauthorized user attempted access: {user_id}")
            return {"ok": True}
        
        logger.info(f"Message from {user_id}: {text[:100]}...")
        
        # Process in background to avoid webhook timeout
        background_tasks.add_task(
            process_message,
            chat_id=chat_id,
            user_id=user_id,
            text=text,
            message_id=message_id,
        )
        
        return {"ok": True}
    
    # Handle callback query (button presses)
    if update.callback_query:
        callback = update.callback_query
        user_id = callback.get("from", {}).get("id")
        callback_id = callback.get("id")
        data = callback.get("data", "")
        chat_id = callback.get("message", {}).get("chat", {}).get("id")
        message_id = callback.get("message", {}).get("message_id")
        
        if not is_user_allowed(user_id):
            return {"ok": True}
        
        logger.info(f"Callback from {user_id}: {data}")
        
        # Process callback in background
        background_tasks.add_task(
            process_callback,
            callback_id=callback_id,
            chat_id=chat_id,
            message_id=message_id,
            data=data,
        )
        
        return {"ok": True}
    
    return {"ok": True}


async def process_message(chat_id: int, user_id: int, text: str, message_id: int):
    """Process incoming message through Alfred's brain."""
    try:
        # Send typing indicator
        await telegram_service.send_typing_action(chat_id)
        
        # Get conversation history for this chat (last 10 messages for context)
        history = conversation_memory.get(chat_id, [])[-10:]
        
        # Think with Claude
        logger.info(f"Thinking about: {text[:100]}...")
        result = await think(
            message=text,
            chat_id=chat_id,
            conversation_history=history,
        )
        
        # Store in conversation memory
        if chat_id not in conversation_memory:
            conversation_memory[chat_id] = []
        conversation_memory[chat_id].append({"role": "user", "content": text})
        conversation_memory[chat_id].append({"role": "assistant", "content": result["response"]})
        
        # Keep only last 20 messages per chat
        if len(conversation_memory[chat_id]) > 20:
            conversation_memory[chat_id] = conversation_memory[chat_id][-20:]
        
        # Log what happened
        if result["executed"]:
            logger.info(f"Executed {len(result['results'])} command(s)")
        
        # Send response
        response = result["response"]
        if not response:
            response = "Done." if result["executed"] else "I'm not sure how to help with that."
        
        await telegram_service.send_message(
            chat_id=chat_id,
            text=response,
            reply_to_message_id=message_id,
        )
        
    except Exception as e:
        logger.error(f"Error processing message: {e}", exc_info=True)
        await telegram_service.send_message(
            chat_id=chat_id,
            text=f"Something went wrong: {e}",
            reply_to_message_id=message_id,
        )


async def process_callback(callback_id: str, chat_id: int, message_id: int, data: str):
    """Process callback query (button press)."""
    try:
        # Answer callback immediately to remove loading state
        await telegram_service.answer_callback_query(callback_id)
        
        # Parse callback data
        if data.startswith("confirm:"):
            confirm_id = data.split(":")[1]
            pending = pending_confirmations.pop(confirm_id, None)
            
            if not pending:
                await telegram_service.edit_message(
                    chat_id=chat_id,
                    message_id=message_id,
                    text="This confirmation has expired.",
                )
                return
            
            # Update message to show confirmed
            await telegram_service.edit_message(
                chat_id=chat_id,
                message_id=message_id,
                text="✓ **Confirmed.** Executing...",
            )
            
            # Re-process the original message
            await process_message(
                chat_id=chat_id,
                user_id=pending["user_id"],
                text=pending["text"],
                message_id=message_id,
            )
            
        elif data.startswith("cancel:"):
            confirm_id = data.split(":")[1]
            pending_confirmations.pop(confirm_id, None)
            
            await telegram_service.edit_message(
                chat_id=chat_id,
                message_id=message_id,
                text="✗ **Cancelled.**",
            )
        
    except Exception as e:
        logger.error(f"Error processing callback: {e}")
