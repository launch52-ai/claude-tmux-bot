from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Union


class PromptType(str, Enum):
    PERMISSION = "permission"
    BASH_APPROVAL = "bash_approval"
    ASK_USER_SINGLE = "ask_user_single"
    ASK_USER_MULTI = "ask_user_multi"
    EXIT_PLAN_MODE = "exit_plan_mode"
    RESTORE_CHECKPOINT = "restore_checkpoint"
    YES_NO = "yes_no"
    TEXT_INPUT = "text_input"
    IDLE = "idle"


@dataclass(frozen=True)
class PermissionPrompt:
    prompt_type: PromptType = PromptType.PERMISSION
    description: str = ""
    tool_name: str = ""
    file_path: str = ""


@dataclass(frozen=True)
class BashApproval:
    prompt_type: PromptType = PromptType.BASH_APPROVAL
    command: str = ""


@dataclass(frozen=True)
class AskUserSingle:
    prompt_type: PromptType = PromptType.ASK_USER_SINGLE
    question: str = ""
    options: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class AskUserMulti:
    prompt_type: PromptType = PromptType.ASK_USER_MULTI
    question: str = ""
    options: list[str] = field(default_factory=list)
    selected: list[bool] = field(default_factory=list)


@dataclass(frozen=True)
class ExitPlanModePrompt:
    prompt_type: PromptType = PromptType.EXIT_PLAN_MODE
    options: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RestoreCheckpointPrompt:
    prompt_type: PromptType = PromptType.RESTORE_CHECKPOINT
    description: str = ""


@dataclass(frozen=True)
class YesNoPrompt:
    prompt_type: PromptType = PromptType.YES_NO
    question: str = ""


@dataclass(frozen=True)
class IdlePrompt:
    prompt_type: PromptType = PromptType.IDLE


DetectedPrompt = Union[
    PermissionPrompt,
    BashApproval,
    AskUserSingle,
    AskUserMulti,
    ExitPlanModePrompt,
    RestoreCheckpointPrompt,
    YesNoPrompt,
    IdlePrompt,
]


# --- Detection patterns ---

_PERMISSION_RE = re.compile(
    r"(?:Do you want to|Allow|wants to)\s+(.+?)(?:\?|$)",
    re.IGNORECASE,
)

_BASH_RE = re.compile(
    r"(?:Bash|Run|Execute)\s*(?:command)?\s*[:>]\s*(.+)",
    re.IGNORECASE | re.DOTALL,
)

_NUMBERED_OPTION_RE = re.compile(r"^\s*(\d+)[.)]\s+(.+)$", re.MULTILINE)

_CHECKBOX_UNCHECKED_RE = re.compile(r"[☐○◯\[\s\]]\s+(.+)")
_CHECKBOX_CHECKED_RE = re.compile(r"[☑✔✓☒✅\[x\]]\s+(.+)", re.IGNORECASE)

_PLAN_MODE_RE = re.compile(
    r"(?:Would you like to proceed|How would you like to proceed|What would you like to do)\s*\?",
    re.IGNORECASE,
)

_RESTORE_RE = re.compile(
    r"(?:Restore|restore the code|restore the conversation|restore checkpoint)",
    re.IGNORECASE,
)

_YES_NO_RE = re.compile(
    r"(?:Yes|No)\s*[/|]\s*(?:Yes|No)",
    re.IGNORECASE,
)

_IDLE_RE = re.compile(r"[❯›>$%#]\s*$")


def detect_prompt(text: str) -> DetectedPrompt | None:
    lines = text.strip().splitlines()
    if not lines:
        return None

    tail = "\n".join(lines[-30:])

    # Check idle prompt first (most common)
    last_line = lines[-1].strip()
    if _IDLE_RE.search(last_line) and len(last_line) < 10:
        return IdlePrompt()

    # Bash approval
    bash_match = _BASH_RE.search(tail)
    if bash_match:
        command = bash_match.group(1).strip()
        return BashApproval(command=command)

    # Plan mode / ExitPlanMode
    if _PLAN_MODE_RE.search(tail):
        options = _extract_numbered_options(tail)
        if options:
            return ExitPlanModePrompt(options=options)

    # Restore checkpoint
    if _RESTORE_RE.search(tail):
        return RestoreCheckpointPrompt(description=tail.strip())

    # Multi-select (checkboxes)
    unchecked = _CHECKBOX_UNCHECKED_RE.findall(tail)
    checked = _CHECKBOX_CHECKED_RE.findall(tail)
    if unchecked or checked:
        all_options = []
        selected = []
        for line in lines[-20:]:
            line_s = line.strip()
            cm = _CHECKBOX_CHECKED_RE.match(line_s)
            um = _CHECKBOX_UNCHECKED_RE.match(line_s)
            if cm:
                all_options.append(cm.group(1).strip())
                selected.append(True)
            elif um:
                all_options.append(um.group(1).strip())
                selected.append(False)
        if all_options:
            question = _extract_question_above(lines, len(lines) - len(all_options) - 1)
            return AskUserMulti(
                question=question,
                options=all_options,
                selected=selected,
            )

    # Permission prompt
    perm_match = _PERMISSION_RE.search(tail)
    if perm_match:
        desc = perm_match.group(1).strip()
        tool_name = ""
        file_path = ""
        # Try to extract tool/file from description
        if "edit" in desc.lower() or "create" in desc.lower() or "delete" in desc.lower():
            parts = desc.rsplit(" ", 1)
            if len(parts) > 1:
                file_path = parts[-1]
        return PermissionPrompt(description=desc, tool_name=tool_name, file_path=file_path)

    # Yes/No
    if _YES_NO_RE.search(tail):
        question = tail.strip()
        return YesNoPrompt(question=question)

    # Single-select with numbered options
    options = _extract_numbered_options(tail)
    if options:
        question = _extract_question_above(lines, len(lines) - len(options) - 1)
        return AskUserSingle(question=question, options=options)

    return None


def _extract_numbered_options(text: str) -> list[str]:
    matches = _NUMBERED_OPTION_RE.findall(text)
    return [m[1].strip() for m in matches]


def _extract_question_above(lines: list[str], index: int) -> str:
    if 0 <= index < len(lines):
        return lines[index].strip()
    return ""
