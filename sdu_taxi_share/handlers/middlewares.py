"""Загрузка пользователя из БД, проверка бана, фильтры доступа."""
from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.filters import Filter
from aiogram.types import CallbackQuery, Message, TelegramObject

from config import Settings
from db.repo import Repo
from texts import t


class UserMiddleware(BaseMiddleware):
    """Кладёт в data['user'] строку пользователя (или None) и не пускает забаненных."""

    async def __call__(self, handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
                       event: TelegramObject, data: dict[str, Any]) -> Any:
        repo: Repo = data["repo"]
        settings: Settings = data["settings"]
        tg_user = getattr(event, "from_user", None)
        user = None
        if tg_user is not None:
            user = await repo.get_user_by_tg(tg_user.id)
            if user is not None:
                if user["is_banned"] and not settings.is_admin(tg_user.id):
                    if isinstance(event, CallbackQuery):
                        await event.answer(t("banned"), show_alert=True)
                    elif isinstance(event, Message):
                        await event.answer(t("banned"))
                    return None
                if user["username"] != tg_user.username:
                    await repo.update_user(user["id"], username=tg_user.username)
                    user = await repo.get_user(user["id"])
        data["user"] = user
        return await handler(event, data)


class Registered(Filter):
    async def __call__(self, event: TelegramObject, user=None) -> bool:
        return user is not None


class IsAdmin(Filter):
    async def __call__(self, event: TelegramObject, settings: Settings) -> bool:
        tg_user = getattr(event, "from_user", None)
        return tg_user is not None and settings.is_admin(tg_user.id)
