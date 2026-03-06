from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Update


class AuthMiddleware(BaseMiddleware):
    def __init__(self, allowed_user_id: int) -> None:
        super().__init__()
        self._allowed_user_id = allowed_user_id

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if isinstance(event, Update):
            user = _extract_user_id(event)
            if user is not None and user != self._allowed_user_id:
                return None  # Silently ignore
        return await handler(event, data)


def _extract_user_id(update: Update) -> int | None:
    if update.message and update.message.from_user:
        return update.message.from_user.id
    if update.callback_query and update.callback_query.from_user:
        return update.callback_query.from_user.id
    return None
