from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

_LABEL = "com.ctb"
_PLIST_TEMPLATE = Path(__file__).parent / "com.ctb.plist"
_LAUNCH_AGENTS_DIR = Path.home() / "Library" / "LaunchAgents"
_INSTALLED_PLIST = _LAUNCH_AGENTS_DIR / f"{_LABEL}.plist"
_LOGS_DIR = Path.home() / ".ctb" / "logs"


def install() -> str:
    if not _PLIST_TEMPLATE.exists():
        return "Error: com.ctb.plist template not found."

    _LAUNCH_AGENTS_DIR.mkdir(parents=True, exist_ok=True)
    _LOGS_DIR.mkdir(parents=True, exist_ok=True)

    content = _PLIST_TEMPLATE.read_text()
    content = content.replace("__CTB_MAIN_PY__", str(Path(__file__).parent / "main.py"))
    content = content.replace("__CTB_WORKING_DIR__", str(Path(__file__).parent))
    content = content.replace("__CTB_HOME__", str(Path.home()))

    _INSTALLED_PLIST.write_text(content)

    result = subprocess.run(
        ["launchctl", "load", str(_INSTALLED_PLIST)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return f"Error loading service: {result.stderr.strip()}"

    logger.info("Service installed and loaded")
    return "Service installed and loaded. It will auto-start on login."


def uninstall() -> str:
    if not _INSTALLED_PLIST.exists():
        return "Service is not installed."

    result = subprocess.run(
        ["launchctl", "unload", str(_INSTALLED_PLIST)],
        capture_output=True,
        text=True,
    )
    _INSTALLED_PLIST.unlink(missing_ok=True)

    if result.returncode != 0:
        return f"Warning: {result.stderr.strip()} (plist removed anyway)"

    logger.info("Service uninstalled")
    return "Service uninstalled."


def status() -> str:
    if not _INSTALLED_PLIST.exists():
        return "Service is not installed."

    result = subprocess.run(
        ["launchctl", "list", _LABEL],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        # Parse PID from output
        lines = result.stdout.strip().splitlines()
        for line in lines:
            if "PID" in line:
                return f"Service is running.\n{line}"
        return f"Service is loaded.\n{result.stdout.strip()}"
    return "Service is installed but not running."
