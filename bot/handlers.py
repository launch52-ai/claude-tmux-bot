from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from bot import keyboards
from bot.formatters import format_terminal_output, truncate_for_telegram
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


def _get_topic_id(message: Message) -> int | None:
    return message.message_thread_id


def _wrong_topic_reply(expected: str) -> str:
    return f"This command works in a {expected} topic."


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
    lines = [
        f"Mode: {topics.topic_mode}",
        f"Sessions: {len(sessions)}",
        f"Caffeinate: {'on' if state.bot_state.caffeinate_active else 'off'}",
        f"Topics: {len(topics.all_targets())}",
    ]
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
    await message.reply(text, parse_mode="Markdown", reply_markup=markup)


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
async def cmd_kill_window(message: Message, **_: Any) -> None:
    await message.reply("Use with caution. Not yet fully implemented.")


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


@session_router.message(Command("history"))
async def cmd_history(message: Message, **_: Any) -> None:
    await message.reply("Message history browsing not yet implemented.")


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
    await tmux.send_keys_claude(pane_id, cmd)
    await callback.answer(f"Sent {cmd}")


@control_router.callback_query(F.data.startswith("dir:"))
async def handle_dir_browse(
    callback: CallbackQuery,
    **_: Any,
) -> None:
    path = Path((callback.data or "").split(":", 1)[1])
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
async def handle_dir_up(callback: CallbackQuery, **_: Any) -> None:
    path = Path((callback.data or "").split(":", 1)[1])
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
    **_: Any,
) -> None:
    path_str = (callback.data or "").split(":", 1)[1]
    path = Path(path_str)

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
