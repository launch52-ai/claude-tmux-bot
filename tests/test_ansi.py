from __future__ import annotations

from parser.ansi import strip_ansi


def test_strip_color_codes() -> None:
    text = "\x1b[31mRed text\x1b[0m"
    assert strip_ansi(text) == "Red text"


def test_strip_bold() -> None:
    text = "\x1b[1mBold\x1b[22m normal"
    assert strip_ansi(text) == "Bold normal"


def test_strip_cursor_movement() -> None:
    text = "\x1b[2Ahello\x1b[3B"
    assert strip_ansi(text) == "hello"


def test_strip_osc_sequence() -> None:
    text = "\x1b]0;title\x07rest"
    assert strip_ansi(text) == "rest"


def test_preserve_newlines_and_tabs() -> None:
    text = "line1\n\tline2\n"
    assert strip_ansi(text) == "line1\n\tline2\n"


def test_strip_control_chars() -> None:
    text = "hello\x08\x7fworld"
    assert strip_ansi(text) == "helloworld"


def test_plain_text_unchanged() -> None:
    text = "Just plain text with no escapes"
    assert strip_ansi(text) == text


def test_complex_sequence() -> None:
    text = "\x1b[38;5;196mcolored\x1b[0m \x1b[1;4;32mbold underline green\x1b[0m"
    assert strip_ansi(text) == "colored bold underline green"
