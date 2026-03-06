from __future__ import annotations

import json
import tempfile
from pathlib import Path

from watcher.state import BotState, PaneState, StateManager, TopicState


def _make_state_manager() -> tuple[StateManager, Path]:
    tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    tmp.close()
    path = Path(tmp.name)
    path.unlink(missing_ok=True)
    return StateManager(path), path


def test_save_and_load() -> None:
    sm, path = _make_state_manager()
    sm.bot_state.topic_mode = "window"
    sm.bot_state.control_topic_id = 42
    sm.bot_state.caffeinate_active = True

    ts = sm.ensure_topic_state("myproject", 100)
    sm.ensure_pane_state("myproject", "%0")
    sm.set_focused_pane(100, "%0")

    sm.save()

    sm2 = StateManager(path)
    sm2.load()
    assert sm2.bot_state.topic_mode == "window"
    assert sm2.bot_state.control_topic_id == 42
    assert sm2.bot_state.caffeinate_active is True
    assert "myproject" in sm2.bot_state.topics
    assert sm2.bot_state.topics["myproject"].focused_pane_id == "%0"
    path.unlink(missing_ok=True)


def test_focus_management() -> None:
    sm, path = _make_state_manager()
    ts = sm.ensure_topic_state("sess", 10)
    sm.ensure_pane_state("sess", "%0")
    sm.ensure_pane_state("sess", "%1")

    sm.set_focused_pane(10, "%0")
    assert sm.get_focused_pane(10) == "%0"
    assert ts.panes["%0"].is_focused is True

    sm.set_focused_pane(10, "%1")
    assert sm.get_focused_pane(10) == "%1"
    assert ts.panes["%0"].is_focused is False
    assert ts.panes["%1"].is_focused is True
    path.unlink(missing_ok=True)


def test_direct_mode() -> None:
    sm, path = _make_state_manager()
    sm.ensure_topic_state("sess", 10)

    assert sm.is_direct_mode(10) is False
    result = sm.toggle_direct_mode(10)
    assert result is True
    assert sm.is_direct_mode(10) is True

    result = sm.toggle_direct_mode(10)
    assert result is False
    assert sm.is_direct_mode(10) is False
    path.unlink(missing_ok=True)


def test_claude_pane_marking() -> None:
    sm, path = _make_state_manager()
    sm.ensure_topic_state("sess", 10)
    sm.ensure_pane_state("sess", "%0")

    assert sm.is_claude_pane("%0") is False
    sm.mark_claude_pane("%0", True)
    assert sm.is_claude_pane("%0") is True
    sm.mark_claude_pane("%0", False)
    assert sm.is_claude_pane("%0") is False
    path.unlink(missing_ok=True)


def test_tool_msg_ids() -> None:
    sm, path = _make_state_manager()
    sm.ensure_topic_state("sess", 10)
    sm.ensure_pane_state("sess", "%0")

    assert sm.get_tool_msg_id("%0", "tu_1") is None
    sm.set_tool_msg_id("%0", "tu_1", 999)
    assert sm.get_tool_msg_id("%0", "tu_1") == 999
    path.unlink(missing_ok=True)


def test_action_bar_msg_id() -> None:
    sm, path = _make_state_manager()
    sm.ensure_topic_state("sess", 10)

    assert sm.get_action_bar_msg_id(10) is None
    sm.set_action_bar_msg_id(10, 555)
    assert sm.get_action_bar_msg_id(10) == 555
    path.unlink(missing_ok=True)


def test_remove_topic() -> None:
    sm, path = _make_state_manager()
    sm.ensure_topic_state("sess", 10)
    sm.ensure_pane_state("sess", "%0")

    assert sm.get_topic_by_target("sess") is not None
    sm.remove_topic("sess")
    assert sm.get_topic_by_target("sess") is None
    path.unlink(missing_ok=True)


def test_all_pane_ids() -> None:
    sm, path = _make_state_manager()
    sm.ensure_topic_state("s1", 10)
    sm.ensure_pane_state("s1", "%0")
    sm.ensure_pane_state("s1", "%1")
    sm.ensure_topic_state("s2", 20)
    sm.ensure_pane_state("s2", "%2")

    pane_ids = sm.all_pane_ids()
    assert set(pane_ids) == {"%0", "%1", "%2"}
    path.unlink(missing_ok=True)


def test_get_topic_id_for_pane() -> None:
    sm, path = _make_state_manager()
    sm.ensure_topic_state("s1", 10)
    sm.ensure_pane_state("s1", "%0")

    assert sm.get_topic_id_for_pane("%0") == 10
    assert sm.get_topic_id_for_pane("%99") is None
    path.unlink(missing_ok=True)


def test_load_missing_file() -> None:
    sm = StateManager(Path("/nonexistent/state.json"))
    sm.load()  # Should not raise
    assert sm.bot_state.topic_mode == "session"
