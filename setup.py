"""Auto-detect Telegram chat ID and user ID by listening for a message."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path


async def _detect(bot_token: str, timeout: int = 60) -> dict[str, int] | None:
    """Poll Telegram for a message in a supergroup. Returns {chat_id, user_id} or None."""
    # Import here so install.sh can check syntax before deps are ready
    from aiogram import Bot, Dispatcher
    from aiogram.types import Message

    bot = Bot(token=bot_token)
    dp = Dispatcher()
    found = asyncio.Event()
    result: dict[str, int] = {}

    @dp.message()
    async def _on_message(message: Message) -> None:
        if message.chat.type not in ("supergroup", "group"):
            await message.reply(
                "This is not a group. Please send a message in your supergroup."
            )
            return

        chat_id = message.chat.id
        user_id = message.from_user.id if message.from_user else 0
        is_forum = getattr(message.chat, "is_forum", False)

        result["chat_id"] = chat_id
        result["user_id"] = user_id

        status = "yes" if is_forum else "NO — please enable Topics in group settings first"
        await message.reply(
            f"Detected!\n\n"
            f"Chat ID: {chat_id}\n"
            f"Your User ID: {user_id}\n"
            f"Forum topics: {status}"
        )
        found.set()

    async def _poll() -> None:
        await dp.start_polling(bot)

    task = asyncio.create_task(_poll())

    try:
        await asyncio.wait_for(found.wait(), timeout=timeout)
    except asyncio.TimeoutError:
        pass

    task.cancel()
    try:
        await asyncio.gather(task, return_exceptions=True)
    except Exception:
        pass
    await bot.session.close()

    return result if result else None


def run_setup(bot_token: str, env_path: str, timeout: int = 60) -> bool:
    """Run detection and write results to .env. Returns True on success."""
    result = asyncio.run(_detect(bot_token, timeout))

    if not result:
        return False

    chat_id = result["chat_id"]
    user_id = result["user_id"]

    # Update .env file
    path = Path(env_path)
    if path.exists():
        content = path.read_text()
        lines = content.splitlines()
        new_lines = []
        set_chat = False
        set_user = False
        for line in lines:
            stripped = line.split("#")[0].strip()
            if stripped.startswith("CTB_CHAT_ID=") or stripped == "CTB_CHAT_ID":
                new_lines.append(f"CTB_CHAT_ID={chat_id}")
                set_chat = True
            elif stripped.startswith("CTB_ALLOWED_USER_ID=") or stripped == "CTB_ALLOWED_USER_ID":
                old_val = stripped.split("=", 1)[1] if "=" in stripped else ""
                # Only overwrite if it's a placeholder or empty
                if not old_val or old_val == "123456789":
                    new_lines.append(f"CTB_ALLOWED_USER_ID={user_id}")
                    set_user = True
                else:
                    new_lines.append(line)
            else:
                new_lines.append(line)
        if not set_chat:
            new_lines.append(f"CTB_CHAT_ID={chat_id}")
        if not set_user:
            new_lines.append(f"CTB_ALLOWED_USER_ID={user_id}")
        path.write_text("\n".join(new_lines) + "\n")
    else:
        path.write_text(
            f"CTB_CHAT_ID={chat_id}\n"
            f"CTB_ALLOWED_USER_ID={user_id}\n"
        )

    # Output as JSON for the shell script to parse
    print(json.dumps({"chat_id": chat_id, "user_id": user_id}))
    return True


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python3 setup.py <bot_token> <env_path> [timeout]", file=sys.stderr)
        sys.exit(1)

    token = sys.argv[1]
    env = sys.argv[2]
    t = int(sys.argv[3]) if len(sys.argv) > 3 else 60

    success = run_setup(token, env, t)
    sys.exit(0 if success else 1)
