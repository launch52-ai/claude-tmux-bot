from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class HookEvent(str, Enum):
    PRE_TOOL_USE = "PreToolUse"
    POST_TOOL_USE = "PostToolUse"
    POST_TOOL_USE_FAILURE = "PostToolUseFailure"
    STOP = "Stop"
    NOTIFICATION = "Notification"
    USER_PROMPT_SUBMIT = "UserPromptSubmit"
    SESSION_START = "SessionStart"
    SESSION_END = "SessionEnd"
    SUBAGENT_START = "SubagentStart"
    SUBAGENT_STOP = "SubagentStop"


class NotificationType(str, Enum):
    PERMISSION_PROMPT = "permission_prompt"
    IDLE_PROMPT = "idle_prompt"
    AUTH_SUCCESS = "auth_success"
    ELICITATION_DIALOG = "elicitation_dialog"


@dataclass(frozen=True)
class HookPayload:
    event: HookEvent
    session_id: str
    pane_id: str
    timestamp: float
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolUseEvent:
    tool_use_id: str
    tool_name: str
    file_path: str | None = None
    command: str | None = None
    input_summary: str = ""


@dataclass(frozen=True)
class ToolResultEvent:
    tool_use_id: str
    tool_name: str
    success: bool
    output_summary: str = ""
    error: str | None = None


@dataclass(frozen=True)
class StopEvent:
    session_id: str
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    duration_ms: int = 0


@dataclass(frozen=True)
class SubagentEvent:
    session_id: str
    subagent_id: str
    description: str = ""


# -- Transcript entry types --


class TranscriptRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


@dataclass(frozen=True)
class TranscriptTextBlock:
    text: str


@dataclass(frozen=True)
class TranscriptThinkingBlock:
    thinking: str


@dataclass(frozen=True)
class TranscriptToolUseBlock:
    tool_use_id: str
    tool_name: str
    input: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TranscriptToolResultBlock:
    tool_use_id: str
    content: str = ""
    is_error: bool = False


TranscriptContentBlock = (
    TranscriptTextBlock
    | TranscriptThinkingBlock
    | TranscriptToolUseBlock
    | TranscriptToolResultBlock
)


@dataclass(frozen=True)
class TranscriptEntry:
    role: TranscriptRole
    timestamp: str
    content: list[TranscriptContentBlock] = field(default_factory=list)
    cost_usd: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None


@dataclass(frozen=True)
class CostSummary:
    total_cost_usd: float
    total_input_tokens: int
    total_output_tokens: int
    session_id: str = ""
