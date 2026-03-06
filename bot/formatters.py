from __future__ import annotations

import html

from claude.models import (
    CostSummary,
    StopEvent,
    ToolResultEvent,
    ToolUseEvent,
    TranscriptContentBlock,
    TranscriptEntry,
    TranscriptTextBlock,
    TranscriptThinkingBlock,
    TranscriptToolResultBlock,
    TranscriptToolUseBlock,
)
from parser.ansi import strip_ansi

_MAX_MESSAGE_CHARS = 4000  # Telegram limit is 4096, leave margin


def format_terminal_output(text: str, line_limit: int = 30) -> tuple[str, bool]:
    clean = strip_ansi(text)
    lines = clean.splitlines()
    truncated = len(lines) > line_limit
    if truncated:
        lines = lines[-line_limit:]
    output = "\n".join(lines)
    if len(output) > _MAX_MESSAGE_CHARS:
        output = output[-_MAX_MESSAGE_CHARS:]
        truncated = True
    return f"<pre>{_escape_html(output)}</pre>", truncated


def format_tool_running(event: ToolUseEvent) -> str:
    target = event.input_summary or event.tool_name
    return f"Running {event.tool_name} on {target}..."


def format_tool_result(event: ToolResultEvent) -> str:
    if event.success:
        summary = event.output_summary[:200] if event.output_summary else "Done"
        return f"{event.tool_name}: {summary}"
    error = event.error or "Unknown error"
    return f"{event.tool_name} failed: {error}"


def format_tool_failure(event: ToolResultEvent) -> str:
    error = event.error or event.output_summary or "Unknown error"
    return f"{event.tool_name} failed: {error[:300]}"


def format_thinking_block(thinking: str) -> str:
    # Telegram expandable quote using blockquote
    preview = thinking[:100].replace("\n", " ")
    if len(thinking) > 100:
        preview += "..."
    return f"<blockquote expandable>{_escape_html(thinking)}</blockquote>"


def format_stop_event(event: StopEvent) -> str:
    parts = ["Task completed"]
    if event.cost_usd > 0:
        parts.append(f"Cost: ${event.cost_usd:.4f}")
    if event.input_tokens > 0:
        parts.append(f"In: {event.input_tokens:,} tokens")
    if event.output_tokens > 0:
        parts.append(f"Out: {event.output_tokens:,} tokens")
    if event.duration_ms > 0:
        secs = event.duration_ms / 1000
        parts.append(f"Duration: {secs:.1f}s")
    return " | ".join(parts)


def format_cost_summary(summary: CostSummary) -> str:
    return (
        f"Session cost: ${summary.total_cost_usd:.4f} | "
        f"In: {summary.total_input_tokens:,} | "
        f"Out: {summary.total_output_tokens:,}"
    )


def format_transcript_entry(entry: TranscriptEntry) -> list[str]:
    messages: list[str] = []
    for block in entry.content:
        formatted = _format_content_block(block)
        if formatted:
            messages.append(formatted)
    return messages


def _format_content_block(block: TranscriptContentBlock) -> str | None:
    if isinstance(block, TranscriptTextBlock):
        if block.text.strip():
            return block.text
        return None
    if isinstance(block, TranscriptThinkingBlock):
        if block.thinking.strip():
            return format_thinking_block(block.thinking)
        return None
    if isinstance(block, TranscriptToolUseBlock):
        return None  # Skip individual tool use noise
    if isinstance(block, TranscriptToolResultBlock):
        if block.is_error:
            return f"Error: {block.content[:300]}"
        return None
    return None


def format_activity_notification(window_name: str, pane_index: int) -> str:
    return f"Activity in window '{window_name}' / pane {pane_index}"


def format_prompt_source(window_name: str, pane_index: int, description: str) -> str:
    return f"[window '{window_name}' / pane {pane_index}] {description}"


def format_status_line(text: str) -> str:
    return f"* {text}"


def format_subagent_start(description: str) -> str:
    return f"Spawned subagent for {description}" if description else "Spawned subagent"


def format_subagent_stop() -> str:
    return "Subagent finished"


def truncate_for_telegram(text: str) -> str:
    if len(text) <= _MAX_MESSAGE_CHARS:
        return text
    return text[: _MAX_MESSAGE_CHARS - 3] + "..."


def _escape_html(text: str) -> str:
    return html.escape(text, quote=False)
