from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from aiogram import BaseMiddleware, Bot, Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message, TelegramObject

import time

from bot import keyboards
from bot.formatters import format_terminal_output, format_transcript_entry, truncate_for_telegram
from claude.transcript import TranscriptReader, find_transcript_files

_START_TIME = time.monotonic()
from bot.media import (
    save_document,
    save_photo,
    send_file_to_telegram,
    transcribe_voice,
)
from config import Settings

if TYPE_CHECKING:
    from bot.topics import TopicManager
    from tmux.manager import TmuxManager
    from watcher.state import StateManager

logger = logging.getLogger(__name__)

control_router = Router(name="control")
session_router = Router(name="session")


class _TopicScopeMiddleware(BaseMiddleware):
    def __init__(self, scope: str) -> None:
        super().__init__()
        self._scope = scope  # "control" or "session"

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        topics: TopicManager | None = data.get("topics")
        if topics is None:
            return await handler(event, data)

        topic_id: int | None = None
        if isinstance(event, Message):
            topic_id = event.message_thread_id
        elif isinstance(event, CallbackQuery) and event.message:
            topic_id = event.message.message_thread_id

        if topic_id is None:
            return None

        is_control = topics.is_control_topic(topic_id)

        if self._scope == "control" and not is_control:
            if isinstance(event, Message) and event.text and event.text.startswith("/"):
                await event.reply("This command works in the Control topic.")
            return None
        if self._scope == "session" and is_control:
            if isinstance(event, Message) and event.text and event.text.startswith("/"):
                await event.reply("This command works in a session topic.")
            return None

        return await handler(event, data)


control_router.message.middleware(_TopicScopeMiddleware("control"))
control_router.callback_query.middleware(_TopicScopeMiddleware("control"))
session_router.message.middleware(_TopicScopeMiddleware("session"))
session_router.callback_query.middleware(_TopicScopeMiddleware("session"))


def _get_topic_id(message: Message) -> int | None:
    return message.message_thread_id


# ═══════════════════════════════════════════
# Control topic commands
# ═══════════════════════════════════════════


@control_router.message(Command("sessions"))
async def cmd_sessions(message: Message, tmux: TmuxManager, **_: Any) -> None:
    sessions = tmux.list_sessions()
    if not sessions:
        await message.reply("No tmux sessions found.")
        return
    items = [(s.session_name, s.session_id) for s in sessions]
    await message.reply("Sessions:", reply_markup=keyboards.sessions_keyboard(items))


@control_router.message(Command("new_session"))
async def cmd_new_session(
    message: Message,
    tmux: TmuxManager,
    settings: Settings,
    **_: Any,
) -> None:
    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2:
        # Show directory browser
        root = settings.projects_dir
        if root.is_dir():
            dirs = sorted([d for d in root.iterdir() if d.is_dir()])
            await message.reply(
                f"Select a directory (in {root}):",
                reply_markup=keyboards.directory_browser_keyboard(dirs, root),
            )
        else:
            await message.reply("Usage: /new_session <name>")
        return

    name = args[1].strip()
    tmux.create_session(name)
    await message.reply(f"Session '{name}' created.")


@control_router.message(Command("topic_mode"))
async def cmd_topic_mode(
    message: Message,
    topics: TopicManager,
    tmux: TmuxManager,
    **_: Any,
) -> None:
    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2:
        await message.reply(f"Current mode: {topics.topic_mode}")
        return

    new_mode = args[1].strip().lower()
    if new_mode not in ("session", "window"):
        await message.reply("Mode must be 'session' or 'window'.")
        return

    sessions = tmux.list_sessions()
    await topics.switch_mode(new_mode, sessions)
    await message.reply(f"Switched to {new_mode} mode.")


@control_router.message(Command("caffeinate"))
async def cmd_caffeinate(message: Message, state: StateManager, **_: Any) -> None:
    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2:
        status = "on" if state.bot_state.caffeinate_active else "off"
        await message.reply(f"Caffeinate is {status}.")
        return

    action = args[1].strip().lower()
    if action == "on":
        await state.start_caffeinate()
        await message.reply("Caffeinate enabled. Mac will stay awake.")
    elif action == "off":
        await state.stop_caffeinate()
        await message.reply("Caffeinate disabled.")
    else:
        await message.reply("Usage: /caffeinate [on|off]")


@control_router.message(Command("status"))
async def cmd_status(
    message: Message,
    topics: TopicManager,
    tmux: TmuxManager,
    state: StateManager,
    **_: Any,
) -> None:
    sessions = tmux.list_sessions()
    uptime_s = int(time.monotonic() - _START_TIME)
    hours, rem = divmod(uptime_s, 3600)
    mins, secs = divmod(rem, 60)
    uptime_str = f"{hours}h {mins}m {secs}s"

    lines = [
        f"Mode: {topics.topic_mode}",
        f"Sessions: {len(sessions)}",
        f"Caffeinate: {'on' if state.bot_state.caffeinate_active else 'off'}",
        f"Topics: {len(topics.all_targets())}",
        f"Uptime: {uptime_str}",
    ]

    # Show focused pane and direct mode per topic
    for target, ts in state.bot_state.topics.items():
        focused = ts.focused_pane_id or "none"
        direct = "on" if ts.direct_mode else "off"
        lines.append(f"  {target}: focused={focused}, direct={direct}")

    await message.reply("\n".join(lines))


@control_router.message(Command("service"))
async def cmd_service(message: Message, **_: Any) -> None:
    import service

    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2:
        await message.reply("Usage: /service [install|uninstall|status]")
        return

    action = args[1].strip().lower()
    if action == "install":
        result = service.install()
    elif action == "uninstall":
        result = service.uninstall()
    elif action == "status":
        result = service.status()
    else:
        result = "Usage: /service [install|uninstall|status]"
    await message.reply(result)


# ═══════════════════════════════════════════
# Session/window topic commands
# ═══════════════════════════════════════════


@session_router.message(Command("send"))
async def cmd_send(
    message: Message,
    tmux: TmuxManager,
    state: StateManager,
    **_: Any,
) -> None:
    topic_id = _get_topic_id(message)
    if topic_id is None:
        return

    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2:
        await message.reply("Usage: /send <text>")
        return

    text = args[1]
    pane_id = state.get_focused_pane(topic_id)
    if not pane_id:
        await message.reply("No pane focused in this topic.")
        return

    is_claude = state.is_claude_pane(pane_id)
    if is_claude:
        await tmux.send_keys_claude(pane_id, text)
    else:
        tmux.send_keys(pane_id, text)


@session_router.message(Command("direct"))
async def cmd_direct(message: Message, state: StateManager, **_: Any) -> None:
    topic_id = _get_topic_id(message)
    if topic_id is None:
        return

    new_state = state.toggle_direct_mode(topic_id)
    mode_str = "on" if new_state else "off"
    await message.reply(f"Direct mode: {mode_str}")


@session_router.message(Command("capture"))
async def cmd_capture(
    message: Message,
    tmux: TmuxManager,
    state: StateManager,
    settings: Settings,
    **_: Any,
) -> None:
    topic_id = _get_topic_id(message)
    if topic_id is None:
        return

    pane_id = state.get_focused_pane(topic_id)
    if not pane_id:
        await message.reply("No pane focused.")
        return

    content = tmux.capture_pane(pane_id)
    if content is None:
        await message.reply("Failed to capture pane.")
        return

    text, truncated = format_terminal_output(content, settings.text_line_limit)
    markup = keyboards.screenshot_button() if truncated else None
    await message.reply(text, parse_mode="HTML", reply_markup=markup)


@session_router.message(Command("screenshot"))
async def cmd_screenshot(
    message: Message,
    tmux: TmuxManager,
    state: StateManager,
    bot: Bot,
    settings: Settings,
    **_: Any,
) -> None:
    topic_id = _get_topic_id(message)
    if topic_id is None:
        return

    pane_id = state.get_focused_pane(topic_id)
    if not pane_id:
        await message.reply("No pane focused.")
        return

    from tmux.screenshot import render_pane_screenshot

    png_data = render_pane_screenshot(tmux, pane_id)
    if png_data is None:
        await message.reply("Failed to render screenshot.")
        return

    from aiogram.types import BufferedInputFile

    photo = BufferedInputFile(png_data, filename="screenshot.png")
    await bot.send_photo(
        chat_id=message.chat.id,
        photo=photo,
        message_thread_id=topic_id,
    )


@session_router.message(Command("key"))
async def cmd_key(
    message: Message,
    tmux: TmuxManager,
    state: StateManager,
    **_: Any,
) -> None:
    topic_id = _get_topic_id(message)
    if topic_id is None:
        return

    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2:
        await message.reply("Usage: /key <combo> (e.g., /key ctrl+a, /key up)")
        return

    pane_id = state.get_focused_pane(topic_id)
    if not pane_id:
        await message.reply("No pane focused.")
        return

    key = _translate_key(args[1].strip())
    tmux.send_special_key(pane_id, key)


@session_router.message(Command("claude"))
async def cmd_claude(message: Message, state: StateManager, **_: Any) -> None:
    topic_id = _get_topic_id(message)
    if topic_id is None:
        return

    pane_id = state.get_focused_pane(topic_id)
    if pane_id and state.is_claude_pane(pane_id):
        await message.reply(
            "Claude commands:",
            reply_markup=keyboards.claude_commands_keyboard(),
        )
    else:
        await message.reply("Focused pane is not running Claude Code.")


@session_router.message(Command("new_window"))
async def cmd_new_window(
    message: Message,
    tmux: TmuxManager,
    state: StateManager,
    topics: TopicManager,
    **_: Any,
) -> None:
    topic_id = _get_topic_id(message)
    if topic_id is None:
        return

    args = (message.text or "").split(maxsplit=1)
    name = args[1].strip() if len(args) > 1 else "new"

    target = topics.get_tmux_target(topic_id)
    if not target:
        await message.reply("No session associated with this topic.")
        return

    session_name = target.split(":")[0]
    window = tmux.create_window(session_name, name)
    if window:
        await message.reply(f"Window '{name}' created.")
    else:
        await message.reply("Failed to create window.")


@session_router.message(Command("split"))
async def cmd_split(
    message: Message,
    tmux: TmuxManager,
    state: StateManager,
    **_: Any,
) -> None:
    topic_id = _get_topic_id(message)
    if topic_id is None:
        return

    pane_id = state.get_focused_pane(topic_id)
    if not pane_id:
        await message.reply("No pane focused.")
        return

    args = (message.text or "").split(maxsplit=1)
    vertical = True
    if len(args) > 1 and args[1].strip().lower() in ("h", "horizontal"):
        vertical = False

    result = tmux.split_pane(pane_id, vertical=vertical)
    if result:
        await message.reply("Pane split.")
    else:
        await message.reply("Failed to split pane.")


@session_router.message(Command("kill_pane"))
async def cmd_kill_pane(
    message: Message,
    tmux: TmuxManager,
    state: StateManager,
    **_: Any,
) -> None:
    topic_id = _get_topic_id(message)
    if topic_id is None:
        return
    pane_id = state.get_focused_pane(topic_id)
    if pane_id and tmux.kill_pane(pane_id):
        await message.reply("Pane killed.")
    else:
        await message.reply("Failed to kill pane.")


@session_router.message(Command("kill_window"))
async def cmd_kill_window(
    message: Message,
    tmux: TmuxManager,
    topics: TopicManager,
    state: StateManager,
    **_: Any,
) -> None:
    topic_id = _get_topic_id(message)
    if topic_id is None:
        return
    target = topics.get_tmux_target(topic_id)
    if not target:
        await message.reply("No session associated.")
        return
    # In window mode, target is "session:window" — find the window
    # In session mode, we need the focused pane's window
    sessions = tmux.list_sessions()
    pane_id = state.get_focused_pane(topic_id)
    for session in sessions:
        for window in session.windows:
            for pane in window.panes:
                if pane.pane_id == pane_id:
                    if tmux.kill_window(window.window_id):
                        await message.reply(f"Window '{window.window_name}' killed.")
                    else:
                        await message.reply("Failed to kill window.")
                    return
    await message.reply("Could not find window for focused pane.")


@session_router.message(Command("kill_session"))
async def cmd_kill_session(
    message: Message,
    tmux: TmuxManager,
    topics: TopicManager,
    **_: Any,
) -> None:
    topic_id = _get_topic_id(message)
    if topic_id is None:
        return
    target = topics.get_tmux_target(topic_id)
    if not target:
        await message.reply("No session associated.")
        return
    session_name = target.split(":")[0]
    if tmux.kill_session(session_name):
        await message.reply(f"Session '{session_name}' killed.")
    else:
        await message.reply("Failed to kill session.")


_HISTORY_PAGE_SIZE = 5


@session_router.message(Command("history"))
async def cmd_history(
    message: Message,
    state: StateManager,
    **_: Any,
) -> None:
    topic_id = _get_topic_id(message)
    if topic_id is None:
        return

    text, kb = _render_history_page(state, topic_id, page=0)
    await message.reply(text, reply_markup=kb)


@session_router.message(Command("file"))
async def cmd_file(
    message: Message,
    bot: Bot,
    settings: Settings,
    **_: Any,
) -> None:
    topic_id = _get_topic_id(message)
    if topic_id is None:
        return

    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2:
        await message.reply("Usage: /file <path>")
        return

    success = await send_file_to_telegram(
        bot, message.chat.id, topic_id, args[1].strip()
    )
    if not success:
        await message.reply("File not found or too large (>50MB).")


# ═══════════════════════════════════════════
# Direct mode: forward plain text messages
# ═══════════════════════════════════════════


@session_router.message(F.text & ~F.text.startswith("/"))
async def handle_direct_text(
    message: Message,
    tmux: TmuxManager,
    state: StateManager,
    **_: Any,
) -> None:
    topic_id = _get_topic_id(message)
    if topic_id is None:
        return

    if not state.is_direct_mode(topic_id):
        return

    pane_id = state.get_focused_pane(topic_id)
    if not pane_id:
        return

    text = message.text or ""
    if state.is_claude_pane(pane_id):
        await tmux.send_keys_claude(pane_id, text)
    else:
        tmux.send_keys(pane_id, text)


# ═══════════════════════════════════════════
# Voice messages
# ═══════════════════════════════════════════


@session_router.message(F.voice)
async def handle_voice(
    message: Message,
    bot: Bot,
    tmux: TmuxManager,
    state: StateManager,
    settings: Settings,
    **_: Any,
) -> None:
    topic_id = _get_topic_id(message)
    if topic_id is None:
        return

    if not settings.openai_api_key:
        await message.reply("Voice transcription not configured (CTB_OPENAI_API_KEY).")
        return

    pane_id = state.get_focused_pane(topic_id)
    if not pane_id:
        await message.reply("No pane focused.")
        return

    text = await transcribe_voice(bot, message, settings.openai_api_key)
    if not text:
        await message.reply("Failed to transcribe voice message.")
        return

    await message.reply(f"Transcribed: {text}")

    if state.is_claude_pane(pane_id):
        await tmux.send_keys_claude(pane_id, text)
    else:
        tmux.send_keys(pane_id, text)


# ═══════════════════════════════════════════
# Photo & document handling
# ═══════════════════════════════════════════


@session_router.message(F.photo)
async def handle_photo(
    message: Message,
    bot: Bot,
    tmux: TmuxManager,
    state: StateManager,
    **_: Any,
) -> None:
    topic_id = _get_topic_id(message)
    if topic_id is None:
        return

    path = await save_photo(bot, message)
    if not path:
        await message.reply("Failed to save photo.")
        return

    pane_id = state.get_focused_pane(topic_id)
    if pane_id and state.is_claude_pane(pane_id):
        await tmux.send_keys_claude(pane_id, str(path))
        await message.reply(f"Photo saved and path sent to Claude: {path}")
    else:
        await message.reply(f"Photo saved: {path}")


@session_router.message(F.document)
async def handle_document(
    message: Message,
    bot: Bot,
    tmux: TmuxManager,
    state: StateManager,
    **_: Any,
) -> None:
    topic_id = _get_topic_id(message)
    if topic_id is None:
        return

    path = await save_document(bot, message)
    if not path:
        await message.reply("Failed to save file.")
        return

    pane_id = state.get_focused_pane(topic_id)
    if pane_id and state.is_claude_pane(pane_id):
        await tmux.send_keys_claude(pane_id, str(path))
        await message.reply(f"File saved and path sent to Claude: {path}")
    else:
        await message.reply(f"File saved: {path}")


# ═══════════════════════════════════════════
# Callback query handlers
# ═══════════════════════════════════════════


@session_router.callback_query(F.data.startswith("prompt:"))
async def handle_prompt_callback(
    callback: CallbackQuery,
    tmux: TmuxManager,
    state: StateManager,
    **_: Any,
) -> None:
    topic_id = callback.message.message_thread_id if callback.message else None
    if topic_id is None:
        await callback.answer()
        return

    pane_id = state.get_focused_pane(topic_id)
    if not pane_id:
        await callback.answer("No pane focused.")
        return

    action = (callback.data or "").split(":", 1)[1]

    key_map = {
        "yes": "y",
        "always": "a",
        "no": "n",
        "cancel": "Escape",
    }
    key = key_map.get(action, action)
    tmux.send_keys(pane_id, key, enter=True)

    await callback.answer(f"Sent: {action}")
    if callback.message:
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass


@session_router.callback_query(F.data.startswith("choice:"))
async def handle_choice_callback(
    callback: CallbackQuery,
    tmux: TmuxManager,
    state: StateManager,
    **_: Any,
) -> None:
    topic_id = callback.message.message_thread_id if callback.message else None
    if topic_id is None:
        await callback.answer()
        return

    pane_id = state.get_focused_pane(topic_id)
    if not pane_id:
        await callback.answer("No pane focused.")
        return

    choice = (callback.data or "").split(":", 1)[1]
    if choice == "custom":
        await callback.answer("Send your reply as a text message.")
        return

    # Send the 1-indexed choice number
    num = str(int(choice) + 1)
    tmux.send_keys(pane_id, num, enter=True)
    await callback.answer(f"Selected option {num}")
    if callback.message:
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass


@session_router.callback_query(F.data.startswith("plan:"))
async def handle_plan_callback(
    callback: CallbackQuery,
    tmux: TmuxManager,
    state: StateManager,
    **_: Any,
) -> None:
    topic_id = callback.message.message_thread_id if callback.message else None
    if topic_id is None:
        await callback.answer()
        return

    pane_id = state.get_focused_pane(topic_id)
    if not pane_id:
        await callback.answer("No pane focused.")
        return

    choice = (callback.data or "").split(":", 1)[1]
    if choice == "cancel":
        tmux.send_keys(pane_id, "Escape", enter=False)
    else:
        num = str(int(choice) + 1)
        tmux.send_keys(pane_id, num, enter=True)

    await callback.answer()
    if callback.message:
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass


@session_router.callback_query(F.data.startswith("yn:"))
async def handle_yes_no_callback(
    callback: CallbackQuery,
    tmux: TmuxManager,
    state: StateManager,
    **_: Any,
) -> None:
    topic_id = callback.message.message_thread_id if callback.message else None
    if topic_id is None:
        await callback.answer()
        return

    pane_id = state.get_focused_pane(topic_id)
    if not pane_id:
        await callback.answer("No pane focused.")
        return

    answer = (callback.data or "").split(":", 1)[1]
    tmux.send_keys(pane_id, answer[0], enter=True)  # 'y' or 'n'
    await callback.answer()


@session_router.callback_query(F.data.startswith("cp:"))
async def handle_checkpoint_callback(
    callback: CallbackQuery,
    tmux: TmuxManager,
    state: StateManager,
    **_: Any,
) -> None:
    topic_id = callback.message.message_thread_id if callback.message else None
    if topic_id is None:
        await callback.answer()
        return

    pane_id = state.get_focused_pane(topic_id)
    if not pane_id:
        await callback.answer("No pane focused.")
        return

    action = (callback.data or "").split(":", 1)[1]
    action_map = {"code": "1", "conv": "2", "both": "3", "cancel": "Escape"}
    key = action_map.get(action, "Escape")
    if key == "Escape":
        tmux.send_keys(pane_id, key, enter=False)
    else:
        tmux.send_keys(pane_id, key, enter=True)

    await callback.answer()
    if callback.message:
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass


@session_router.callback_query(F.data.startswith("action:"))
async def handle_action_callback(
    callback: CallbackQuery,
    tmux: TmuxManager,
    state: StateManager,
    bot: Bot,
    settings: Settings,
    **_: Any,
) -> None:
    topic_id = callback.message.message_thread_id if callback.message else None
    if topic_id is None:
        await callback.answer()
        return

    pane_id = state.get_focused_pane(topic_id)
    if not pane_id:
        await callback.answer("No pane focused.")
        return

    action = (callback.data or "").split(":", 1)[1]

    if action == "stop":
        tmux.send_special_key(pane_id, "Escape")
        await callback.answer("Stop sent")
    elif action == "escape":
        tmux.send_special_key(pane_id, "Escape")
        await callback.answer("Escape sent")
    elif action == "ctrl_c":
        tmux.send_special_key(pane_id, "C-c")
        await callback.answer("Ctrl+C sent")
    elif action == "screenshot":
        await callback.answer("Rendering screenshot...")
        from tmux.screenshot import render_pane_screenshot
        from aiogram.types import BufferedInputFile

        png_data = render_pane_screenshot(tmux, pane_id)
        if png_data and callback.message:
            photo = BufferedInputFile(png_data, filename="screenshot.png")
            await bot.send_photo(
                chat_id=callback.message.chat.id,
                photo=photo,
                message_thread_id=topic_id,
            )


@session_router.callback_query(F.data.startswith("claude_cmd:"))
async def handle_claude_cmd_callback(
    callback: CallbackQuery,
    tmux: TmuxManager,
    state: StateManager,
    **_: Any,
) -> None:
    topic_id = callback.message.message_thread_id if callback.message else None
    if topic_id is None:
        await callback.answer()
        return

    pane_id = state.get_focused_pane(topic_id)
    if not pane_id:
        await callback.answer("No pane focused.")
        return

    cmd = (callback.data or "").split(":", 1)[1]
    allowed_cmds = {
        "/compact", "/clear", "/cost", "/model", "/memory",
        "/rewind", "/settings", "/help", "/doctor",
    }
    if cmd not in allowed_cmds:
        await callback.answer("Unknown command.")
        return
    await tmux.send_keys_claude(pane_id, cmd)
    await callback.answer(f"Sent {cmd}")


@session_router.callback_query(F.data.startswith("history:"))
async def handle_history_callback(
    callback: CallbackQuery,
    state: StateManager,
    **_: Any,
) -> None:
    topic_id = callback.message.message_thread_id if callback.message else None
    if topic_id is None:
        await callback.answer()
        return

    page = int((callback.data or "history:0").split(":")[1])
    text, kb = _render_history_page(state, topic_id, page)

    try:
        await callback.message.edit_text(text, reply_markup=kb)
    except Exception:
        await callback.answer("Failed to update.")
        return
    await callback.answer()


@control_router.callback_query(F.data.startswith("dir:"))
async def handle_dir_browse(
    callback: CallbackQuery,
    settings: Settings,
    **_: Any,
) -> None:
    path = Path((callback.data or "").split(":", 1)[1]).resolve()
    if not _is_safe_browse_path(path, settings.projects_dir):
        await callback.answer("Path not allowed.")
        return
    if not path.is_dir():
        await callback.answer("Not a directory.")
        return
    dirs = sorted([d for d in path.iterdir() if d.is_dir()])
    if callback.message:
        await callback.message.edit_text(
            f"Browse: {path}",
            reply_markup=keyboards.directory_browser_keyboard(dirs, path),
        )
    await callback.answer()


@control_router.callback_query(F.data.startswith("dir_up:"))
async def handle_dir_up(
    callback: CallbackQuery,
    settings: Settings,
    **_: Any,
) -> None:
    path = Path((callback.data or "").split(":", 1)[1]).resolve()
    if not _is_safe_browse_path(path, settings.projects_dir):
        await callback.answer("Path not allowed.")
        return
    if not path.is_dir():
        await callback.answer("Not a directory.")
        return
    dirs = sorted([d for d in path.iterdir() if d.is_dir()])
    if callback.message:
        await callback.message.edit_text(
            f"Browse: {path}",
            reply_markup=keyboards.directory_browser_keyboard(dirs, path),
        )
    await callback.answer()


@control_router.callback_query(F.data.startswith("dir_select:"))
async def handle_dir_select(
    callback: CallbackQuery,
    tmux: TmuxManager,
    topics: TopicManager,
    settings: Settings,
    **_: Any,
) -> None:
    path_str = (callback.data or "").split(":", 1)[1]
    path = Path(path_str).resolve()

    if not _is_safe_browse_path(path, settings.projects_dir):
        await callback.answer("Path not allowed.")
        return

    name = path.name or "session"
    session = tmux.create_session(name, start_directory=str(path))
    sessions = tmux.list_sessions()
    await topics.sync_sessions(sessions)

    if callback.message:
        await callback.message.edit_text(f"Session '{name}' created in {path}")
    await callback.answer()


@control_router.callback_query(F.data.startswith("dir_page:"))
async def handle_dir_page(callback: CallbackQuery, settings: Settings, **_: Any) -> None:
    page = int((callback.data or "").split(":", 1)[1])
    root = settings.projects_dir
    dirs = sorted([d for d in root.iterdir() if d.is_dir()])
    if callback.message:
        await callback.message.edit_reply_markup(
            reply_markup=keyboards.directory_browser_keyboard(dirs, root, page),
        )
    await callback.answer()


@session_router.callback_query(F.data.startswith("multi:"))
async def handle_multi_callback(
    callback: CallbackQuery,
    tmux: TmuxManager,
    state: StateManager,
    **_: Any,
) -> None:
    topic_id = callback.message.message_thread_id if callback.message else None
    if topic_id is None:
        await callback.answer()
        return

    pane_id = state.get_focused_pane(topic_id)
    if not pane_id:
        await callback.answer("No pane focused.")
        return

    action = (callback.data or "").split(":", 1)[1]

    if action == "submit":
        tmux.send_keys(pane_id, "", enter=True)
        await callback.answer("Submitted")
        if callback.message:
            try:
                await callback.message.edit_reply_markup(reply_markup=None)
            except Exception:
                pass
    elif action == "custom":
        await callback.answer("Send your input as a text message.")
    else:
        # Toggle checkbox — send space to toggle, then arrow to move
        idx = int(action)
        # Navigate to the item and toggle
        tmux.send_keys(pane_id, " ", enter=False)
        await callback.answer(f"Toggled option {idx + 1}")


# ═══════════════════════════════════════════
# Navigation callbacks
# ═══════════════════════════════════════════


@session_router.callback_query(F.data.startswith("sess:"))
async def handle_session_nav(
    callback: CallbackQuery,
    tmux: TmuxManager,
    **_: Any,
) -> None:
    sessions = tmux.list_sessions()
    sess_id = (callback.data or "").split(":", 1)[1]

    for session in sessions:
        if session.session_id == sess_id:
            items = [
                (w.window_name, w.window_id) for w in session.windows
            ]
            if callback.message:
                await callback.message.edit_text(
                    f"Windows in '{session.session_name}':",
                    reply_markup=keyboards.windows_keyboard(items, session.session_name),
                )
            break

    await callback.answer()


@session_router.callback_query(F.data.startswith("win:"))
async def handle_window_nav(
    callback: CallbackQuery,
    tmux: TmuxManager,
    **_: Any,
) -> None:
    win_id = (callback.data or "").split(":", 1)[1]
    sessions = tmux.list_sessions()

    for session in sessions:
        for window in session.windows:
            if window.window_id == win_id:
                items = [
                    (str(p.pane_index), p.pane_id) for p in window.panes
                ]
                if callback.message:
                    await callback.message.edit_text(
                        f"Panes in '{window.window_name}':",
                        reply_markup=keyboards.panes_keyboard(items, window.window_name),
                    )
                await callback.answer()
                return

    await callback.answer("Window not found.")


@session_router.callback_query(F.data.startswith("pane:"))
async def handle_pane_focus(
    callback: CallbackQuery,
    state: StateManager,
    **_: Any,
) -> None:
    topic_id = callback.message.message_thread_id if callback.message else None
    if topic_id is None:
        await callback.answer()
        return

    pane_id = (callback.data or "").split(":", 1)[1]
    state.set_focused_pane(topic_id, pane_id)
    await callback.answer(f"Focused on pane {pane_id}")


@session_router.callback_query(F.data == "nav:back_to_windows")
async def handle_nav_back_to_windows(
    callback: CallbackQuery,
    tmux: TmuxManager,
    **_: Any,
) -> None:
    # Go back to sessions list (user can pick a session to see windows)
    sessions = tmux.list_sessions()
    items = [(s.session_name, s.session_id) for s in sessions]
    if callback.message:
        await callback.message.edit_text(
            "Sessions:",
            reply_markup=keyboards.sessions_keyboard(items),
        )
    await callback.answer()


@session_router.callback_query(F.data == "nav:sessions")
async def handle_nav_sessions(
    callback: CallbackQuery,
    tmux: TmuxManager,
    **_: Any,
) -> None:
    sessions = tmux.list_sessions()
    items = [(s.session_name, s.session_id) for s in sessions]
    if callback.message:
        await callback.message.edit_text(
            "Sessions:",
            reply_markup=keyboards.sessions_keyboard(items),
        )
    await callback.answer()


def _render_history_page(
    state: StateManager,
    topic_id: int,
    page: int,
) -> tuple[str, InlineKeyboardMarkup | None]:
    from claude.models import TranscriptRole

    topic_state = state.get_topic_state(topic_id)
    if topic_state is None:
        return "No session associated with this topic.", None

    # Find the most recent transcript for this topic's target
    files = find_transcript_files()
    if not files:
        return "No transcript files found.", None

    # Read all entries from the most recent file
    reader = TranscriptReader(files[0])
    all_entries = reader.read_new_entries()

    # Filter to assistant entries only
    assistant_entries = [e for e in all_entries if e.role == TranscriptRole.ASSISTANT]
    assistant_entries.reverse()  # newest first

    if not assistant_entries:
        return "No history entries found.", None

    start = page * _HISTORY_PAGE_SIZE
    end = start + _HISTORY_PAGE_SIZE
    page_entries = assistant_entries[start:end]

    if not page_entries:
        return "No more entries.", None

    lines: list[str] = []
    for entry in page_entries:
        parts = format_transcript_entry(entry)
        ts = entry.timestamp[:19] if entry.timestamp else ""
        header = f"[{ts}]" if ts else ""
        for part in parts:
            text = truncate_for_telegram(part)
            if header:
                lines.append(f"{header}\n{text}")
                header = ""
            else:
                lines.append(text)

    body = "\n\n---\n\n".join(lines) if lines else "No content."
    has_older = end < len(assistant_entries)
    kb = keyboards.history_keyboard(page, has_older)

    return body, kb


def _is_safe_browse_path(path: Path, root: Path) -> bool:
    """Ensure path is within the allowed root directory."""
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _translate_key(combo: str) -> str:
    combo = combo.strip().lower()
    translations = {
        "ctrl+a": "C-a",
        "ctrl+b": "C-b",
        "ctrl+c": "C-c",
        "ctrl+d": "C-d",
        "ctrl+e": "C-e",
        "ctrl+g": "C-g",
        "ctrl+l": "C-l",
        "ctrl+z": "C-z",
        "up": "Up",
        "down": "Down",
        "left": "Left",
        "right": "Right",
        "enter": "Enter",
        "escape": "Escape",
        "esc": "Escape",
        "tab": "Tab",
        "space": "Space",
        "backspace": "BSpace",
        "delete": "DC",
        "home": "Home",
        "end": "End",
        "pageup": "PPage",
        "pagedown": "NPage",
    }
    return translations.get(combo, combo)


def setup_routers(
    dp: Dispatcher,
    topics: TopicManager,
    tmux: TmuxManager,
    state: StateManager,
    settings: Settings,
) -> None:
    dp.include_router(control_router)
    dp.include_router(session_router)
