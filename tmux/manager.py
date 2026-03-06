from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

import libtmux

if TYPE_CHECKING:
    pass


@dataclass(frozen=True)
class PaneInfo:
    pane_id: str
    pane_index: int
    width: int
    height: int
    current_command: str


@dataclass(frozen=True)
class WindowInfo:
    window_id: str
    window_index: int
    window_name: str
    panes: list[PaneInfo]


@dataclass(frozen=True)
class SessionInfo:
    session_id: str
    session_name: str
    session_index: int
    windows: list[WindowInfo]


final_class = True  # marker — all classes in this module are final


class TmuxManager:
    _CLAUDE_ENTER_DELAY: float = 0.5

    def __init__(self) -> None:
        self._server: libtmux.Server | None = None

    @property
    def server(self) -> libtmux.Server:
        if self._server is None:
            self._server = libtmux.Server()
        return self._server

    def is_available(self) -> bool:
        try:
            self.server.sessions
            return True
        except Exception:
            return False

    def _reconnect(self) -> None:
        self._server = libtmux.Server()

    def list_sessions(self) -> list[SessionInfo]:
        sessions: list[SessionInfo] = []
        for idx, sess in enumerate(self.server.sessions):
            windows: list[WindowInfo] = []
            for win in sess.windows:
                panes: list[PaneInfo] = []
                for pane in win.panes:
                    panes.append(
                        PaneInfo(
                            pane_id=pane.pane_id,
                            pane_index=int(pane.pane_index),
                            width=int(pane.pane_width),
                            height=int(pane.pane_height),
                            current_command=pane.pane_current_command or "",
                        )
                    )
                windows.append(
                    WindowInfo(
                        window_id=win.window_id,
                        window_index=int(win.window_index),
                        window_name=win.window_name,
                        panes=panes,
                    )
                )
            sessions.append(
                SessionInfo(
                    session_id=sess.session_id,
                    session_name=sess.session_name,
                    session_index=idx,
                    windows=windows,
                )
            )
        return sessions

    def get_session(self, name: str) -> libtmux.Session | None:
        try:
            return self.server.sessions.get(session_name=name)
        except Exception:
            return None

    def create_session(self, name: str, start_directory: str | None = None) -> libtmux.Session:
        kwargs: dict = {"session_name": name, "attach": False}
        if start_directory:
            kwargs["start_directory"] = start_directory
        return self.server.new_session(**kwargs)

    def kill_session(self, name: str) -> bool:
        session = self.get_session(name)
        if session is None:
            return False
        session.kill()
        return True

    def create_window(self, session_name: str, window_name: str) -> libtmux.Window | None:
        session = self.get_session(session_name)
        if session is None:
            return None
        return session.new_window(window_name=window_name)

    def kill_window(self, window_id: str) -> bool:
        try:
            window = self.server.windows.get(window_id=window_id)
            if window:
                window.kill()
                return True
        except Exception:
            pass
        return False

    def split_pane(self, pane_id: str, vertical: bool = True) -> libtmux.Pane | None:
        pane = self._get_pane(pane_id)
        if pane is None:
            return None
        return pane.split(direction=libtmux.constants.PaneDirection.Right if vertical else libtmux.constants.PaneDirection.Below)

    def kill_pane(self, pane_id: str) -> bool:
        pane = self._get_pane(pane_id)
        if pane is None:
            return False
        pane.kill()
        return True

    def capture_pane(self, pane_id: str, *, ansi: bool = False) -> str | None:
        pane = self._get_pane(pane_id)
        if pane is None:
            return None
        lines = pane.capture_pane(p=not ansi, e=ansi)
        if isinstance(lines, list):
            return "\n".join(lines)
        return lines

    def capture_pane_ansi(self, pane_id: str) -> str | None:
        return self.capture_pane(pane_id, ansi=True)

    def send_keys(self, pane_id: str, keys: str, *, enter: bool = True) -> bool:
        pane = self._get_pane(pane_id)
        if pane is None:
            return False
        pane.send_keys(keys, enter=enter)
        return True

    async def send_keys_claude(self, pane_id: str, text: str) -> bool:
        pane = self._get_pane(pane_id)
        if pane is None:
            return False
        pane.send_keys(text, enter=False)
        await asyncio.sleep(self._CLAUDE_ENTER_DELAY)
        pane.send_keys("", enter=True)
        await asyncio.sleep(0.1)
        pane.send_keys("", enter=True)
        return True

    def send_special_key(self, pane_id: str, key: str) -> bool:
        pane = self._get_pane(pane_id)
        if pane is None:
            return False
        pane.send_keys(key, enter=False)
        return True

    def _get_pane(self, pane_id: str) -> libtmux.Pane | None:
        try:
            return self.server.panes.get(pane_id=pane_id)
        except Exception:
            return None
