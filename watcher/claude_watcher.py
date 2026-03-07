from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from aiogram import Bot
from aiogram.exceptions import TelegramRetryAfter

from bot import keyboards
from bot.rate_limiter import GroupRateLimiter
from bot.formatters import (
    format_hook_tool_use,
    format_stop_event,
    format_tool_failure,
    format_transcript_entry,
)
from claude.hooks import (
    HookEventWatcher,
    parse_stop_event,
    parse_tool_result,
    parse_tool_use,
)
from claude.models import HookEvent, HookPayload, TranscriptRole
from claude.transcript import TranscriptReader, find_transcript_files

if TYPE_CHECKING:
    from watcher.state import StateManager

logger = logging.getLogger(__name__)

_TRANSCRIPT_POLL_INTERVAL = 2.0

# Status emojis for tool use lines
_STATUS_RUNNING = "\U0001f7e1"  # 🟡
_STATUS_DONE = "\U0001f7e2"  # 🟢
_STATUS_FAILED = "\U0001f534"  # 🔴


@dataclass
class _ToolLine:
    tool_use_id: str
    text: str
    status: str = _STATUS_RUNNING


@dataclass
class _ActivityMessage:
    """Tracks a single editable Telegram message that accumulates tool use lines."""
    message_id: int
    topic_id: int
    lines: list[_ToolLine] = field(default_factory=list)

    def build_text(self) -> str:
        return "\n".join(f"{line.status} {line.text}" for line in self.lines)

    def find_line(self, tool_use_id: str) -> _ToolLine | None:
        for line in self.lines:
            if line.tool_use_id == tool_use_id:
                return line
        return None


class ClaudeWatcher:
    def __init__(
        self,
        bot: Bot,
        chat_id: int,
        state: StateManager,
        rate_limiter: GroupRateLimiter | None = None,
    ) -> None:
        self._bot = bot
        self._chat_id = chat_id
        self._state = state
        self._limiter = rate_limiter
        self._hook_watcher = HookEventWatcher(self._on_hook_event)
        self._claude_active_panes: set[str] = set()
        self._transcript_readers: dict[str, TranscriptReader] = {}
        # session_id -> topic_id, so the transcript poller knows where to send
        self._session_topics: dict[str, int] = {}
        # topic_id -> current activity message being edited
        self._activity_msgs: dict[int, _ActivityMessage] = {}
        self._running = False

    async def start(self) -> None:
        logger.info("Claude watcher started")
        self._running = True
        await asyncio.gather(
            self._hook_watcher.start(),
            self._transcript_poll_loop(),
        )

    def stop(self) -> None:
        self._running = False
        self._hook_watcher.stop()

    def is_claude_active(self, pane_id: str) -> bool:
        return pane_id in self._claude_active_panes

    async def _on_hook_event(self, payload: HookPayload) -> None:
        pane_id = payload.pane_id
        topic_id = self._state.get_topic_id_for_pane(pane_id)

        # Mark pane as Claude pane
        if pane_id and pane_id != "unknown":
            self._state.mark_claude_pane(pane_id, True)

        if topic_id is None:
            logger.debug("No topic for pane %s, skipping event %s", pane_id, payload.event)
            return

        # Always try to init transcript reader on any event with a session_id
        if payload.session_id:
            transcript_path = payload.data.get("transcript_path")
            self._init_transcript_reader(payload.session_id, topic_id, transcript_path)

        if payload.event == HookEvent.PRE_TOOL_USE:
            await self._handle_tool_use(payload, topic_id)
        elif payload.event == HookEvent.POST_TOOL_USE:
            await self._handle_tool_done(payload, topic_id)
        elif payload.event == HookEvent.POST_TOOL_USE_FAILURE:
            await self._handle_tool_failure(payload, topic_id)
        elif payload.event == HookEvent.STOP:
            await self._handle_stop(payload, topic_id, pane_id)
        elif payload.event == HookEvent.NOTIFICATION:
            await self._handle_notification(payload, topic_id)
        elif payload.event == HookEvent.SESSION_START:
            self._claude_active_panes.add(pane_id)
            self._init_transcript_reader(payload.session_id, topic_id)
        elif payload.event == HookEvent.SESSION_END:
            self._claude_active_panes.discard(pane_id)
            self._cleanup_session(payload.session_id)
            self._activity_msgs.pop(topic_id, None)
        elif payload.event == HookEvent.USER_PROMPT_SUBMIT:
            self._claude_active_panes.add(pane_id)
            self._init_transcript_reader(payload.session_id, topic_id)
            # Reset activity message for new turn
            self._activity_msgs.pop(topic_id, None)
            await self._send_typing_indicator(topic_id)

    async def _handle_tool_use(
        self, payload: HookPayload, topic_id: int
    ) -> None:
        event = parse_tool_use(payload)
        cwd = payload.data.get("cwd", "")
        tool_text = format_hook_tool_use(event, cwd)
        tool_line = _ToolLine(
            tool_use_id=event.tool_use_id,
            text=tool_text,
            status=_STATUS_RUNNING,
        )

        activity = self._activity_msgs.get(topic_id)
        if activity is not None:
            activity.lines.append(tool_line)
            await self._edit_activity_message(activity)
        else:
            # Send new message
            msg = await self._send_activity_message(
                topic_id, f"{tool_line.status} {tool_line.text}",
            )
            if msg:
                activity = _ActivityMessage(
                    message_id=msg.message_id,
                    topic_id=topic_id,
                    lines=[tool_line],
                )
                self._activity_msgs[topic_id] = activity

    async def _handle_tool_done(
        self, payload: HookPayload, topic_id: int
    ) -> None:
        tool_use_id = payload.data.get("tool_use_id", "")
        activity = self._activity_msgs.get(topic_id)
        if activity is None:
            return
        line = activity.find_line(tool_use_id)
        if line is None:
            return
        line.status = _STATUS_DONE
        await self._edit_activity_message(activity)

    async def _handle_tool_failure(
        self, payload: HookPayload, topic_id: int
    ) -> None:
        tool_use_id = payload.data.get("tool_use_id", "")
        activity = self._activity_msgs.get(topic_id)
        if activity is not None:
            line = activity.find_line(tool_use_id)
            if line is not None:
                line.status = _STATUS_FAILED
                await self._edit_activity_message(activity)
                return

        # Fallback: send standalone failure message
        event = parse_tool_result(payload)
        text = format_tool_failure(event)
        await self._acquire_send()
        await self._bot.send_message(
            chat_id=self._chat_id,
            message_thread_id=topic_id,
            text=text,
        )

    async def _handle_stop(
        self, payload: HookPayload, topic_id: int, pane_id: str
    ) -> None:
        # Mark all remaining running tools as done
        activity = self._activity_msgs.get(topic_id)
        if activity:
            for line in activity.lines:
                if line.status == _STATUS_RUNNING:
                    line.status = _STATUS_DONE
            await self._edit_activity_message(activity, final=True)
            self._activity_msgs.pop(topic_id, None)

        # Flush any remaining transcript entries
        await self._flush_transcript(payload.session_id, topic_id)

        event = parse_stop_event(payload)
        self._claude_active_panes.discard(pane_id)
        self._cleanup_session(payload.session_id)
        text = format_stop_event(event)
        await self._send_transcript_message(topic_id, text)

    async def _handle_notification(
        self, payload: HookPayload, topic_id: int
    ) -> None:
        notification_type = payload.data.get("type", "")
        title = payload.data.get("title", "Notification")
        body = payload.data.get("body", "")

        if notification_type == "permission_prompt":
            text = body or "Claude is asking for permission..."
            tool_name = payload.data.get("tool_name", "")
            always_text = f"Always allow {tool_name}" if tool_name else "Always Allow"
            await self._acquire_send()
            await self._bot.send_message(
                chat_id=self._chat_id,
                message_thread_id=topic_id,
                text=text,
                reply_markup=keyboards.permission_keyboard(always_text),
            )
        elif notification_type == "idle_prompt":
            await self._acquire_send()
            await self._bot.send_message(
                chat_id=self._chat_id,
                message_thread_id=topic_id,
                text="Claude is waiting for input.",
            )
        else:
            text = f"{title}: {body}" if body else title
            await self._acquire_send()
            await self._bot.send_message(
                chat_id=self._chat_id,
                message_thread_id=topic_id,
                text=text,
            )

    async def _acquire_send(self) -> None:
        if self._limiter is not None:
            await self._limiter.acquire()

    async def _send_activity_message(
        self, topic_id: int, text: str,
    ) -> object:
        """Send a new activity message with Stop button. Returns the Message."""
        kb = keyboards.action_bar_keyboard(claude_active=True)
        for attempt in range(3):
            try:
                await self._acquire_send()
                return await self._bot.send_message(
                    chat_id=self._chat_id,
                    message_thread_id=topic_id,
                    text=text,
                    parse_mode="HTML",
                    reply_markup=kb,
                )
            except TelegramRetryAfter as e:
                await asyncio.sleep(e.retry_after)
            except Exception:
                # Fallback without HTML (no extra acquire — already acquired)
                try:
                    return await self._bot.send_message(
                        chat_id=self._chat_id,
                        message_thread_id=topic_id,
                        text=text,
                        reply_markup=kb,
                    )
                except Exception:
                    logger.debug("Failed to send activity message")
                return None
        return None

    async def _edit_activity_message(
        self, activity: _ActivityMessage, final: bool = False,
    ) -> None:
        """Edit the activity message with updated tool lines."""
        text = activity.build_text()
        if len(text) > 4000:
            text = text[:4000] + "\n..."
        kb = keyboards.action_bar_keyboard(claude_active=not final)
        try:
            await self._bot.edit_message_text(
                chat_id=self._chat_id,
                message_id=activity.message_id,
                text=text,
                parse_mode="HTML",
                reply_markup=kb,
            )
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after)
            try:
                await self._bot.edit_message_text(
                    chat_id=self._chat_id,
                    message_id=activity.message_id,
                    text=text,
                    parse_mode="HTML",
                    reply_markup=kb,
                )
            except Exception:
                pass
        except Exception:
            # If edit fails (e.g. message too old), try without HTML
            try:
                await self._bot.edit_message_text(
                    chat_id=self._chat_id,
                    message_id=activity.message_id,
                    text=text,
                    reply_markup=kb,
                )
            except Exception:
                logger.debug("Failed to edit activity message")

    async def _send_typing_indicator(self, topic_id: int) -> None:
        try:
            await self._bot.send_chat_action(
                chat_id=self._chat_id,
                action="typing",
                message_thread_id=topic_id,
            )
        except Exception:
            logger.debug("Failed to send typing indicator")

    def _init_transcript_reader(
        self, session_id: str, topic_id: int, transcript_path: str | None = None
    ) -> None:
        if not session_id:
            return
        self._session_topics[session_id] = topic_id
        if session_id in self._transcript_readers:
            return

        # Use provided path or search for it
        filepath: Path | None = None
        if transcript_path:
            p = Path(transcript_path)
            if p.exists():
                filepath = p
        if filepath is None:
            files = find_transcript_files(session_id)
            if files:
                filepath = files[0]

        if filepath:
            reader = TranscriptReader(filepath)
            # Skip to end so we only get new content from this point
            reader.read_new_entries()
            self._transcript_readers[session_id] = reader
            logger.info("Initialized transcript reader for session %s: %s", session_id, filepath)

    def _cleanup_session(self, session_id: str) -> None:
        self._transcript_readers.pop(session_id, None)
        self._session_topics.pop(session_id, None)

    async def _transcript_poll_loop(self) -> None:
        """Periodically flush transcript entries for all active sessions."""
        while self._running:
            for session_id, topic_id in list(self._session_topics.items()):
                await self._flush_transcript(session_id, topic_id)
            await asyncio.sleep(_TRANSCRIPT_POLL_INTERVAL)

    async def _flush_transcript(self, session_id: str, topic_id: int) -> None:
        reader = self._transcript_readers.get(session_id)
        if reader is None:
            self._init_transcript_reader(session_id, topic_id)
            reader = self._transcript_readers.get(session_id)
            if reader is None:
                return

        entries = reader.read_new_entries()
        for entry in entries:
            if entry.role != TranscriptRole.ASSISTANT:
                continue
            messages = format_transcript_entry(entry)
            for text in messages:
                if not text.strip():
                    continue
                # Text message resets the activity message so next tools
                # get a fresh batch
                self._activity_msgs.pop(topic_id, None)
                await self._send_transcript_message(topic_id, text)

    async def _send_transcript_message(self, topic_id: int, text: str) -> None:
        for attempt in range(3):
            try:
                await self._acquire_send()
                await self._bot.send_message(
                    chat_id=self._chat_id,
                    message_thread_id=topic_id,
                    text=text,
                    parse_mode="HTML",
                )
                return
            except TelegramRetryAfter as e:
                logger.debug("Rate limited, waiting %ss", e.retry_after)
                await asyncio.sleep(e.retry_after)
            except Exception:
                # HTML parse error — try without formatting once, then give up
                try:
                    await self._bot.send_message(
                        chat_id=self._chat_id,
                        message_thread_id=topic_id,
                        text=text,
                    )
                except TelegramRetryAfter as e:
                    await asyncio.sleep(e.retry_after)
                except Exception:
                    logger.debug("Failed to send transcript message")
                return
