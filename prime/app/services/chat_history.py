"""Chat history management - stores conversations and provides context to Claude."""

import json
import os
import logging
from datetime import datetime
from typing import List, Dict, Optional
from pathlib import Path

logger = logging.getLogger(__name__)

# Where to store chat history files
HISTORY_DIR = Path("/home/ec2-user/alfred/data/chat_history")


class ChatHistory:
    """Manages conversation history with persistent storage."""
    
    def __init__(self):
        # In-memory sliding window per chat
        self.memory: Dict[int, List[dict]] = {}
        self.window_size = 30  # Last 30 messages in memory
        
        # Ensure history directory exists
        HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    
    def _get_history_file(self, chat_id: int) -> Path:
        """Get the file path for a chat's history."""
        return HISTORY_DIR / f"chat_{chat_id}.jsonl"
    
    def add_message(self, chat_id: int, role: str, content: str, metadata: Optional[dict] = None):
        """Add a message to history."""
        # Skip empty messages
        if not content or not content.strip():
            logger.debug(f"Skipping empty message for chat {chat_id}")
            return
        
        message = {
            "role": role,
            "content": content,
            "timestamp": datetime.utcnow().isoformat(),
        }
        if metadata:
            message["metadata"] = metadata
        
        # Add to in-memory window
        if chat_id not in self.memory:
            self.memory[chat_id] = []
        self.memory[chat_id].append({"role": role, "content": content})
        
        # Trim to window size
        if len(self.memory[chat_id]) > self.window_size:
            self.memory[chat_id] = self.memory[chat_id][-self.window_size:]
        
        # Append to file (JSONL format - one JSON object per line)
        try:
            history_file = self._get_history_file(chat_id)
            with open(history_file, "a") as f:
                f.write(json.dumps(message) + "\n")
        except Exception as e:
            logger.error(f"Failed to save message to history: {e}")
    
    def get_recent(self, chat_id: int, count: int = 30) -> List[dict]:
        """Get recent messages for context (from memory)."""
        if chat_id in self.memory:
            return self.memory[chat_id][-count:]
        
        # If not in memory, try to load from file
        return self._load_recent_from_file(chat_id, count)
    
    def _load_recent_from_file(self, chat_id: int, count: int) -> List[dict]:
        """Load recent messages from file into memory."""
        history_file = self._get_history_file(chat_id)
        if not history_file.exists():
            return []
        
        try:
            messages = []
            with open(history_file, "r") as f:
                for line in f:
                    if line.strip():
                        msg = json.loads(line)
                        content = msg.get("content", "")
                        # Skip empty messages
                        if not content or not content.strip():
                            continue
                        messages.append({"role": msg["role"], "content": content})
            
            # Store in memory and return recent
            recent = messages[-count:]
            self.memory[chat_id] = recent
            return recent
        except Exception as e:
            logger.error(f"Failed to load history from file: {e}")
            return []
    
    def get_full_history_path(self, chat_id: int) -> str:
        """Get the path to the full history file."""
        return str(self._get_history_file(chat_id))
    
    def get_message_count(self, chat_id: int) -> int:
        """Get total number of messages in history."""
        history_file = self._get_history_file(chat_id)
        if not history_file.exists():
            return 0
        
        try:
            with open(history_file, "r") as f:
                return sum(1 for line in f if line.strip())
        except Exception:
            return 0
    
    def search_history(self, chat_id: int, query: str, limit: int = 10) -> List[dict]:
        """Search through chat history for messages containing query."""
        history_file = self._get_history_file(chat_id)
        if not history_file.exists():
            return []
        
        results = []
        try:
            with open(history_file, "r") as f:
                for line in f:
                    if line.strip():
                        msg = json.loads(line)
                        if query.lower() in msg["content"].lower():
                            results.append(msg)
                            if len(results) >= limit:
                                break
        except Exception as e:
            logger.error(f"Failed to search history: {e}")
        
        return results
    
    def get_history_summary(self, chat_id: int) -> dict:
        """Get a summary of the chat history."""
        history_file = self._get_history_file(chat_id)
        if not history_file.exists():
            return {"exists": False, "message_count": 0}
        
        count = self.get_message_count(chat_id)
        return {
            "exists": True,
            "message_count": count,
            "file_path": str(history_file),
            "in_memory": len(self.memory.get(chat_id, [])),
        }
    
    def clean_history(self, chat_id: int) -> int:
        """Remove empty messages from history file. Returns count of removed messages."""
        history_file = self._get_history_file(chat_id)
        if not history_file.exists():
            return 0
        
        try:
            # Read all messages
            valid_messages = []
            removed = 0
            with open(history_file, "r") as f:
                for line in f:
                    if line.strip():
                        msg = json.loads(line)
                        content = msg.get("content", "")
                        if content and content.strip():
                            valid_messages.append(msg)
                        else:
                            removed += 1
            
            # Rewrite file with only valid messages
            if removed > 0:
                with open(history_file, "w") as f:
                    for msg in valid_messages:
                        f.write(json.dumps(msg) + "\n")
                
                # Clear memory to reload
                if chat_id in self.memory:
                    del self.memory[chat_id]
                
                logger.info(f"Cleaned {removed} empty messages from chat {chat_id}")
            
            return removed
        except Exception as e:
            logger.error(f"Failed to clean history: {e}")
            return 0


# Global instance
chat_history = ChatHistory()
