from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

_LABEL = "com.claude-tmux-bot"
_SRC_DIR = Path(__file__).parent
_PLIST_TEMPLATE = _SRC_DIR / "com.claude-tmux-bot.plist"
_APP_DIR = Path.home() / ".ctb" / "app"
_LAUNCH_AGENTS_DIR = Path.home() / "Library" / "LaunchAgents"
_INSTALLED_PLIST = _LAUNCH_AGENTS_DIR / f"{_LABEL}.plist"
_LOGS_DIR = Path.home() / ".ctb" / "logs"

# Directories and files to copy for runtime
_COPY_DIRS = ["bot", "claude", "parser", "tmux", "watcher"]
_COPY_FILES = [
    "main.py", "config.py", "service.py", "claude-tmux-bot",
    "com.claude-tmux-bot.plist", "requirements.txt",
]


def _deploy_to_app_dir() -> None:
    """Copy runtime files to ~/.ctb/app/ so launchd can access them."""
    _APP_DIR.mkdir(parents=True, exist_ok=True)

    for dirname in _COPY_DIRS:
        src = _SRC_DIR / dirname
        dst = _APP_DIR / dirname
        if src.is_dir():
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__"))

    for filename in _COPY_FILES:
        src = _SRC_DIR / filename
        if src.exists():
            shutil.copy2(src, _APP_DIR / filename)

    # Copy .env so pydantic-settings can read it from CWD
    env_src = _SRC_DIR / ".env"
    if env_src.exists():
        shutil.copy2(env_src, _APP_DIR / ".env")

    # Ensure launcher is executable
    launcher = _APP_DIR / "claude-tmux-bot"
    if launcher.exists():
        launcher.chmod(0o755)


def install() -> str:
    if not _PLIST_TEMPLATE.exists():
        return "Error: com.claude-tmux-bot.plist template not found."

    _LAUNCH_AGENTS_DIR.mkdir(parents=True, exist_ok=True)
    _LOGS_DIR.mkdir(parents=True, exist_ok=True)

    # Deploy files to ~/.ctb/app/
    _deploy_to_app_dir()

    content = _PLIST_TEMPLATE.read_text()
    content = content.replace("__CTB_LAUNCHER__", str(_APP_DIR / "claude-tmux-bot"))
    content = content.replace("__CTB_WORKING_DIR__", str(_APP_DIR))
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
    return "Service installed and running. It will auto-start on login."


def uninstall() -> str:
    if not _INSTALLED_PLIST.exists():
        return "Service is not installed."

    result = subprocess.run(
        ["launchctl", "unload", str(_INSTALLED_PLIST)],
        capture_output=True,
        text=True,
    )
    _INSTALLED_PLIST.unlink(missing_ok=True)

    # Clean up deployed app files
    if _APP_DIR.exists():
        shutil.rmtree(_APP_DIR)

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
