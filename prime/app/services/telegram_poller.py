"""
Telegram polling mode - fetches updates from Telegram instead of using webhooks.
"""

import asyncio
import logging
import json
import httpx
from pathlib import Path
from typing import Optional
from datetime import datetime

from app.config import settings

logger = logging.getLogger(__name__)

# Persist offset so restarts don't reprocess old messages
OFFSET_FILE = Path("/home/ec2-user/ultron/data/telegram_offset.json")


class TelegramPoller:
    """Polls Telegram for updates."""
    
    def __init__(self):
        self.base_url = f"https://api.telegram.org/bot{settings.telegram_token}"
        self.client: Optional[httpx.AsyncClient] = None
        self.running = False
        self.last_update_id = 0
        self._task: Optional[asyncio.Task] = None
    
    def _load_offset(self):
        """Load last update ID from disk."""
        try:
            if OFFSET_FILE.exists():
                with open(OFFSET_FILE) as f:
                    data = json.load(f)
                    self.last_update_id = data.get("last_update_id", 0)
                    logger.info(f"Loaded offset: {self.last_update_id}")
        except Exception as e:
            logger.warning(f"Failed to load offset: {e}")
    
    def _save_offset(self):
        """Save last update ID to disk."""
        try:
            OFFSET_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(OFFSET_FILE, "w") as f:
                json.dump({
                    "last_update_id": self.last_update_id,
                    "saved_at": datetime.utcnow().isoformat()
                }, f)
        except Exception as e:
            logger.warning(f"Failed to save offset: {e}")
    
    async def start(self):
        """Start polling for updates."""
        if not settings.telegram_token:
            logger.warning("No Telegram token configured, polling disabled")
            return
        
        self.client = httpx.AsyncClient(timeout=60.0)
        self.running = True
        
        # Load persisted offset
        self._load_offset()
        
        # Delete any existing webhook
        try:
            await self.client.post(f"{self.base_url}/deleteWebhook")
            logger.info("Deleted existing webhook (if any)")
        except Exception as e:
            logger.warning(f"Failed to delete webhook: {e}")
        
        self._task = asyncio.create_task(self._poll_loop())
        logger.info("Telegram polling started")
    
    async def stop(self):
        """Stop polling."""
        self.running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self.client:
            await self.client.aclose()
        
        self._save_offset()
        logger.info("Telegram polling stopped")
    
    async def _poll_loop(self):
        """Main polling loop."""
        while self.running:
            try:
                updates = await self._get_updates()
                for update in updates:
                    # Process each update immediately (don't await, let it run)
                    asyncio.create_task(self._handle_update(update))
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Polling error: {e}")
                await asyncio.sleep(5)
    
    async def _get_updates(self):
        """Fetch updates from Telegram."""
        try:
            response = await self.client.get(
                f"{self.base_url}/getUpdates",
                params={
                    "offset": self.last_update_id + 1,
                    "timeout": 30,
                    "allowed_updates": ["message", "callback_query"],
                },
            )
            data = response.json()
            
            if not data.get("ok"):
                logger.error(f"Telegram API error: {data}")
                return []
            
            updates = data.get("result", [])
            
            if updates:
                self.last_update_id = updates[-1]["update_id"]
                self._save_offset()
            
            return updates
            
        except httpx.TimeoutException:
            return []
        except Exception as e:
            logger.error(f"Failed to get updates: {e}")
            raise
    
    async def _handle_update(self, update: dict):
        """Handle a single update."""
        from app.api.telegram import is_user_allowed, process_callback
        from app.services.message_queue import message_queue
        from app.services.telegram_service import telegram_service
        
        # Handle callback queries immediately
        if "callback_query" in update:
            callback = update["callback_query"]
            user_id = callback.get("from", {}).get("id")
            if is_user_allowed(user_id):
                await process_callback(
                    callback_id=callback.get("id"),
                    chat_id=callback.get("message", {}).get("chat", {}).get("id"),
                    message_id=callback.get("message", {}).get("message_id"),
                    data=callback.get("data", ""),
                )
            return
        
        # Handle messages
        if "message" not in update:
            return
        
        message = update["message"]
        user_id = message.get("from", {}).get("id")
        chat_id = message.get("chat", {}).get("id")
        message_id = message.get("message_id")
        
        if not is_user_allowed(user_id):
            logger.warning(f"Unauthorized user: {user_id}")
            return
        
        # Extract text
        text = await self._extract_text(message)
        if not text:
            return
        
        logger.info(f"Message from {user_id}: {text[:50]}...")
        
        # Check if already processing this chat
        if await message_queue.is_processing(chat_id):
            # Queue for incorporation into ongoing conversation
            await message_queue.add(chat_id, user_id, text, message_id)
            logger.info(f"Queued message for ongoing conversation in chat {chat_id}")
            return
        
        # Start processing immediately
        if not await message_queue.start_processing(chat_id):
            # Race condition - queue it
            await message_queue.add(chat_id, user_id, text, message_id)
            return
        
        try:
            from app.api.telegram import process_message
            await process_message(
                chat_id=chat_id,
                user_id=user_id,
                text=text,
                message_id=message_id,
            )
        finally:
            await message_queue.stop_processing(chat_id)
            
            # Check if more messages came in during processing
            if await message_queue.has_pending(chat_id):
                # Get next message and process it
                next_msg = await message_queue.get_next(chat_id)
                if next_msg:
                    asyncio.create_task(self._process_queued(next_msg))
    
    async def _process_queued(self, msg):
        """Process a queued message."""
        from app.api.telegram import process_message
        from app.services.message_queue import message_queue
        
        if not await message_queue.start_processing(msg.chat_id):
            # Still processing, re-queue
            await message_queue.add(msg.chat_id, msg.user_id, msg.text, msg.message_id)
            return
        
        try:
            await process_message(
                chat_id=msg.chat_id,
                user_id=msg.user_id,
                text=msg.text,
                message_id=msg.message_id,
            )
        finally:
            await message_queue.stop_processing(msg.chat_id)
            
            # Check for more
            if await message_queue.has_pending(msg.chat_id):
                next_msg = await message_queue.get_next(msg.chat_id)
                if next_msg:
                    asyncio.create_task(self._process_queued(next_msg))
    
    async def _extract_text(self, message: dict) -> Optional[str]:
        """Extract text from a message."""
        from app.services.telegram_service import telegram_service
        
        text = message.get("text", "")
        if text:
            return text
        
        caption = message.get("caption", "")
        if caption:
            return caption
        
        # Handle media
        media_types = ["video", "photo", "audio", "voice", "document", "sticker", "video_note", "animation"]
        for media_type in media_types:
            if media_type in message:
                media_info = message.get(media_type, {})
                download_result = await telegram_service.download_media(message)
                
                if download_result:
                    local_path, _ = download_result
                    if media_type == "video":
                        duration = media_info.get("duration", "?")
                        return f"[User sent a video ({duration}s). Downloaded to: {local_path}]"
                    elif media_type == "photo":
                        return f"[User sent a photo. Downloaded to: {local_path}]"
                    else:
                        return f"[User sent {media_type}. Downloaded to: {local_path}]"
                else:
                    if media_type == "sticker":
                        return f"[User sent a sticker {media_info.get('emoji', '')}]"
                    return f"[User sent {media_type} - download failed]"
        
        return None


# Global instance
telegram_poller = TelegramPoller()
