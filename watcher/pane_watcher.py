from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

from aiogram import Bot

from bot import keyboards
from bot.formatters import (
    format_activity_notification,
    format_prompt_source,
    format_terminal_output,
)
from parser.terminal import (
    BashApproval,
    ExitPlanModePrompt,
    IdlePrompt,
    PermissionPrompt,
    RestoreCheckpointPrompt,
    YesNoPrompt,
    AskUserSingle,
    AskUserMulti,
    detect_prompt,
)
from tmux.capture import PaneCapture

if TYPE_CHECKING:
    from config import Settings
    from tmux.manager import TmuxManager
    from watcher.state import StateManager

logger = logging.getLogger(__name__)


class PaneWatcher:
    def __init__(
        self,
        bot: Bot,
        chat_id: int,
        tmux: TmuxManager,
        state: StateManager,
        settings: "Settings",
    ) -> None:
        self._bot = bot
        self._chat_id = chat_id
        self._tmux = tmux
        self._state = state
        self._settings = settings
        self._capture = PaneCapture(tmux)
        self._running = False
        self._last_output_time: dict[str, float] = {}
        self._pending_output: dict[str, str] = {}
        self._output_msg_ids: dict[str, int] = {}

    async def start(self) -> None:
        self._running = True
        logger.info("Pane watcher started")
        while self._running:
            await self._poll_cycle()

    def stop(self) -> None:
        self._running = False

    async def _poll_cycle(self) -> None:
        pane_ids = self._state.all_pane_ids()
        now = time.monotonic()

        for pane_id in pane_ids:
            # Skip Claude panes (handled by ClaudeWatcher)
            if self._state.is_claude_pane(pane_id):
                continue

            topic_id = self._state.get_topic_id_for_pane(pane_id)
            if topic_id is None:
                continue

            is_focused = self._state.get_focused_pane(topic_id) == pane_id

            # Adaptive polling interval
            interval = (
                self._settings.poll_interval_active
                if is_focused
                else self._settings.poll_interval_idle
            )
            last_time = self._last_output_time.get(pane_id, 0)
            if now - last_time < interval:
                continue

            content = self._capture.capture_if_changed(pane_id)
            if content is None:
                continue

            self._last_output_time[pane_id] = now

            if is_focused:
                await self._handle_focused_output(pane_id, topic_id, content)
            else:
                await self._handle_background_activity(pane_id, topic_id)

        # Flush debounced output
        await self._flush_pending_output()

        # Sleep for shortest interval
        await asyncio.sleep(self._settings.poll_interval_active)

    async def _handle_focused_output(
        self, pane_id: str, topic_id: int, content: str
    ) -> None:
        # Check for prompts first
        prompt = detect_prompt(content)
        if prompt is not None and not isinstance(prompt, IdlePrompt):
            await self._send_prompt(pane_id, topic_id, prompt)
            return

        # Debounce output
        self._pending_output[pane_id] = content

    async def _handle_background_activity(
        self, pane_id: str, topic_id: int
    ) -> None:
        # Check for prompts from background panes — surface immediately
        content = self._capture.get_last_content(pane_id)
        prompt = detect_prompt(content)

        if prompt is not None and not isinstance(prompt, IdlePrompt):
            await self._send_prompt(pane_id, topic_id, prompt)
            return

        # Get pane index for display
        pane_index = 0
        try:
            pane_index = int(pane_id.replace("%", ""))
        except ValueError:
            pass

        window_name = "unknown"
        pane = self._tmux._get_pane(pane_id)
        if pane and pane.window:
            window_name = pane.window.name or "unknown"

        text = format_activity_notification(window_name, pane_index)
        await self._bot.send_message(
            chat_id=self._chat_id,
            message_thread_id=topic_id,
            text=text,
            reply_markup=keyboards.switch_pane_button(pane_id),
        )

    async def _flush_pending_output(self) -> None:
        now = time.monotonic()
        flushed: list[str] = []

        for pane_id, content in self._pending_output.items():
            last_time = self._last_output_time.get(pane_id, 0)
            if now - last_time < self._settings.output_debounce:
                continue

            topic_id = self._state.get_topic_id_for_pane(pane_id)
            if topic_id is None:
                flushed.append(pane_id)
                continue

            text, truncated = format_terminal_output(
                content, self._settings.text_line_limit
            )
            markup = keyboards.screenshot_button() if truncated else None

            try:
                # Try to edit existing output message
                msg_id = self._output_msg_ids.get(pane_id)
                if msg_id:
                    try:
                        await self._bot.edit_message_text(
                            chat_id=self._chat_id,
                            message_id=msg_id,
                            text=text,
                            parse_mode="Markdown",
                            reply_markup=markup,
                        )
                        flushed.append(pane_id)
                        continue
                    except Exception:
                        pass

                msg = await self._bot.send_message(
                    chat_id=self._chat_id,
                    message_thread_id=topic_id,
                    text=text,
                    parse_mode="Markdown",
                    reply_markup=markup,
                )
                self._output_msg_ids[pane_id] = msg.message_id
            except Exception:
                logger.exception("Failed to send output for pane %s", pane_id)

            flushed.append(pane_id)

        for pane_id in flushed:
            self._pending_output.pop(pane_id, None)

    async def _send_prompt(self, pane_id: str, topic_id: int, prompt: object) -> None:
        is_focused = self._state.get_focused_pane(topic_id) == pane_id

        # Track pending prompt in state
        prompt_type = type(prompt).__name__
        ps = self._state.find_pane_state(pane_id)
        if ps is not None:
            ps.pending_prompt = prompt_type

        if isinstance(prompt, PermissionPrompt):
            text = prompt.description or "Permission requested"
            markup = keyboards.permission_keyboard()
        elif isinstance(prompt, BashApproval):
            text = f"Bash: `{prompt.command}`"
            markup = keyboards.bash_approval_keyboard()
        elif isinstance(prompt, AskUserSingle):
            text = prompt.question or "Choose an option:"
            markup = keyboards.single_choice_keyboard(prompt.options)
        elif isinstance(prompt, AskUserMulti):
            text = prompt.question or "Select options:"
            markup = keyboards.multi_choice_keyboard(prompt.options, prompt.selected)
        elif isinstance(prompt, ExitPlanModePrompt):
            text = "How would you like to proceed?"
            markup = keyboards.plan_mode_keyboard(prompt.options)
        elif isinstance(prompt, RestoreCheckpointPrompt):
            text = prompt.description or "Restore checkpoint?"
            markup = keyboards.checkpoint_keyboard()
        elif isinstance(prompt, YesNoPrompt):
            text = prompt.question or "Yes or No?"
            markup = keyboards.yes_no_keyboard()
        else:
            return

        # Prefix background prompts with source info
        if not is_focused:
            pane = self._tmux._get_pane(pane_id)
            window_name = "unknown"
            pane_index = 0
            if pane:
                if pane.window:
                    window_name = pane.window.name or "unknown"
                try:
                    pane_index = int(pane_id.replace("%", ""))
                except ValueError:
                    pass
            text = format_prompt_source(window_name, pane_index, text)

        await self._bot.send_message(
            chat_id=self._chat_id,
            message_thread_id=topic_id,
            text=text,
            reply_markup=markup,
        )
        # Reset output message so next output gets a new message
        self._output_msg_ids.pop(pane_id, None)
