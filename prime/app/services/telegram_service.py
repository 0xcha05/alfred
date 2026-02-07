"""Telegram bot service for sending messages and handling interactions."""

import logging
import os
from pathlib import Path
from typing import Optional, List, Tuple
import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# Directory to store downloaded media
MEDIA_DIR = Path("/home/ec2-user/ultron/data/media")
MEDIA_DIR.mkdir(parents=True, exist_ok=True)


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
        parse_mode: Optional[str] = "Markdown",
        reply_to_message_id: Optional[int] = None,
        reply_markup: Optional[dict] = None,
    ) -> dict:
        """Send a text message to a chat. Tries Markdown first, falls back to plain text."""
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
    
    async def get_file(self, file_id: str) -> Optional[dict]:
        """Get file info from Telegram."""
        try:
            response = await self.client.post(
                f"{self.base_url}/getFile",
                json={"file_id": file_id},
            )
            response.raise_for_status()
            result = response.json()
            if result.get("ok"):
                return result.get("result")
            return None
        except Exception as e:
            logger.error(f"Failed to get file info: {e}")
            return None
    
    async def download_file(self, file_id: str, save_as: Optional[str] = None) -> Optional[str]:
        """Download a file from Telegram and save it locally.
        
        Args:
            file_id: The Telegram file_id
            save_as: Optional filename to save as (will be placed in MEDIA_DIR)
            
        Returns:
            The local file path if successful, None otherwise
        """
        try:
            # Get file info
            file_info = await self.get_file(file_id)
            if not file_info:
                return None
            
            file_path = file_info.get("file_path")
            if not file_path:
                logger.error("No file_path in file info")
                return None
            
            # Determine local filename
            if save_as:
                local_filename = save_as
            else:
                # Use original filename or generate from file_id
                local_filename = os.path.basename(file_path)
            
            local_path = MEDIA_DIR / local_filename
            
            # Download the file
            download_url = f"https://api.telegram.org/file/bot{self.token}/{file_path}"
            response = await self.client.get(download_url)
            response.raise_for_status()
            
            # Save to disk
            with open(local_path, "wb") as f:
                f.write(response.content)
            
            logger.info(f"Downloaded file to {local_path}")
            return str(local_path)
            
        except Exception as e:
            logger.error(f"Failed to download file: {e}")
            return None
    
    async def download_media(self, message: dict) -> Optional[Tuple[str, str]]:
        """Download media from a Telegram message.
        
        Returns:
            Tuple of (local_path, media_type) if successful, None otherwise
        """
        media_types = ["video", "photo", "audio", "voice", "document", "video_note", "animation"]
        
        for media_type in media_types:
            if media_type in message:
                media = message[media_type]
                
                # Photo is a list - get the largest (last) one
                if media_type == "photo":
                    media = media[-1]  # Largest photo
                
                file_id = media.get("file_id")
                if not file_id:
                    continue
                
                # Generate filename with extension
                file_name = media.get("file_name")
                if not file_name:
                    # Infer extension from media type
                    ext_map = {
                        "video": ".mp4",
                        "photo": ".jpg",
                        "audio": ".mp3",
                        "voice": ".ogg",
                        "video_note": ".mp4",
                        "animation": ".mp4",
                    }
                    ext = ext_map.get(media_type, "")
                    file_name = f"{file_id[:20]}{ext}"
                
                local_path = await self.download_file(file_id, file_name)
                if local_path:
                    return (local_path, media_type)
        
        return None
    
    async def send_document(
        self,
        chat_id: int,
        file_path: str,
        caption: Optional[str] = None,
    ) -> dict:
        """Send a document/file to a chat."""
        try:
            with open(file_path, "rb") as f:
                files = {"document": (os.path.basename(file_path), f)}
                data = {"chat_id": chat_id}
                if caption:
                    data["caption"] = caption
                
                response = await self.client.post(
                    f"{self.base_url}/sendDocument",
                    data=data,
                    files=files,
                )
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error(f"Failed to send document: {e}")
            raise
    
    async def send_video(
        self,
        chat_id: int,
        file_path: str,
        caption: Optional[str] = None,
    ) -> dict:
        """Send a video to a chat."""
        try:
            with open(file_path, "rb") as f:
                files = {"video": (os.path.basename(file_path), f)}
                data = {"chat_id": chat_id}
                if caption:
                    data["caption"] = caption
                
                response = await self.client.post(
                    f"{self.base_url}/sendVideo",
                    data=data,
                    files=files,
                    timeout=300.0,  # Videos can take a while
                )
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error(f"Failed to send video: {e}")
            raise
    
    async def send_photo(
        self,
        chat_id: int,
        file_path: str,
        caption: Optional[str] = None,
    ) -> dict:
        """Send a photo to a chat."""
        try:
            with open(file_path, "rb") as f:
                files = {"photo": (os.path.basename(file_path), f)}
                data = {"chat_id": chat_id}
                if caption:
                    data["caption"] = caption
                
                response = await self.client.post(
                    f"{self.base_url}/sendPhoto",
                    data=data,
                    files=files,
                )
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error(f"Failed to send photo: {e}")
            raise
    
    async def send_audio(
        self,
        chat_id: int,
        file_path: str,
        caption: Optional[str] = None,
    ) -> dict:
        """Send an audio file to a chat."""
        try:
            with open(file_path, "rb") as f:
                files = {"audio": (os.path.basename(file_path), f)}
                data = {"chat_id": chat_id}
                if caption:
                    data["caption"] = caption
                
                response = await self.client.post(
                    f"{self.base_url}/sendAudio",
                    data=data,
                    files=files,
                    timeout=120.0,
                )
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error(f"Failed to send audio: {e}")
            raise
    
    async def send_file(
        self,
        chat_id: int,
        file_path: str,
        caption: Optional[str] = None,
    ) -> dict:
        """Smart file sender - detects type and sends appropriately."""
        ext = os.path.splitext(file_path)[1].lower()
        
        video_exts = [".mp4", ".avi", ".mov", ".mkv", ".webm"]
        photo_exts = [".jpg", ".jpeg", ".png", ".gif", ".webp"]
        audio_exts = [".mp3", ".wav", ".ogg", ".m4a", ".flac"]
        
        if ext in video_exts:
            return await self.send_video(chat_id, file_path, caption)
        elif ext in photo_exts:
            return await self.send_photo(chat_id, file_path, caption)
        elif ext in audio_exts:
            return await self.send_audio(chat_id, file_path, caption)
        else:
            return await self.send_document(chat_id, file_path, caption)
    
    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()


# Global service instance
telegram_service = TelegramService()
