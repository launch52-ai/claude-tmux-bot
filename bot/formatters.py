from __future__ import annotations

import difflib
import html
import re
from pathlib import Path

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
    """Format a transcript entry into Telegram messages.

    Batches all blocks into as few messages as possible (respecting
    Telegram's 4096 char limit).
    """
    parts: list[str] = []
    for block in entry.content:
        formatted = _format_content_block(block, entry.cwd)
        if formatted:
            parts.append(formatted)

    if not parts:
        return []

    # Merge parts into messages, splitting only when Telegram limit is hit
    messages: list[str] = []
    current: list[str] = []
    current_len = 0
    for part in parts:
        # +1 for the \n separator
        if current and current_len + len(part) + 1 > _MAX_MESSAGE_CHARS:
            messages.append("\n".join(current))
            current = []
            current_len = 0
        current.append(part)
        current_len += len(part) + 1
    if current:
        messages.append("\n".join(current))

    return messages


def _format_content_block(block: TranscriptContentBlock, cwd: str = "") -> str | None:
    if isinstance(block, TranscriptTextBlock):
        if block.text.strip():
            return truncate_for_telegram(_markdown_to_telegram_html(block.text))
        return None
    if isinstance(block, TranscriptThinkingBlock):
        if block.thinking.strip():
            return format_thinking_block(block.thinking)
        return None
    if isinstance(block, TranscriptToolUseBlock):
        return None  # Handled in real-time via hooks
    if isinstance(block, TranscriptToolResultBlock):
        if block.is_error:
            return f"Error: {_escape_html(block.content[:300])}"
        return None
    return None


def _format_tool_use_block(block: TranscriptToolUseBlock, cwd: str = "") -> str:
    """Format a tool use block as a concise one-line summary."""
    name = block.tool_name
    inp = block.input

    if name == "Bash":
        cmd = inp.get("command", "")
        desc = inp.get("description", "")
        if len(cmd) > 300:
            cmd = cmd[:300] + "…"
        if desc:
            return f"⏺ <b>Bash</b>({_escape_html(desc)})\n<code>{_escape_html(cmd)}</code>"
        return f"⏺ <b>Bash</b>\n<code>{_escape_html(cmd)}</code>"

    if name in ("Read", "Write"):
        path = inp.get("file_path", "")
        short = _shorten_path(path, cwd)
        return f"⏺ <b>{_escape_html(name)}</b>({_escape_html(short)})"

    if name == "Edit":
        path = inp.get("file_path", "")
        short = _shorten_path(path, cwd)
        old = inp.get("old_string", "")
        new = inp.get("new_string", "")
        diff = _format_diff(old, new)
        return f"⏺ <b>Edit</b>({_escape_html(short)})\n{diff}"

    if name == "Grep":
        pattern = inp.get("pattern", "")
        path = inp.get("path", "")
        short = _shorten_path(path, cwd) if path else "."
        return f"⏺ <b>Grep</b>(<code>{_escape_html(pattern)}</code> in {_escape_html(short)})"

    if name == "Glob":
        pattern = inp.get("pattern", "")
        return f"⏺ <b>Glob</b>(<code>{_escape_html(pattern)}</code>)"

    if name == "Agent":
        prompt = inp.get("prompt", "")[:100]
        return f"⏺ <b>Agent</b>({_escape_html(prompt)})"

    if name == "WebFetch":
        url = inp.get("url", "")
        return f"⏺ <b>WebFetch</b>({_escape_html(url[:100])})"

    if name == "WebSearch":
        query = inp.get("query", "")
        return f"⏺ <b>WebSearch</b>({_escape_html(query[:100])})"

    # Generic fallback
    summary_parts: list[str] = []
    for key, val in inp.items():
        s = str(val)[:80]
        summary_parts.append(f"{key}={s}")
        if len(summary_parts) >= 2:
            break
    detail = ", ".join(summary_parts)
    if len(detail) > 150:
        detail = detail[:150] + "…"
    return f"⏺ <b>{_escape_html(name)}</b>({_escape_html(detail)})"


def _format_diff(old: str, new: str, max_lines: int = 20) -> str:
    """Format old/new strings as a unified-style diff for Telegram."""
    if not old and not new:
        return ""
    old_lines = old.splitlines()
    new_lines = new.splitlines()

    diff_lines: list[str] = []

    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(
        None, old_lines, new_lines
    ).get_opcodes():
        if tag == "equal":
            # Show max 2 context lines around changes
            lines = old_lines[i1:i2]
            if len(lines) <= 4:
                for line in lines:
                    diff_lines.append(f"  {line}")
            else:
                for line in lines[:2]:
                    diff_lines.append(f"  {line}")
                diff_lines.append("  ...")
                for line in lines[-2:]:
                    diff_lines.append(f"  {line}")
        elif tag == "replace":
            for line in old_lines[i1:i2]:
                diff_lines.append(f"- {line}")
            for line in new_lines[j1:j2]:
                diff_lines.append(f"+ {line}")
        elif tag == "delete":
            for line in old_lines[i1:i2]:
                diff_lines.append(f"- {line}")
        elif tag == "insert":
            for line in new_lines[j1:j2]:
                diff_lines.append(f"+ {line}")

    if len(diff_lines) > max_lines:
        diff_lines = diff_lines[:max_lines]
        diff_lines.append("  ...")

    diff_text = "\n".join(diff_lines)
    if len(diff_text) > 1500:
        diff_text = diff_text[:1500] + "\n..."
    return f"<pre>{_escape_html(diff_text)}</pre>"


def _shorten_path(path: str, cwd: str = "") -> str:
    """Shorten paths: strip cwd prefix, then fall back to ~ shortening."""
    if cwd and path.startswith(cwd + "/"):
        return path[len(cwd) + 1:]
    if cwd and path == cwd:
        return "."
    home = str(Path.home())
    if path.startswith(home + "/"):
        return "~" + path[len(home):]
    return path


def format_hook_tool_use(event: ToolUseEvent, cwd: str = "") -> str:
    """Format a real-time hook tool use event for Telegram."""
    block = TranscriptToolUseBlock(
        tool_use_id=event.tool_use_id,
        tool_name=event.tool_name,
        input=event.tool_input,
    )
    return _format_tool_use_block(block, cwd)


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


# Regex for fenced code blocks: ```lang\n...\n```
_RE_CODE_BLOCK = re.compile(r"```(\w*)\n(.*?)```", re.DOTALL)
# Placeholder to protect code blocks during inline processing
_CODE_BLOCK_PH = "\x00CODEBLOCK{}\x00"


def _markdown_to_telegram_html(text: str) -> str:
    """Convert common markdown to Telegram-compatible HTML."""
    # 1. Extract fenced code blocks to protect them from inline processing
    code_blocks: list[str] = []

    def _replace_code_block(m: re.Match) -> str:
        lang = m.group(1)
        code = m.group(2).rstrip("\n")
        escaped = _escape_html(code)
        if lang:
            block = f'<pre><code class="language-{_escape_html(lang)}">{escaped}</code></pre>'
        else:
            block = f"<pre>{escaped}</pre>"
        idx = len(code_blocks)
        code_blocks.append(block)
        return _CODE_BLOCK_PH.format(idx)

    text = _RE_CODE_BLOCK.sub(_replace_code_block, text)

    # 2. Process line by line for headings, then do inline formatting
    lines = text.split("\n")
    result_lines: list[str] = []
    for line in lines:
        # Headers → bold
        header_match = re.match(r"^(#{1,6})\s+(.+)$", line)
        if header_match:
            content = _escape_html(header_match.group(2))
            result_lines.append(f"<b>{content}</b>")
            continue

        # Escape HTML in normal lines first
        line = _escape_html(line)
        result_lines.append(line)

    text = "\n".join(result_lines)

    # 3. Inline formatting (on escaped text, so we match literal chars)
    # Bold: **text** or __text__
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"__(.+?)__", r"<b>\1</b>", text)
    # Italic: *text* or _text_ (but not inside words with underscores)
    text = re.sub(r"(?<!\w)\*([^*]+?)\*(?!\w)", r"<i>\1</i>", text)
    text = re.sub(r"(?<!\w)_([^_]+?)_(?!\w)", r"<i>\1</i>", text)
    # Strikethrough: ~~text~~
    text = re.sub(r"~~(.+?)~~", r"<s>\1</s>", text)
    # Inline code: `text`
    text = re.sub(r"`([^`]+?)`", lambda m: f"<code>{m.group(1)}</code>", text)
    # Links: [text](url)
    text = re.sub(
        r"\[([^\]]+)\]\(([^)]+)\)",
        lambda m: f'<a href="{m.group(2)}">{m.group(1)}</a>',
        text,
    )

    # 4. Restore code blocks
    for idx, block in enumerate(code_blocks):
        text = text.replace(_CODE_BLOCK_PH.format(idx), block)

    return text
