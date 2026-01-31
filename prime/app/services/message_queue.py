"""
Message queue for handling incoming messages during processing.
Allows checking for new messages between tool executions.
"""

import asyncio
import logging
from typing import Optional, List, Dict
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class QueuedMessage:
    """A message waiting to be processed or incorporated."""
    chat_id: int
    user_id: int
    text: str
    message_id: int
    timestamp: datetime = field(default_factory=datetime.utcnow)


class MessageQueue:
    """
    Queue for incoming messages.
    
    - Messages are queued as they arrive
    - Brain can check for new messages between tool calls
    - New messages get incorporated into ongoing conversation
    """
    
    def __init__(self):
        self.pending: Dict[int, List[QueuedMessage]] = {}  # chat_id -> messages
        self.processing: Dict[int, bool] = {}  # chat_id -> is_processing
        self.lock = asyncio.Lock()
    
    async def add(self, chat_id: int, user_id: int, text: str, message_id: int):
        """Add a message to the queue."""
        async with self.lock:
            if chat_id not in self.pending:
                self.pending[chat_id] = []
            
            self.pending[chat_id].append(QueuedMessage(
                chat_id=chat_id,
                user_id=user_id,
                text=text,
                message_id=message_id,
            ))
            logger.debug(f"Queued message for chat {chat_id}: {text[:50]}...")
    
    async def get_next(self, chat_id: int) -> Optional[QueuedMessage]:
        """Get the next message for a chat (for initial processing)."""
        async with self.lock:
            if chat_id in self.pending and self.pending[chat_id]:
                return self.pending[chat_id].pop(0)
            return None
    
    async def get_new_messages(self, chat_id: int) -> List[QueuedMessage]:
        """
        Get any new messages that arrived during processing.
        Call this between tool executions to incorporate new context.
        """
        async with self.lock:
            if chat_id in self.pending and self.pending[chat_id]:
                messages = self.pending[chat_id].copy()
                self.pending[chat_id].clear()
                return messages
            return []
    
    async def has_pending(self, chat_id: int) -> bool:
        """Check if there are pending messages for a chat."""
        async with self.lock:
            return chat_id in self.pending and len(self.pending[chat_id]) > 0
    
    async def start_processing(self, chat_id: int) -> bool:
        """
        Mark a chat as being processed.
        Returns False if already processing (caller should queue).
        """
        async with self.lock:
            if self.processing.get(chat_id, False):
                return False
            self.processing[chat_id] = True
            return True
    
    async def stop_processing(self, chat_id: int):
        """Mark a chat as done processing."""
        async with self.lock:
            self.processing[chat_id] = False
    
    async def is_processing(self, chat_id: int) -> bool:
        """Check if a chat is currently being processed."""
        async with self.lock:
            return self.processing.get(chat_id, False)


# Global instance
message_queue = MessageQueue()
