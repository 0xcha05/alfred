"""
Telegram polling mode - fetches updates from Telegram instead of using webhooks.
Use this for development/testing when you don't have HTTPS.
"""

import asyncio
import logging
import httpx
from typing import Optional

from app.config import settings

logger = logging.getLogger(__name__)


class TelegramPoller:
    """Polls Telegram for updates instead of using webhooks."""
    
    def __init__(self):
        self.base_url = f"https://api.telegram.org/bot{settings.telegram_token}"
        self.client: Optional[httpx.AsyncClient] = None
        self.running = False
        self.last_update_id = 0
        self._task: Optional[asyncio.Task] = None
    
    async def start(self):
        """Start polling for updates."""
        if not settings.telegram_token:
            logger.warning("No Telegram token configured, polling disabled")
            return
        
        self.client = httpx.AsyncClient(timeout=60.0)
        self.running = True
        
        # Delete any existing webhook first
        try:
            await self.client.post(f"{self.base_url}/deleteWebhook")
            logger.info("Deleted existing webhook (if any)")
        except Exception as e:
            logger.warning(f"Failed to delete webhook: {e}")
        
        # Start polling task
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
        logger.info("Telegram polling stopped")
    
    async def _poll_loop(self):
        """Main polling loop."""
        while self.running:
            try:
                updates = await self._get_updates()
                for update in updates:
                    await self._process_update(update)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Polling error: {e}")
                await asyncio.sleep(5)  # Wait before retrying
    
    async def _get_updates(self):
        """Fetch updates from Telegram."""
        try:
            response = await self.client.get(
                f"{self.base_url}/getUpdates",
                params={
                    "offset": self.last_update_id + 1,
                    "timeout": 30,  # Long polling
                    "allowed_updates": ["message", "callback_query"],
                },
            )
            data = response.json()
            
            if not data.get("ok"):
                logger.error(f"Telegram API error: {data}")
                return []
            
            updates = data.get("result", [])
            
            # Update offset
            if updates:
                self.last_update_id = updates[-1]["update_id"]
            
            return updates
            
        except httpx.TimeoutException:
            # Normal for long polling
            return []
        except Exception as e:
            logger.error(f"Failed to get updates: {e}")
            raise
    
    async def _process_update(self, update: dict):
        """Process a single update."""
        from app.api.telegram import process_message, process_callback, is_user_allowed
        from app.services.telegram_service import telegram_service
        
        update_id = update.get("update_id")
        logger.debug(f"Processing update {update_id}")
        
        # Handle message
        if "message" in update:
            message = update["message"]
            user_id = message.get("from", {}).get("id")
            chat_id = message.get("chat", {}).get("id")
            text = message.get("text", "")
            message_id = message.get("message_id")
            
            if not is_user_allowed(user_id):
                logger.warning(f"Unauthorized user: {user_id}")
                return
            
            logger.info(f"Message from {user_id}: {text[:50]}...")
            
            # Process the message
            await process_message(
                chat_id=chat_id,
                user_id=user_id,
                text=text,
                message_id=message_id,
            )
        
        # Handle callback query
        elif "callback_query" in update:
            callback = update["callback_query"]
            user_id = callback.get("from", {}).get("id")
            callback_id = callback.get("id")
            data = callback.get("data", "")
            chat_id = callback.get("message", {}).get("chat", {}).get("id")
            message_id = callback.get("message", {}).get("message_id")
            
            if not is_user_allowed(user_id):
                return
            
            logger.info(f"Callback from {user_id}: {data}")
            
            await process_callback(
                callback_id=callback_id,
                chat_id=chat_id,
                message_id=message_id,
                data=data,
            )


# Global instance
telegram_poller = TelegramPoller()
