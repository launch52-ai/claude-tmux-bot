from __future__ import annotations

import json
import tempfile
from pathlib import Path

from claude.models import (
    TranscriptRole,
    TranscriptTextBlock,
    TranscriptThinkingBlock,
    TranscriptToolUseBlock,
    TranscriptToolResultBlock,
)
from claude.transcript import TranscriptReader, extract_cost_summary


def _make_transcript(lines: list[dict]) -> Path:
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
    for line in lines:
        tmp.write(json.dumps(line) + "\n")
    tmp.flush()
    return Path(tmp.name)


def test_read_text_entry() -> None:
    path = _make_transcript([
        {
            "role": "assistant",
            "timestamp": "2024-01-01T00:00:00Z",
            "content": [{"type": "text", "text": "Hello, world!"}],
        }
    ])
    reader = TranscriptReader(path)
    entries = reader.read_new_entries()
    assert len(entries) == 1
    assert entries[0].role == TranscriptRole.ASSISTANT
    assert isinstance(entries[0].content[0], TranscriptTextBlock)
    assert entries[0].content[0].text == "Hello, world!"


def test_read_thinking_block() -> None:
    path = _make_transcript([
        {
            "role": "assistant",
            "timestamp": "2024-01-01T00:00:00Z",
            "content": [{"type": "thinking", "thinking": "Let me think..."}],
        }
    ])
    reader = TranscriptReader(path)
    entries = reader.read_new_entries()
    assert len(entries) == 1
    assert isinstance(entries[0].content[0], TranscriptThinkingBlock)
    assert entries[0].content[0].thinking == "Let me think..."


def test_read_tool_use_block() -> None:
    path = _make_transcript([
        {
            "role": "assistant",
            "timestamp": "2024-01-01T00:00:00Z",
            "content": [
                {"type": "tool_use", "id": "tu_1", "name": "Read", "input": {"file_path": "test.py"}},
            ],
        }
    ])
    reader = TranscriptReader(path)
    entries = reader.read_new_entries()
    block = entries[0].content[0]
    assert isinstance(block, TranscriptToolUseBlock)
    assert block.tool_name == "Read"
    assert block.input == {"file_path": "test.py"}


def test_read_tool_result_block() -> None:
    path = _make_transcript([
        {
            "role": "user",
            "timestamp": "2024-01-01T00:00:00Z",
            "content": [
                {"type": "tool_result", "tool_use_id": "tu_1", "content": "file contents here", "is_error": False},
            ],
        }
    ])
    reader = TranscriptReader(path)
    entries = reader.read_new_entries()
    block = entries[0].content[0]
    assert isinstance(block, TranscriptToolResultBlock)
    assert block.tool_use_id == "tu_1"
    assert block.is_error is False


def test_byte_offset_tracking() -> None:
    path = _make_transcript([
        {"role": "user", "timestamp": "t1", "content": "Hello"},
    ])
    reader = TranscriptReader(path)

    entries1 = reader.read_new_entries()
    assert len(entries1) == 1

    # Second read without new data — returns nothing
    entries2 = reader.read_new_entries()
    assert len(entries2) == 0

    # Append new data
    with path.open("a") as f:
        f.write(json.dumps({"role": "assistant", "timestamp": "t2", "content": "World"}) + "\n")

    entries3 = reader.read_new_entries()
    assert len(entries3) == 1
    assert entries3[0].role == TranscriptRole.ASSISTANT


def test_extract_cost_summary() -> None:
    path = _make_transcript([
        {"role": "assistant", "timestamp": "t1", "content": "Hi", "costUSD": 0.01, "inputTokens": 100, "outputTokens": 50},
        {"role": "assistant", "timestamp": "t2", "content": "Bye", "costUSD": 0.02, "inputTokens": 200, "outputTokens": 100},
    ])
    reader = TranscriptReader(path)
    entries = reader.read_new_entries()
    summary = extract_cost_summary(entries)
    assert summary is not None
    assert abs(summary.total_cost_usd - 0.03) < 1e-9
    assert summary.total_input_tokens == 300
    assert summary.total_output_tokens == 150


def test_missing_file() -> None:
    reader = TranscriptReader(Path("/nonexistent/file.jsonl"))
    entries = reader.read_new_entries()
    assert entries == []
