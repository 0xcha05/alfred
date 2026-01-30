"""Telegram bot service for sending messages and handling interactions."""

import logging
from typing import Optional, List
import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class TelegramService:
    """Service for interacting with Telegram Bot API."""
    
    def __init__(self):
        self.token = settings.telegram_token
        self.base_url = f"https://api.telegram.org/bot{self.token}"
        self.client = httpx.AsyncClient(timeout=30.0)
    
    async def send_message(
        self,
        chat_id: int,
        text: str,
        parse_mode: Optional[str] = None,
        reply_to_message_id: Optional[int] = None,
        reply_markup: Optional[dict] = None,
    ) -> dict:
        """Send a text message to a chat. Tries plain text first (most reliable)."""
        payload = {
            "chat_id": chat_id,
            "text": text,
        }
        
        if parse_mode:
            payload["parse_mode"] = parse_mode
        
        if reply_to_message_id:
            payload["reply_to_message_id"] = reply_to_message_id
        
        if reply_markup:
            payload["reply_markup"] = reply_markup
        
        try:
            response = await self.client.post(
                f"{self.base_url}/sendMessage",
                json=payload,
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            # If markdown parsing failed, try again without parse_mode
            if e.response.status_code == 400 and parse_mode:
                logger.warning(f"Markdown parsing failed, retrying as plain text")
                payload.pop("parse_mode", None)
                response = await self.client.post(
                    f"{self.base_url}/sendMessage",
                    json=payload,
                )
                response.raise_for_status()
                return response.json()
            logger.error(f"Failed to send message: {e}")
            raise
        except Exception as e:
            logger.error(f"Failed to send message: {e}")
            raise
    
    async def send_confirmation(
        self,
        chat_id: int,
        message: str,
        callback_data_yes: str,
        callback_data_no: str,
    ) -> dict:
        """Send a message with Yes/No inline buttons."""
        reply_markup = {
            "inline_keyboard": [
                [
                    {"text": "✓ Yes", "callback_data": callback_data_yes},
                    {"text": "✗ No", "callback_data": callback_data_no},
                ]
            ]
        }
        
        return await self.send_message(
            chat_id=chat_id,
            text=message,
            reply_markup=reply_markup,
        )
    
    async def send_options(
        self,
        chat_id: int,
        message: str,
        options: List[dict],  # [{"text": "...", "callback_data": "..."}]
    ) -> dict:
        """Send a message with multiple option buttons."""
        # Arrange in rows of 2
        keyboard = []
        row = []
        for opt in options:
            row.append(opt)
            if len(row) == 2:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)
        
        reply_markup = {"inline_keyboard": keyboard}
        
        return await self.send_message(
            chat_id=chat_id,
            text=message,
            reply_markup=reply_markup,
        )
    
    async def answer_callback_query(
        self,
        callback_query_id: str,
        text: Optional[str] = None,
        show_alert: bool = False,
    ) -> dict:
        """Answer a callback query (button press)."""
        payload = {
            "callback_query_id": callback_query_id,
            "show_alert": show_alert,
        }
        
        if text:
            payload["text"] = text
        
        try:
            response = await self.client.post(
                f"{self.base_url}/answerCallbackQuery",
                json=payload,
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Failed to answer callback: {e}")
            raise
    
    async def edit_message(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        parse_mode: Optional[str] = None,
        reply_markup: Optional[dict] = None,
    ) -> dict:
        """Edit an existing message."""
        payload = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
        }
        
        if parse_mode:
            payload["parse_mode"] = parse_mode
        
        if reply_markup:
            payload["reply_markup"] = reply_markup
        
        try:
            response = await self.client.post(
                f"{self.base_url}/editMessageText",
                json=payload,
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Failed to edit message: {e}")
            raise
    
    async def send_typing_action(self, chat_id: int) -> dict:
        """Send typing indicator."""
        try:
            response = await self.client.post(
                f"{self.base_url}/sendChatAction",
                json={"chat_id": chat_id, "action": "typing"},
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.warning(f"Failed to send typing action: {e}")
            return {}
    
    async def set_webhook(self, url: str, secret_token: Optional[str] = None) -> dict:
        """Set the webhook URL for receiving updates."""
        payload = {
            "url": url,
            "allowed_updates": ["message", "callback_query"],
        }
        
        if secret_token:
            payload["secret_token"] = secret_token
        
        try:
            response = await self.client.post(
                f"{self.base_url}/setWebhook",
                json=payload,
            )
            response.raise_for_status()
            result = response.json()
            logger.info(f"Webhook set: {result}")
            return result
        except Exception as e:
            logger.error(f"Failed to set webhook: {e}")
            raise
    
    async def get_webhook_info(self) -> dict:
        """Get current webhook configuration."""
        try:
            response = await self.client.get(f"{self.base_url}/getWebhookInfo")
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Failed to get webhook info: {e}")
            raise
    
    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()


# Global service instance
telegram_service = TelegramService()
