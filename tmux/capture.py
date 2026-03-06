from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from parser.ansi import strip_ansi
from tmux.manager import TmuxManager


@dataclass
class _PaneCaptureState:
    content_hash: str = ""
    last_content: str = ""


class PaneCapture:
    def __init__(self, tmux: TmuxManager) -> None:
        self._tmux = tmux
        self._states: dict[str, _PaneCaptureState] = {}

    def _get_state(self, pane_id: str) -> _PaneCaptureState:
        if pane_id not in self._states:
            self._states[pane_id] = _PaneCaptureState()
        return self._states[pane_id]

    @staticmethod
    def _hash_content(content: str) -> str:
        return hashlib.md5(content.encode()).hexdigest()

    def capture(self, pane_id: str) -> str | None:
        return self._tmux.capture_pane(pane_id)

    def capture_if_changed(self, pane_id: str) -> str | None:
        raw = self._tmux.capture_pane(pane_id)
        if raw is None:
            return None
        clean = strip_ansi(raw)
        content_hash = self._hash_content(clean)
        state = self._get_state(pane_id)
        if content_hash == state.content_hash:
            return None
        state.content_hash = content_hash
        state.last_content = clean
        return clean

    def get_last_content(self, pane_id: str) -> str:
        return self._get_state(pane_id).last_content

    def remove_pane(self, pane_id: str) -> None:
        self._states.pop(pane_id, None)
