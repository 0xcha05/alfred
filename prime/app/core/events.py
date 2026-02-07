"""Event system - the core of Ultron's event-driven architecture.

Everything in Ultron flows through events:
- Triggers create events (Telegram message, schedule tick, webhook, etc.)
- Brain processes events and decides what to do using tools
- Brain's response is sent back through the appropriate channel

NO ENUMS. Sources and types are just strings. Any system can create events.
Claude (the brain) decides what actions to take using available tools.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Callable, Awaitable
import asyncio
import logging
import uuid

logger = logging.getLogger(__name__)


@dataclass
class Event:
    """A thing that happened that Ultron should know about.
    
    source and type are STRINGS - not enums. Any system can create events.
    Examples:
        source="telegram", type="message"
        source="github", type="push"
        source="slack", type="mention"
        source="schedule", type="tick"
        source="my_custom_app", type="alert"
    """
    
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    
    # What triggered this - ANY STRING
    source: str = "unknown"
    type: str = "event"
    
    # The actual content/data
    payload: Dict[str, Any] = field(default_factory=dict)
    
    # Context for responding (where to send response, who triggered, etc.)
    # This tells the handler WHERE to send the response
    context: Dict[str, Any] = field(default_factory=dict)
    
    # Metadata
    timestamp: datetime = field(default_factory=datetime.utcnow)
    
    def __str__(self):
        return f"Event({self.source}/{self.type}, id={self.id})"


@dataclass 
class EventResult:
    """Result of processing an event."""
    
    event: Event
    response: str  # Text response from brain
    executed: bool = False  # Did brain execute any tools?
    error: Optional[str] = None


# Type for event handlers
EventHandler = Callable[[Event], Awaitable[Optional[EventResult]]]


class EventBus:
    """Central hub for event routing.
    
    Triggers publish events → EventBus routes to handlers → Actions executed
    """
    
    def __init__(self):
        self._handlers: Dict[str, List[EventHandler]] = {}
        self._global_handlers: List[EventHandler] = []
        self._queue: asyncio.Queue = asyncio.Queue()
        self._running = False
        self._task: Optional[asyncio.Task] = None
    
    def subscribe(
        self, 
        handler: EventHandler,
        source: Optional[str] = None,
        event_type: Optional[str] = None,
    ):
        """Subscribe a handler to events.
        
        If source/type not specified, handler receives all events.
        source and event_type are plain strings (not enums).
        """
        if source is None and event_type is None:
            self._global_handlers.append(handler)
        else:
            key = f"{source if source else '*'}:{event_type if event_type else '*'}"
            if key not in self._handlers:
                self._handlers[key] = []
            self._handlers[key].append(handler)
    
    async def publish(self, event: Event):
        """Publish an event to the bus."""
        await self._queue.put(event)
        logger.debug(f"Published: {event}")
    
    def publish_sync(self, event: Event):
        """Publish an event synchronously (for non-async contexts)."""
        asyncio.create_task(self.publish(event))
    
    async def start(self):
        """Start processing events."""
        self._running = True
        self._task = asyncio.create_task(self._process_loop())
        logger.info("EventBus started")
    
    async def stop(self):
        """Stop processing events."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("EventBus stopped")
    
    async def _process_loop(self):
        """Main event processing loop."""
        while self._running:
            try:
                # Wait for event with timeout so we can check _running
                try:
                    event = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                
                # Process the event
                await self._dispatch(event)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error processing event: {e}", exc_info=True)
    
    async def _dispatch(self, event: Event):
        """Dispatch event to matching handlers."""
        handlers_to_call = []
        
        # Add global handlers
        handlers_to_call.extend(self._global_handlers)
        
        # Add specific handlers (source and type are now strings)
        keys_to_check = [
            f"{event.source}:{event.type}",  # Exact match
            f"{event.source}:*",  # Source match, any type
            f"*:{event.type}",  # Any source, type match
        ]
        
        for key in keys_to_check:
            if key in self._handlers:
                handlers_to_call.extend(self._handlers[key])
        
        # Call all handlers
        for handler in handlers_to_call:
            try:
                await handler(event)
            except Exception as e:
                logger.error(f"Handler error for {event}: {e}", exc_info=True)


# Global event bus instance
event_bus = EventBus()
