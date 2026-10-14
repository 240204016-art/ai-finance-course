"""Команды администратора: /stats, /complaints, /ban, /unban."""
from __future__ import annotations

import logging
from html import escape

from aiogram import Bot, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from config import Settings
from db.repo import Repo
from handlers.middlewares import IsAdmin
from services import analytics, notify
from texts import t

log = logging.getLogger(__name__)
router = Router(name="admin")
router.message.filter(IsAdmin())


def _fmt_pct(value: float | None) -> str:
    return "—" if value is None else f"{value:.1f}%"


@router.message(Command("stats"))
async def cmd_stats(message: Message, repo: Repo) -> None:
    users_by_event = await repo.distinct_users_by_event()
    refs_by_event = await repo.distinct_refs_by_event()
    funnel = analytics.compute_funnel(users_by_event)
    lines = [t("funnel_line", label=t(f"funnel_{step.key}"), count=step.count,
               pct_prev=_fmt_pct(step.pct_prev), pct_first=_fmt_pct(step.pct_first))
             for step in funnel]
    await message.answer(t(
        "stats",
        users=await repo.count("users"),
        trips=await repo.count("trips"),
        groups_formed=refs_by_event.get(analytics.EV_GROUP_FORMED, 0),
        groups_completed=refs_by_event.get(analytics.EV_TRIP_COMPLETED, 0),
        payments_confirmed=await repo.count_events(analytics.EV_PAYMENT_CONFIRMED),
        funnel="\n".join(lines),
    ))


@router.message(Command("complaints"))
async def cmd_complaints(message: Message, repo: Repo) -> None:
    rows = await repo.list_complaints()
    if not rows:
        await message.answer(t("complaints_empty"))
        return
    deleted = t("deleted_user")
    items = [t("complaint_line", id=r["id"], group_id=r["group_id"], created=r["created_at"][:16],
               from_name=escape(r["from_name"] or deleted), from_id=r["from_user"] or "—",
               to_name=escape(r["to_name"] or deleted), to_id=r["to_user"] or "—",
               text=escape(r["complaint_text"]))
             for r in rows]
    await message.answer(t("complaints_title") + "\n\n" + "\n\n".join(items))


async def _target(message: Message, command: CommandObject, repo: Repo):
    arg = (command.args or "").strip()
    if not arg.isdigit():
        await message.answer(t("ban_usage", cmd=command.command))
        return None
    user = await repo.get_user(int(arg))
    if user is None:
        await message.answer(t("user_not_found"))
    return user


@router.message(Command("ban"))
async def cmd_ban(message: Message, command: CommandObject, repo: Repo, settings: Settings,
                  bot: Bot) -> None:
    user = await _target(message, command, repo)
    if user is None:
        return
    await repo.update_user(user["id"], is_banned=1)
    for trip in await repo.active_trips_of_user(user["id"]):
        await notify.leave_and_notify(bot, repo, settings, trip["id"], user["name"],
                                      penalize_late=False)
    log.info("admin banned user_id=%s", user["id"])
    await notify.safe_send(bot, user["telegram_id"], t("you_are_banned"))
    await message.answer(t("user_banned", user_id=user["id"]))


@router.message(Command("unban"))
async def cmd_unban(message: Message, command: CommandObject, repo: Repo, bot: Bot) -> None:
    user = await _target(message, command, repo)
    if user is None:
        return
    await repo.update_user(user["id"], is_banned=0)
    log.info("admin unbanned user_id=%s", user["id"])
    await notify.safe_send(bot, user["telegram_id"], t("you_are_unbanned"))
    await message.answer(t("user_unbanned", user_id=user["id"]))
