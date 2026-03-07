from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aiogram import Bot
    from aiogram.types import InlineKeyboardMarkup, Message

logger = logging.getLogger(__name__)

# Telegram group limit is ~20 sends/min. Keep a small buffer.
_DEFAULT_MAX_PER_MINUTE = 18.0


class GroupRateLimiter:
    """Token-bucket rate limiter for Telegram sendMessage calls in a group.

    editMessageText uses a separate Telegram-side bucket, so only
    sendMessage (and similar send* methods) need to go through this.
    """

    def __init__(self, max_per_minute: float = _DEFAULT_MAX_PER_MINUTE) -> None:
        self._max = max_per_minute
        self._tokens: float = max_per_minute
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Wait until a send token is available."""
        while True:
            async with self._lock:
                self._refill()
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
            await asyncio.sleep(1.0)

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(
            self._max, self._tokens + elapsed * (self._max / 60.0)
        )
        self._last_refill = now


class GroupSender:
    """Rate-limited message sender with edit-fallback for Telegram groups.

    When sendMessage hits flood control, falls back to editing the last
    sent message in that topic (edits use a separate Telegram-side bucket).
    If no previous message exists, waits and retries the send.
    """

    def __init__(self, bot: Bot, chat_id: int, max_per_minute: float = _DEFAULT_MAX_PER_MINUTE) -> None:
        self._bot = bot
        self._chat_id = chat_id
        self._limiter = GroupRateLimiter(max_per_minute)
        # topic_id -> (message_id, current_text)
        self._last_msg: dict[int, tuple[int, str]] = {}

    async def send(
        self,
        topic_id: int,
        text: str,
        parse_mode: str | None = "HTML",
        reply_markup: InlineKeyboardMarkup | None = None,
    ) -> Message | None:
        """Send a message, falling back to editing the last one on rate limit."""
        from aiogram.exceptions import TelegramRetryAfter

        await self._limiter.acquire()
        try:
            msg = await self._bot.send_message(
                chat_id=self._chat_id,
                message_thread_id=topic_id,
                text=text,
                parse_mode=parse_mode,
                reply_markup=reply_markup,
            )
            self._last_msg[topic_id] = (msg.message_id, text)
            return msg
        except TelegramRetryAfter as e:
            logger.warning("Rate limited on send (topic %d), retry_after=%s", topic_id, e.retry_after)
            # Try edit fallback first
            edited = await self._edit_fallback(topic_id, text, parse_mode, reply_markup)
            if edited:
                return None
            # No previous message to edit — wait and retry send
            logger.info("No message to edit, waiting %ss to retry send", e.retry_after)
            await asyncio.sleep(e.retry_after)
            try:
                msg = await self._bot.send_message(
                    chat_id=self._chat_id,
                    message_thread_id=topic_id,
                    text=text,
                    parse_mode=parse_mode,
                    reply_markup=reply_markup,
                )
                self._last_msg[topic_id] = (msg.message_id, text)
                return msg
            except Exception:
                logger.warning("Retry send also failed for topic %d", topic_id)
                return None
        except Exception:
            # HTML parse error — retry without parse_mode
            if parse_mode:
                try:
                    msg = await self._bot.send_message(
                        chat_id=self._chat_id,
                        message_thread_id=topic_id,
                        text=text,
                        reply_markup=reply_markup,
                    )
                    self._last_msg[topic_id] = (msg.message_id, text)
                    return msg
                except TelegramRetryAfter as e:
                    logger.warning("Rate limited on fallback send (topic %d)", topic_id)
                    edited = await self._edit_fallback(topic_id, text, None, reply_markup)
                    if edited:
                        return None
                    await asyncio.sleep(e.retry_after)
                    return None
                except Exception:
                    logger.debug("Failed to send message to topic %d", topic_id)
            return None

    async def _edit_fallback(
        self,
        topic_id: int,
        new_text: str,
        parse_mode: str | None,
        reply_markup: InlineKeyboardMarkup | None,
    ) -> bool:
        """Try to append new_text to the last message via edit. Returns True if successful."""
        last = self._last_msg.get(topic_id)
        if last is None:
            return False

        msg_id, old_text = last
        # Append new content separated by a divider
        combined = f"{old_text}\n\n{new_text}"
        if len(combined) > 4000:
            combined = f"...\n\n{new_text}"
        try:
            await self._bot.edit_message_text(
                chat_id=self._chat_id,
                message_id=msg_id,
                text=combined,
                parse_mode=parse_mode,
                reply_markup=reply_markup,
            )
            self._last_msg[topic_id] = (msg_id, combined)
            logger.debug("Rate limit fallback: edited msg %d in topic %d", msg_id, topic_id)
            return True
        except Exception:
            if parse_mode:
                try:
                    await self._bot.edit_message_text(
                        chat_id=self._chat_id,
                        message_id=msg_id,
                        text=combined,
                        reply_markup=reply_markup,
                    )
                    self._last_msg[topic_id] = (msg_id, combined)
                    return True
                except Exception:
                    pass
            logger.debug("Edit fallback also failed in topic %d", topic_id)
            return False

    def clear_topic(self, topic_id: int) -> None:
        """Clear tracked last message for a topic (e.g. on new turn)."""
        self._last_msg.pop(topic_id, None)
