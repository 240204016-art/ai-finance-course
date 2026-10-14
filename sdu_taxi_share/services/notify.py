"""Отправка уведомлений и сценарии, общие для хендлеров и планировщика."""
from __future__ import annotations

import logging
from html import escape

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

from config import DISTRICTS, GROUP_MAX_SIZE, LATE_CANCEL_PENALTY_SCORE, Settings
from db.repo import Repo
from keyboards import inline
from services import matching, ratings
from services.timeutil import short_date
from texts import t

log = logging.getLogger(__name__)


def direction_label(code: str) -> str:
    return t(f"dir_{code}")


def district_label(code: str) -> str:
    return DISTRICTS.get(code, code)


async def safe_send(bot: Bot, chat_id: int, text: str, **kwargs) -> bool:
    try:
        await bot.send_message(chat_id, text, **kwargs)
        return True
    except TelegramAPIError as exc:
        # Пользователь мог заблокировать бота — это не ошибка приложения
        log.warning("send failed chat=%s err=%s", chat_id, type(exc).__name__)
        return False


async def notify_admins(bot: Bot, settings: Settings, text: str) -> None:
    for admin_id in settings.admin_ids:
        await safe_send(bot, admin_id, text)


def member_line(member, organizer_id: int | None) -> str:
    username = ""
    if member["username"]:
        username = f" @{member['username']}" if member["show_username"] else t("username_hidden")
    mark = t("organizer_mark") if member["user_id"] == organizer_id else ""
    return t("member_line", name=escape(member["name"]), username=username, organizer_mark=mark)


async def group_text(repo: Repo, group_id: int, title_key: str) -> tuple[str, list]:
    group = await repo.get_group(group_id)
    members = await repo.group_members(group_id)
    organizer = next((m for m in members if m["user_id"] == group["organizer_id"]), None)
    text = t(
        "group_info",
        title=t(title_key),
        direction=direction_label(group["direction"]),
        district=district_label(group["district"]),
        date=short_date(group["date"]),
        time=group["time"],
        count=len(members),
        max=GROUP_MAX_SIZE,
        members="\n".join(member_line(m, group["organizer_id"]) for m in members),
        organizer=escape(organizer["name"]) if organizer else "—",
    )
    return text, members


async def notify_group(bot: Bot, repo: Repo, group_id: int, formed_now: bool) -> None:
    """«Группа собрана» (или обновлённый состав) — всем участникам."""
    text, members = await group_text(
        repo, group_id, "group_formed_title" if formed_now else "group_updated_title")
    for member in members:
        await safe_send(bot, member["telegram_id"], text)


async def penalize(bot: Bot, repo: Repo, settings: Settings, user_id: int) -> None:
    alert_user = await ratings.apply_score(repo, user_id, LATE_CANCEL_PENALTY_SCORE)
    if alert_user is not None:
        await alert_low_rating(bot, settings, alert_user)


async def alert_low_rating(bot: Bot, settings: Settings, user) -> None:
    await notify_admins(bot, settings, t(
        "admin_low_rating", name=escape(user["name"]), user_id=user["id"],
        rating=ratings.average(user["rating_sum"], user["rating_count"]),
        count=user["rating_count"]))


async def leave_and_notify(bot: Bot, repo: Repo, settings: Settings, trip_id: int,
                           leaver_name: str, penalize_late: bool = True):
    """Выход из поездки: пересчёт группы, уведомления, штраф за позднюю отмену."""
    trip = await repo.get_trip(trip_id)
    result = await matching.leave_trip(repo, trip_id)
    if result is None:
        return None
    for member in result.remaining:
        await safe_send(bot, member["telegram_id"], t(
            "member_left", name=escape(leaver_name), date=short_date(trip["date"]), time=trip["time"]))
        if member["user_id"] == result.new_organizer_id and not result.became_alone:
            await safe_send(bot, member["telegram_id"], t("new_organizer"))
    if result.became_alone and result.remaining:
        await safe_send(bot, result.remaining[0]["telegram_id"], t("member_left_alone"))
    if result.late and penalize_late:
        await penalize(bot, repo, settings, trip["user_id"])
    return result


async def send_rating_prompts(bot: Bot, repo: Repo, group_id: int) -> None:
    group = await repo.get_group(group_id)
    members = await repo.completed_group_members(group_id)
    for rater in members:
        for target in members:
            if rater["user_id"] == target["user_id"]:
                continue
            await safe_send(bot, rater["telegram_id"], t(
                "rate_prompt", name=escape(target["name"]),
                date=short_date(group["date"]), time=group["time"]),
                reply_markup=inline.rate(group_id, target["user_id"]))
