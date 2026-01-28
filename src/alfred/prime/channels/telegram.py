"""Telegram bot integration."""

import asyncio
from typing import Callable, Awaitable

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from alfred.common import get_logger

logger = get_logger(__name__)


class TelegramChannel:
    """Telegram bot interface for Alfred."""

    def __init__(
        self,
        token: str,
        message_handler: Callable[[str, str, str], Awaitable[str]],
    ):
        """
        Initialize Telegram channel.

        Args:
            token: Telegram bot token
            message_handler: Async function(message, user_id, channel) -> response
        """
        self.token = token
        self.message_handler = message_handler
        self.app: Application | None = None

    async def start(self) -> None:
        """Start the Telegram bot."""
        self.app = (
            Application.builder()
            .token(self.token)
            .build()
        )

        # Add handlers
        self.app.add_handler(CommandHandler("start", self._handle_start))
        self.app.add_handler(CommandHandler("status", self._handle_status))
        self.app.add_handler(CommandHandler("help", self._handle_help))
        self.app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_message)
        )

        # Initialize and start polling
        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling(drop_pending_updates=True)

        logger.info("telegram_bot_started")

    async def stop(self) -> None:
        """Stop the Telegram bot."""
        if self.app:
            await self.app.updater.stop()
            await self.app.stop()
            await self.app.shutdown()
            logger.info("telegram_bot_stopped")

    async def _handle_start(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /start command."""
        user = update.effective_user
        await update.message.reply_text(
            f"Hello {user.first_name}! I'm Alfred, your persistent AI assistant.\n\n"
            "I can execute tasks across your machines, remember your preferences, "
            "and help you get things done.\n\n"
            "Just tell me what you need!"
        )

    async def _handle_status(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /status command."""
        user_id = str(update.effective_user.id)

        try:
            response = await self.message_handler(
                "What's your current status? What machines are online?",
                user_id,
                "telegram",
            )
            await update.message.reply_text(response)
        except Exception as e:
            logger.exception("status_command_failed")
            await update.message.reply_text(f"Error getting status: {e}")

    async def _handle_help(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /help command."""
        help_text = """
*Alfred Commands*

Just send me a message describing what you want to do. For example:
- "Run the tests"
- "Show me the logs"
- "List files in ~/projects"
- "Check disk space"

*Special Commands*
/start - Introduction
/status - Check online machines
/help - This message

I understand natural language, so just tell me what you need!
        """.strip()

        await update.message.reply_text(help_text, parse_mode="Markdown")

    async def _handle_message(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle incoming text messages."""
        user_id = str(update.effective_user.id)
        message = update.message.text

        logger.info(
            "telegram_message_received",
            user_id=user_id,
            message_length=len(message),
        )

        # Send typing indicator
        await update.message.chat.send_action("typing")

        try:
            response = await self.message_handler(message, user_id, "telegram")

            # Split long messages (Telegram has 4096 char limit)
            if len(response) > 4000:
                chunks = self._split_message(response, 4000)
                for chunk in chunks:
                    await update.message.reply_text(chunk)
            else:
                await update.message.reply_text(response)

        except Exception as e:
            logger.exception("message_handling_failed", user_id=user_id)
            await update.message.reply_text(
                f"Sorry, I encountered an error: {e}"
            )

    def _split_message(self, text: str, max_length: int) -> list[str]:
        """Split a message into chunks."""
        chunks = []
        current = ""

        for line in text.split("\n"):
            if len(current) + len(line) + 1 > max_length:
                if current:
                    chunks.append(current)
                current = line
            else:
                current = current + "\n" + line if current else line

        if current:
            chunks.append(current)

        return chunks
