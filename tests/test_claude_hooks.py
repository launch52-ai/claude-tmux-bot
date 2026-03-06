from __future__ import annotations

import json
import tempfile
from pathlib import Path

from claude.hooks import parse_hook_event, parse_tool_use, parse_tool_result, parse_stop_event
from claude.models import HookEvent, HookPayload


def _write_event(tmp: Path, event: str, data: dict) -> Path:
    payload = {
        "event": event,
        "session_id": "test-session",
        "pane_id": "%0",
        "timestamp": 1700000000,
        "data": data,
    }
    filepath = tmp / "test_event.json"
    filepath.write_text(json.dumps(payload))
    return filepath


def test_parse_hook_event() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        filepath = _write_event(Path(tmp), "PreToolUse", {"tool_name": "Edit", "input": {"file_path": "main.py"}})
        payload = parse_hook_event(filepath)
        assert payload is not None
        assert payload.event == HookEvent.PRE_TOOL_USE
        assert payload.session_id == "test-session"
        assert payload.pane_id == "%0"


def test_parse_tool_use() -> None:
    payload = HookPayload(
        event=HookEvent.PRE_TOOL_USE,
        session_id="s1",
        pane_id="%0",
        timestamp=1.0,
        data={"tool_name": "Edit", "tool_use_id": "tu_1", "input": {"file_path": "src/app.py"}},
    )
    tool = parse_tool_use(payload)
    assert tool.tool_name == "Edit"
    assert tool.file_path == "src/app.py"
    assert tool.tool_use_id == "tu_1"


def test_parse_tool_result_success() -> None:
    payload = HookPayload(
        event=HookEvent.POST_TOOL_USE,
        session_id="s1",
        pane_id="%0",
        timestamp=1.0,
        data={"tool_name": "Edit", "tool_use_id": "tu_1", "output": "File edited successfully"},
    )
    result = parse_tool_result(payload)
    assert result.success is True
    assert result.tool_name == "Edit"


def test_parse_tool_result_failure() -> None:
    payload = HookPayload(
        event=HookEvent.POST_TOOL_USE_FAILURE,
        session_id="s1",
        pane_id="%0",
        timestamp=1.0,
        data={"tool_name": "Bash", "tool_use_id": "tu_2", "error": "Command failed"},
    )
    result = parse_tool_result(payload)
    assert result.success is False
    assert result.error == "Command failed"


def test_parse_stop_event() -> None:
    payload = HookPayload(
        event=HookEvent.STOP,
        session_id="s1",
        pane_id="%0",
        timestamp=1.0,
        data={"cost_usd": 0.05, "input_tokens": 1000, "output_tokens": 500, "duration_ms": 3000},
    )
    stop = parse_stop_event(payload)
    assert stop.cost_usd == 0.05
    assert stop.input_tokens == 1000
    assert stop.output_tokens == 500


def test_parse_invalid_event() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        filepath = Path(tmp) / "bad.json"
        filepath.write_text("not json")
        payload = parse_hook_event(filepath)
        assert payload is None
