from __future__ import annotations

import asyncio
import logging
import signal
import sys

from aiogram import Bot, Dispatcher

from bot.handlers import control_router, session_router, setup_routers
from bot.middleware import AuthMiddleware
from bot.topics import TopicManager
from claude.hooks import install_hooks
from config import Settings
from tmux.manager import TmuxManager
from watcher.claude_watcher import ClaudeWatcher
from watcher.pane_watcher import PaneWatcher
from watcher.session_watcher import SessionWatcher
from watcher.state import StateManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def _startup(
    bot: Bot,
    settings: Settings,
    tmux: TmuxManager,
    topics: TopicManager,
    state: StateManager,
) -> None:
    # 1. Load persisted state
    state.load()
    topics.load_state(
        topic_map={t: ts.topic_id for t, ts in state.bot_state.topics.items()},
        control_topic_id=state.bot_state.control_topic_id,
        topic_mode=state.bot_state.topic_mode,
    )

    # 2. Install Claude Code hooks
    install_hooks()

    # 3. Ensure Control topic exists
    control_id = await topics.ensure_control_topic()
    state.bot_state.control_topic_id = control_id

    # 4. Discover and sync tmux sessions
    if tmux.is_available():
        sessions = tmux.list_sessions()
        await topics.sync_sessions(sessions)

        # Register pane states
        for session in sessions:
            if topics.topic_mode == "session":
                target = session.session_name
                topic_id = topics.get_topic_id(target)
                if topic_id is not None:
                    ts = state.ensure_topic_state(target, topic_id)
                    for window in session.windows:
                        for pane in window.panes:
                            state.ensure_pane_state(target, pane.pane_id)
                            if not ts.focused_pane_id:
                                state.set_focused_pane(topic_id, pane.pane_id)
            else:
                for window in session.windows:
                    target = f"{session.session_name}:{window.window_name}"
                    topic_id = topics.get_topic_id(target)
                    if topic_id is not None:
                        ts = state.ensure_topic_state(target, topic_id)
                        for pane in window.panes:
                            state.ensure_pane_state(target, pane.pane_id)
                            if not ts.focused_pane_id:
                                state.set_focused_pane(topic_id, pane.pane_id)

        logger.info("Synced %d sessions", len(sessions))
    else:
        logger.warning("tmux server not available at startup")

    # 5. Start caffeinate if configured
    if settings.caffeinate:
        await state.start_caffeinate()

    # 6. Save state
    state.save()

    # 7. Notify control topic
    await bot.send_message(
        chat_id=settings.chat_id,
        message_thread_id=control_id,
        text="Bot started.",
    )

    logger.info("Startup complete")


async def _shutdown(
    bot: Bot,
    settings: Settings,
    state: StateManager,
    session_watcher: SessionWatcher,
    claude_watcher: ClaudeWatcher,
    pane_watcher: PaneWatcher,
) -> None:
    logger.info("Shutting down...")

    session_watcher.stop()
    claude_watcher.stop()
    pane_watcher.stop()

    await state.stop_caffeinate()
    state.save()

    control_id = state.bot_state.control_topic_id
    if control_id:
        try:
            await bot.send_message(
                chat_id=settings.chat_id,
                message_thread_id=control_id,
                text="Bot shutting down.",
            )
        except Exception:
            pass

    await bot.session.close()
    logger.info("Shutdown complete")


async def main() -> None:
    settings = Settings()  # type: ignore[call-arg]
    bot = Bot(token=settings.bot_token)
    dp = Dispatcher()

    # Auth middleware
    dp.update.middleware(AuthMiddleware(settings.allowed_user_id))

    # Core services
    tmux = TmuxManager()
    state = StateManager(settings.state_file)
    topics = TopicManager(bot, settings.chat_id, settings.topic_mode)

    # Setup routers with dependency injection
    setup_routers(dp, topics, tmux, state, settings)

    # Inject dependencies into handler context
    dp["tmux"] = tmux
    dp["state"] = state
    dp["topics"] = topics
    dp["settings"] = settings
    dp["bot"] = bot

    # Watchers
    session_watcher = SessionWatcher(
        bot, settings.chat_id, tmux, topics, state
    )
    claude_watcher = ClaudeWatcher(bot, settings.chat_id, state)
    pane_watcher = PaneWatcher(bot, settings.chat_id, tmux, state, settings)

    # Startup
    await _startup(bot, settings, tmux, topics, state)

    # Run all tasks
    async def _run_polling() -> None:
        await dp.start_polling(bot)

    tasks = [
        asyncio.create_task(_run_polling(), name="polling"),
        asyncio.create_task(session_watcher.start(), name="session_watcher"),
        asyncio.create_task(claude_watcher.start(), name="claude_watcher"),
        asyncio.create_task(pane_watcher.start(), name="pane_watcher"),
    ]

    # Handle shutdown signals
    loop = asyncio.get_event_loop()
    shutdown_event = asyncio.Event()

    def _signal_handler() -> None:
        shutdown_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _signal_handler)

    # Wait for shutdown
    await shutdown_event.wait()

    # Cancel tasks
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)

    await _shutdown(bot, settings, state, session_watcher, claude_watcher, pane_watcher)


if __name__ == "__main__":
    asyncio.run(main())
