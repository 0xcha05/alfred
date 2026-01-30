"""Central event handler - processes all events through the brain.

This is the glue between triggers and the brain.
Events come from ANY source (string) - we route them appropriately.
"""

import logging
from typing import Optional

from app.core.events import Event, EventResult, event_bus
from app.core.brain import think
from app.services.telegram_service import telegram_service
from app.services.chat_history import chat_history

logger = logging.getLogger(__name__)

# Response handlers for different sources
# Maps source -> function that sends response
RESPONSE_HANDLERS = {}


def register_response_handler(source: str, handler):
    """Register a handler for sending responses to a source."""
    RESPONSE_HANDLERS[source] = handler
    logger.info(f"Registered response handler for source: {source}")


async def handle_event(event: Event) -> Optional[EventResult]:
    """Process any event through the brain and execute resulting actions.
    
    This is source-agnostic. The brain processes all events the same way.
    The source just tells us where to send the response.
    """
    
    logger.info(f"Handling event: {event}")
    
    try:
        # Known sources with special handling
        if event.source == "telegram":
            return await handle_telegram_event(event)
        
        elif event.source == "schedule":
            return await handle_schedule_event(event)
        
        # Check for registered handlers
        elif event.source in RESPONSE_HANDLERS:
            return await handle_generic_event(event)
        
        # Unknown source - still process through brain, log response
        else:
            return await handle_generic_event(event)
            
    except Exception as e:
        logger.error(f"Error handling event {event}: {e}", exc_info=True)
        return EventResult(
            event=event,
            response="",
            error=str(e),
        )


async def handle_telegram_event(event: Event) -> EventResult:
    """Handle a Telegram message event."""
    
    chat_id = event.context.get("chat_id")
    user_id = event.context.get("user_id")
    message_id = event.context.get("message_id")
    text = event.payload.get("text", "")
    
    # Send typing indicator
    await telegram_service.send_typing_action(chat_id)
    
    # Get conversation history
    history = chat_history.get_recent(chat_id, count=30)
    history_summary = chat_history.get_history_summary(chat_id)
    
    # Think with the brain
    result = await think(
        message=text,
        chat_id=chat_id,
        conversation_history=history,
        history_file=history_summary.get("file_path"),
        total_messages=history_summary.get("message_count", 0),
    )
    
    # Save to history
    chat_history.add_message(chat_id, "user", text, {"user_id": user_id})
    chat_history.add_message(chat_id, "assistant", result["response"], {
        "executed": result["executed"],
        "event_id": event.id,
    })
    
    # Send response
    response = result["response"] or ("Done." if result["executed"] else "I'm not sure how to help.")
    
    await telegram_service.send_message(
        chat_id=chat_id,
        text=response,
        reply_to_message_id=message_id,
    )
    
    return EventResult(
        event=event,
        response=response,
        executed=result["executed"],
    )


async def handle_schedule_event(event: Event) -> EventResult:
    """Handle a scheduled task event."""
    
    chat_id = event.context.get("chat_id")
    task_name = event.payload.get("task_name", "Scheduled task")
    action = event.payload.get("action", "")
    
    if not chat_id:
        logger.warning(f"Scheduled event has no chat_id: {event}")
        return EventResult(event=event, response="", error="No chat_id")
    
    # Build a prompt that includes the scheduled action
    prompt = f"[SCHEDULED TASK: {task_name}] {action}"
    
    # Get conversation history for context
    history = chat_history.get_recent(chat_id, count=10)  # Less history for scheduled tasks
    history_summary = chat_history.get_history_summary(chat_id)
    
    # Think with the brain
    result = await think(
        message=prompt,
        chat_id=chat_id,
        conversation_history=history,
        history_file=history_summary.get("file_path"),
        total_messages=history_summary.get("message_count", 0),
    )
    
    # Save to history
    chat_history.add_message(chat_id, "system", f"[Scheduled: {task_name}] {action}")
    chat_history.add_message(chat_id, "assistant", result["response"], {
        "scheduled": True,
        "task_name": task_name,
        "event_id": event.id,
    })
    
    # Send response to user
    response = result["response"]
    if response:
        # Prefix with task name so user knows what triggered it
        await telegram_service.send_message(
            chat_id=chat_id,
            text=f"📅 *{task_name}*\n\n{response}",
        )
    
    return EventResult(
        event=event,
        response=response,
        executed=result["executed"],
    )


async def handle_generic_event(event: Event) -> EventResult:
    """Handle any event from any source.
    
    Process through brain, send response via registered handler or log.
    """
    
    # Build a prompt from the event
    prompt = f"[Event from {event.source}: {event.type}]\n"
    
    if event.payload.get("text"):
        prompt += event.payload["text"]
    elif event.payload.get("message"):
        prompt += event.payload["message"]
    else:
        prompt += f"Payload: {event.payload}"
    
    # Get chat_id if available (for history)
    chat_id = event.context.get("chat_id", 0)
    
    # Get history if we have a chat context
    history = []
    history_file = None
    total_messages = 0
    
    if chat_id:
        history = chat_history.get_recent(chat_id, count=10)
        summary = chat_history.get_history_summary(chat_id)
        history_file = summary.get("file_path")
        total_messages = summary.get("message_count", 0)
    
    # Think with the brain
    result = await think(
        message=prompt,
        chat_id=chat_id,
        conversation_history=history,
        history_file=history_file,
        total_messages=total_messages,
    )
    
    response = result["response"]
    
    # Try to send response via registered handler
    if event.source in RESPONSE_HANDLERS:
        try:
            await RESPONSE_HANDLERS[event.source](event, response)
        except Exception as e:
            logger.error(f"Failed to send response via {event.source} handler: {e}")
    
    # If there's a chat_id, also send to telegram as fallback
    elif chat_id and event.source != "telegram":
        await telegram_service.send_message(
            chat_id=chat_id,
            text=f"📨 *{event.source}* ({event.type})\n\n{response}",
        )
    
    # Otherwise just log it
    else:
        logger.info(f"Event {event.id} response: {response[:200]}...")
    
    return EventResult(
        event=event,
        response=response,
        executed=result["executed"],
    )


def setup_event_handlers():
    """Register event handlers with the event bus."""
    
    # Register the main handler for all events
    event_bus.subscribe(handle_event)
    
    logger.info("Event handlers registered")
