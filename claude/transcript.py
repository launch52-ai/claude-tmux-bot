from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from claude.models import (
    CostSummary,
    TranscriptContentBlock,
    TranscriptEntry,
    TranscriptRole,
    TranscriptTextBlock,
    TranscriptThinkingBlock,
    TranscriptToolResultBlock,
    TranscriptToolUseBlock,
)

logger = logging.getLogger(__name__)

_CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"


class TranscriptReader:
    def __init__(self, filepath: Path) -> None:
        self._filepath = filepath
        self._byte_offset: int = 0

    @property
    def filepath(self) -> Path:
        return self._filepath

    @property
    def byte_offset(self) -> int:
        return self._byte_offset

    def read_new_entries(self) -> list[TranscriptEntry]:
        if not self._filepath.exists():
            return []

        entries: list[TranscriptEntry] = []
        try:
            with self._filepath.open("rb") as f:
                f.seek(self._byte_offset)
                remaining = f.read()
                if not remaining:
                    return []

                new_offset = self._byte_offset + len(remaining)
                text = remaining.decode("utf-8", errors="replace")

                for line in text.strip().splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        raw = json.loads(line)
                        entry = _parse_transcript_entry(raw)
                        if entry is not None:
                            entries.append(entry)
                    except json.JSONDecodeError:
                        logger.debug("Skipping malformed JSONL line")

                self._byte_offset = new_offset
        except OSError:
            logger.exception("Failed to read transcript: %s", self._filepath)

        return entries

    def reset(self) -> None:
        self._byte_offset = 0


def _parse_transcript_entry(raw: dict[str, Any]) -> TranscriptEntry | None:
    role_str = raw.get("role", raw.get("type", ""))
    try:
        role = TranscriptRole(role_str)
    except ValueError:
        return None

    # Content may be at top level or nested inside "message"
    raw_content = raw.get("content", [])
    msg = raw.get("message")
    if isinstance(msg, dict) and not raw_content:
        raw_content = msg.get("content", [])

    content_blocks: list[TranscriptContentBlock] = []

    if isinstance(raw_content, str):
        content_blocks.append(TranscriptTextBlock(text=raw_content))
    elif isinstance(raw_content, list):
        for block in raw_content:
            parsed = _parse_content_block(block)
            if parsed is not None:
                content_blocks.append(parsed)

    return TranscriptEntry(
        role=role,
        timestamp=raw.get("timestamp", ""),
        content=content_blocks,
        cwd=raw.get("cwd", ""),
        cost_usd=raw.get("costUSD") or raw.get("cost_usd"),
        input_tokens=raw.get("inputTokens") or raw.get("input_tokens"),
        output_tokens=raw.get("outputTokens") or raw.get("output_tokens"),
    )


def _parse_content_block(block: Any) -> TranscriptContentBlock | None:
    if isinstance(block, str):
        return TranscriptTextBlock(text=block)
    if not isinstance(block, dict):
        return None

    block_type = block.get("type", "")

    if block_type == "text":
        return TranscriptTextBlock(text=block.get("text", ""))
    if block_type == "thinking":
        return TranscriptThinkingBlock(thinking=block.get("thinking", ""))
    if block_type == "tool_use":
        return TranscriptToolUseBlock(
            tool_use_id=block.get("id", ""),
            tool_name=block.get("name", ""),
            input=block.get("input", {}),
        )
    if block_type == "tool_result":
        content = block.get("content", "")
        if isinstance(content, list):
            content = " ".join(
                c.get("text", "") for c in content if isinstance(c, dict)
            )
        return TranscriptToolResultBlock(
            tool_use_id=block.get("tool_use_id", ""),
            content=str(content)[:2000],
            is_error=block.get("is_error", False),
        )

    return None


def find_transcript_files(session_id: str | None = None) -> list[Path]:
    if not _CLAUDE_PROJECTS_DIR.exists():
        return []

    pattern = "*.jsonl"
    files = sorted(_CLAUDE_PROJECTS_DIR.rglob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)

    if session_id:
        files = [f for f in files if session_id in f.name or session_id in str(f.parent)]

    return files


def extract_cost_summary(entries: list[TranscriptEntry]) -> CostSummary | None:
    total_cost = 0.0
    total_input = 0
    total_output = 0
    found = False

    for entry in entries:
        if entry.cost_usd is not None:
            total_cost += entry.cost_usd
            found = True
        if entry.input_tokens is not None:
            total_input += entry.input_tokens
        if entry.output_tokens is not None:
            total_output += entry.output_tokens

    if not found:
        return None

    return CostSummary(
        total_cost_usd=total_cost,
        total_input_tokens=total_input,
        total_output_tokens=total_output,
    )
