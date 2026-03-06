from __future__ import annotations

import re

_ANSI_ESCAPE_RE = re.compile(
    r"""
    \x1b        # ESC character
    (?:
        \[      # CSI sequences
        [0-9;]*
        [A-Za-z]
    |
        \]      # OSC sequences
        .*?
        (?:\x07|\x1b\\)  # terminated by BEL or ST
    |
        [()][AB012]  # character set selection
    |
        [>=<]   # private mode set/reset
    |
        \x1b    # ESC ESC (double escape)
    )
    """,
    re.VERBOSE,
)

# Also strip carriage returns and other control chars (except newline/tab)
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def strip_ansi(text: str) -> str:
    text = _ANSI_ESCAPE_RE.sub("", text)
    text = _CONTROL_CHAR_RE.sub("", text)
    return text
