from __future__ import annotations

from pathlib import Path

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

# --- Navigation ---


def sessions_keyboard(sessions: list[tuple[str, str]]) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text=name, callback_data=f"sess:{sess_id}")]
        for name, sess_id in sessions
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def windows_keyboard(
    windows: list[tuple[str, str]], session_name: str
) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text=name, callback_data=f"win:{win_id}")]
        for name, win_id in windows
    ]
    buttons.append(
        [InlineKeyboardButton(text="<< Back to sessions", callback_data="nav:sessions")]
    )
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def panes_keyboard(
    panes: list[tuple[str, str]], window_name: str
) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text=f"Pane {idx}", callback_data=f"pane:{pane_id}")]
        for idx, pane_id in panes
    ]
    buttons.append(
        [InlineKeyboardButton(text="<< Back", callback_data="nav:back_to_windows")]
    )
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# --- Prompt keyboards ---


def permission_keyboard(always_text: str = "Always Allow") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Yes", callback_data="prompt:yes"),
                InlineKeyboardButton(text=always_text, callback_data="prompt:always"),
            ],
            [
                InlineKeyboardButton(text="No", callback_data="prompt:no"),
                InlineKeyboardButton(text="Cancel", callback_data="prompt:cancel"),
            ],
        ]
    )


def bash_approval_keyboard(pattern: str | None = None) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text="Yes", callback_data="prompt:yes"),
        ],
    ]
    if pattern:
        rows[0].append(
            InlineKeyboardButton(
                text=f"Yes, don't ask for: {pattern[:30]}",
                callback_data="prompt:always",
            )
        )
    rows.append(
        [
            InlineKeyboardButton(text="No", callback_data="prompt:no"),
            InlineKeyboardButton(text="Cancel", callback_data="prompt:cancel"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def single_choice_keyboard(options: list[str]) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text=opt, callback_data=f"choice:{i}")]
        for i, opt in enumerate(options)
    ]
    buttons.append(
        [InlineKeyboardButton(text="Custom input...", callback_data="choice:custom")]
    )
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def multi_choice_keyboard(
    options: list[str], selected: list[bool]
) -> InlineKeyboardMarkup:
    buttons = []
    for i, (opt, sel) in enumerate(zip(options, selected)):
        prefix = "x " if sel else "  "
        buttons.append(
            [InlineKeyboardButton(text=f"{prefix}{opt}", callback_data=f"multi:{i}")]
        )
    buttons.append(
        [
            InlineKeyboardButton(text="Custom input...", callback_data="multi:custom"),
            InlineKeyboardButton(text="Submit", callback_data="multi:submit"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def plan_mode_keyboard(options: list[str]) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text=opt, callback_data=f"plan:{i}")]
        for i, opt in enumerate(options)
    ]
    buttons.append(
        [InlineKeyboardButton(text="Cancel", callback_data="plan:cancel")]
    )
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def checkpoint_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Restore code", callback_data="cp:code")],
            [InlineKeyboardButton(text="Restore conversation", callback_data="cp:conv")],
            [InlineKeyboardButton(text="Restore both", callback_data="cp:both")],
            [InlineKeyboardButton(text="Cancel", callback_data="cp:cancel")],
        ]
    )


def yes_no_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Yes", callback_data="yn:yes"),
                InlineKeyboardButton(text="No", callback_data="yn:no"),
            ]
        ]
    )


# --- Action bar ---


def action_bar_keyboard(claude_active: bool = False) -> InlineKeyboardMarkup:
    buttons = []
    if claude_active:
        buttons.append(InlineKeyboardButton(text="Stop", callback_data="action:stop"))
    buttons.extend(
        [
            InlineKeyboardButton(text="Escape", callback_data="action:escape"),
            InlineKeyboardButton(text="Ctrl+C", callback_data="action:ctrl_c"),
            InlineKeyboardButton(text="Screenshot", callback_data="action:screenshot"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=[buttons])


# --- Screenshot button (appended to truncated output) ---


def screenshot_button() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Screenshot", callback_data="action:screenshot")]
        ]
    )


# --- Directory browser ---

_DIRS_PER_PAGE = 6


def directory_browser_keyboard(
    dirs: list[Path],
    current_path: Path,
    page: int = 0,
) -> InlineKeyboardMarkup:
    start = page * _DIRS_PER_PAGE
    end = start + _DIRS_PER_PAGE
    page_dirs = dirs[start:end]

    buttons = [
        [InlineKeyboardButton(text=d.name, callback_data=f"dir:{d}")]
        for d in page_dirs
    ]

    nav_row = []
    if current_path.parent != current_path:
        nav_row.append(
            InlineKeyboardButton(text="Up", callback_data=f"dir_up:{current_path.parent}")
        )
    if start > 0:
        nav_row.append(
            InlineKeyboardButton(text="<< Prev", callback_data=f"dir_page:{page - 1}")
        )
    if end < len(dirs):
        nav_row.append(
            InlineKeyboardButton(text="Next >>", callback_data=f"dir_page:{page + 1}")
        )
    if nav_row:
        buttons.append(nav_row)

    buttons.append(
        [InlineKeyboardButton(text="Select this directory", callback_data=f"dir_select:{current_path}")]
    )

    return InlineKeyboardMarkup(inline_keyboard=buttons)


# --- Switch pane button ---


def switch_pane_button(pane_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Switch to this pane", callback_data=f"pane:{pane_id}")]
        ]
    )


# --- History pagination ---

_HISTORY_PAGE_SIZE = 5


def history_keyboard(page: int, has_older: bool) -> InlineKeyboardMarkup:
    nav_row = []
    if page > 0:
        nav_row.append(
            InlineKeyboardButton(text="<< Newer", callback_data=f"history:{page - 1}")
        )
    if has_older:
        nav_row.append(
            InlineKeyboardButton(text="Older >>", callback_data=f"history:{page + 1}")
        )
    buttons = [nav_row] if nav_row else []
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# --- Claude commands menu ---


def claude_commands_keyboard() -> InlineKeyboardMarkup:
    commands = [
        ["/compact", "/clear", "/cost"],
        ["/model", "/memory", "/rewind"],
        ["/settings", "/help", "/doctor"],
    ]
    buttons = [
        [
            InlineKeyboardButton(text=cmd, callback_data=f"claude_cmd:{cmd}")
            for cmd in row
        ]
        for row in commands
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)
