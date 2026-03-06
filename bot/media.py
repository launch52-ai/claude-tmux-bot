from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from aiogram import Bot
from aiogram.types import Message

logger = logging.getLogger(__name__)

_MEDIA_DIR = Path.home() / ".ctb" / "media"


async def transcribe_voice(bot: Bot, message: Message, api_key: str) -> str | None:
    if not message.voice:
        return None

    _MEDIA_DIR.mkdir(parents=True, exist_ok=True)

    file = await bot.get_file(message.voice.file_id)
    if file.file_path is None:
        return None

    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
        await bot.download_file(file.file_path, tmp)
        tmp_path = Path(tmp.name)

    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key)
        with tmp_path.open("rb") as audio_file:
            transcript = client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
            )
        return transcript.text
    except Exception:
        logger.exception("Voice transcription failed")
        return None
    finally:
        tmp_path.unlink(missing_ok=True)


async def save_photo(bot: Bot, message: Message) -> Path | None:
    if not message.photo:
        return None

    _MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    photo = message.photo[-1]  # Largest size
    file = await bot.get_file(photo.file_id)
    if file.file_path is None:
        return None

    ext = Path(file.file_path).suffix or ".jpg"
    dest = _MEDIA_DIR / f"{photo.file_unique_id}{ext}"
    await bot.download_file(file.file_path, str(dest))
    logger.info("Saved photo to %s", dest)
    return dest


async def save_document(bot: Bot, message: Message) -> Path | None:
    if not message.document:
        return None

    _MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    doc = message.document
    file = await bot.get_file(doc.file_id)
    if file.file_path is None:
        return None

    # Sanitize filename — strip path components to prevent traversal
    raw_name = doc.file_name or doc.file_unique_id
    name = Path(raw_name).name
    dest = _MEDIA_DIR / name
    await bot.download_file(file.file_path, str(dest))
    logger.info("Saved document to %s", dest)
    return dest


async def send_file_to_telegram(bot: Bot, chat_id: int, topic_id: int, file_path: str) -> bool:
    path = Path(file_path).expanduser().resolve()

    # Block access to sensitive directories
    if not path.exists():
        return False
    if not _is_safe_file_path(path):
        return False
    if path.stat().st_size > 50 * 1024 * 1024:  # 50MB Telegram limit
        return False

    from aiogram.types import FSInputFile

    input_file = FSInputFile(str(path))
    await bot.send_document(
        chat_id=chat_id,
        document=input_file,
        message_thread_id=topic_id,
    )
    return True


def _is_safe_file_path(path: Path) -> bool:
    """Block access to known sensitive paths."""
    resolved = str(path.resolve())
    blocked = [
        str(Path.home() / ".ssh"),
        str(Path.home() / ".gnupg"),
        str(Path.home() / ".aws"),
        str(Path.home() / ".config" / "gcloud"),
        "/etc/shadow",
        "/etc/master.passwd",
    ]
    for prefix in blocked:
        if resolved.startswith(prefix):
            return False
    # Must be a regular file (not a device, socket, etc.)
    if not path.is_file():
        return False
    return True
