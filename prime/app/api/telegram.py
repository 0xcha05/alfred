"""Telegram webhook handler."""

import logging
from fastapi import APIRouter, Request, HTTPException, Header, BackgroundTasks
from pydantic import BaseModel
from typing import Optional
import uuid

from app.config import settings
from app.services.telegram_service import telegram_service
from app.core.intent import parse_intent, format_response, ActionType
from app.core.router import router as task_router
from app.core.orchestrator import orchestrator
from app.grpc_server import daemon_registry

logger = logging.getLogger(__name__)

router = APIRouter()


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
    """Process incoming message through intent parsing and execution."""
    try:
        # Send typing indicator
        await telegram_service.send_typing_action(chat_id)
        
        # Parse intent
        intent = await parse_intent(text)
        logger.info(f"Parsed intent: {intent.action} with confidence {intent.confidence}")
        
        # Handle low confidence
        if intent.confidence < 0.7:
            await telegram_service.send_message(
                chat_id=chat_id,
                text=f"I'm not sure what you mean. Could you clarify?\n\nI understood: `{intent.action}`",
                reply_to_message_id=message_id,
            )
            return
        
        # Handle help
        if intent.action == ActionType.HELP:
            response = await format_response(intent, None)
            await telegram_service.send_message(
                chat_id=chat_id,
                text=response,
                reply_to_message_id=message_id,
            )
            return
        
        # Handle status
        if intent.action == ActionType.STATUS:
            summary = orchestrator.get_task_summary()
            if summary["running_count"] == 0:
                response = "No tasks currently running."
            else:
                tasks = "\n".join([
                    f"• {t['action']} on {t['daemon']} ({t['running_for']})"
                    for t in summary["tasks"]
                ])
                response = f"**Running tasks ({summary['running_count']}):**\n{tasks}"
            
            await telegram_service.send_message(
                chat_id=chat_id,
                text=response,
                reply_to_message_id=message_id,
            )
            return
        
        # Check if confirmation is required
        if intent.confirmation_required:
            # Store pending confirmation
            confirm_id = str(uuid.uuid4())[:8]
            pending_confirmations[confirm_id] = {
                "intent": intent,
                "chat_id": chat_id,
                "user_id": user_id,
            }
            
            # Send confirmation request
            await telegram_service.send_confirmation(
                chat_id=chat_id,
                message=f"⚠️ **Confirm action:**\n\n`{intent.action}`: {intent.parameters.get('command', intent.parameters)}",
                callback_data_yes=f"confirm:{confirm_id}",
                callback_data_no=f"cancel:{confirm_id}",
            )
            return
        
        # Execute the intent
        await execute_intent(intent, chat_id, message_id)
        
    except Exception as e:
        logger.error(f"Error processing message: {e}")
        await telegram_service.send_message(
            chat_id=chat_id,
            text=f"Sorry, something went wrong: {e}",
            reply_to_message_id=message_id,
        )


async def execute_intent(intent, chat_id: int, message_id: int):
    """Execute a parsed intent."""
    try:
        # Find target daemon
        target_daemon = task_router.get_target_daemon(intent)
        
        if not target_daemon:
            await telegram_service.send_message(
                chat_id=chat_id,
                text="No daemons available to execute this task. Please check that a daemon is connected.",
                reply_to_message_id=message_id,
            )
            return
        
        # Check if we're connected to the daemon
        if not daemon_registry.is_connected(target_daemon):
            await telegram_service.send_message(
                chat_id=chat_id,
                text=f"Daemon `{target_daemon}` is not connected. Waiting for connection...",
                reply_to_message_id=message_id,
            )
            return
        
        # Create and execute task
        task = orchestrator.create_task(
            daemon_id=target_daemon,
            action=intent.action.value,
            parameters=intent.parameters,
        )
        
        # Execute
        task.parameters["_daemon_id"] = target_daemon
        task = await orchestrator.execute_task(task)
        
        # Format and send response
        response = await format_response(intent, task.result if task.result else {"error": task.error})
        
        await telegram_service.send_message(
            chat_id=chat_id,
            text=response,
            reply_to_message_id=message_id,
        )
        
    except Exception as e:
        logger.error(f"Error executing intent: {e}")
        await telegram_service.send_message(
            chat_id=chat_id,
            text=f"Execution failed: {e}",
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
                text=f"✓ **Confirmed.** Executing...",
            )
            
            # Execute the intent
            await execute_intent(pending["intent"], chat_id, message_id)
            
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
