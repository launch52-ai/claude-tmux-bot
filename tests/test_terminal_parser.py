from __future__ import annotations

from parser.terminal import (
    AskUserMulti,
    AskUserSingle,
    BashApproval,
    ExitPlanModePrompt,
    IdlePrompt,
    PermissionPrompt,
    RestoreCheckpointPrompt,
    YesNoPrompt,
    detect_prompt,
)


def test_detect_idle_prompt() -> None:
    result = detect_prompt("some output\n❯ ")
    assert isinstance(result, IdlePrompt)


def test_detect_idle_dollar() -> None:
    result = detect_prompt("output\n$ ")
    assert isinstance(result, IdlePrompt)


def test_detect_bash_approval() -> None:
    text = "Bash command: npm install express"
    result = detect_prompt(text)
    assert isinstance(result, BashApproval)
    assert "npm install express" in result.command


def test_detect_permission_edit() -> None:
    text = "Do you want to edit src/main.py?"
    result = detect_prompt(text)
    assert isinstance(result, PermissionPrompt)
    assert "edit" in result.description.lower()


def test_detect_permission_allow() -> None:
    text = "Allow Claude to create new_file.ts?"
    result = detect_prompt(text)
    assert isinstance(result, PermissionPrompt)


def test_detect_exit_plan_mode() -> None:
    text = """Would you like to proceed?
1) Implement
2) Clear context and implement
3) Edit plan"""
    result = detect_prompt(text)
    assert isinstance(result, ExitPlanModePrompt)
    assert len(result.options) == 3
    assert result.options[0] == "Implement"


def test_detect_numbered_options_single() -> None:
    text = """Choose an option:
1) First option
2) Second option
3) Third option"""
    result = detect_prompt(text)
    assert isinstance(result, AskUserSingle)
    assert len(result.options) == 3


def test_detect_multi_select() -> None:
    text = """Select items:
☐ Option A
✔ Option B
☐ Option C"""
    result = detect_prompt(text)
    assert isinstance(result, AskUserMulti)
    assert len(result.options) == 3
    assert result.selected == [False, True, False]


def test_detect_restore_checkpoint() -> None:
    text = "Would you like to restore the code to a previous checkpoint?"
    result = detect_prompt(text)
    assert isinstance(result, RestoreCheckpointPrompt)


def test_detect_yes_no() -> None:
    text = "Continue? Yes/No"
    result = detect_prompt(text)
    assert isinstance(result, YesNoPrompt)


def test_no_prompt_detected() -> None:
    text = "Just some regular terminal output\nnothing special here"
    result = detect_prompt(text)
    assert result is None


def test_empty_input() -> None:
    result = detect_prompt("")
    assert result is None
