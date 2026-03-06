from __future__ import annotations

import io
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tmux.manager import TmuxManager

logger = logging.getLogger(__name__)


def render_pane_screenshot(tmux: "TmuxManager", pane_id: str) -> bytes | None:
    ansi_output = tmux.capture_pane_ansi(pane_id)
    if ansi_output is None:
        return None
    return render_ansi_to_png(ansi_output)


def render_ansi_to_png(ansi_text: str) -> bytes | None:
    try:
        from rich.console import Console
        from rich.text import Text

        console = Console(file=io.StringIO(), width=120, record=True)
        text = Text.from_ansi(ansi_text)
        console.print(text)

        svg_str = console.export_svg(title="Terminal")

        import cairosvg

        png_data = cairosvg.svg2png(bytestring=svg_str.encode("utf-8"))
        return png_data
    except Exception:
        logger.exception("Failed to render screenshot")
        return None
