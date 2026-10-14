"""Периодические задачи: напоминания, запрос суммы, просроченные оплаты.

Раз в минуту проверяется состояние БД; отправленные напоминания отмечаются
флагами, поэтому перезапуск бота не приводит к повторным или потерянным сообщениям.
"""
from __future__ import annotations

import logging
from datetime import datetime

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from config import ASK_PRICE_AFTER_MIN, REMIND_ALONE_MIN, REMIND_CONFIRM_MIN, TIMEZONE, Settings
from db.repo import Repo
from keyboards import inline
from services import matching, payments
from services.notify import district_label, notify_admins, safe_send
from services.timeutil import minutes_until, now_local, short_date
from texts import t

log = logging.getLogger(__name__)

STALE_GROUP_MIN = 24 * 60  # группу без ответа организатора закрываем через сутки


async def process_trips(bot: Bot, repo: Repo, now: datetime) -> None:
    for trip in await repo.all_active_trips():
        mins = minutes_until(trip["date"], trip["dep_time"], now)
        district = district_label(trip["district"])
        if trip["status"] == "waiting":
            if mins <= 0:
                await matching.leave_trip(repo, trip["id"], now, status="expired")
                await safe_send(bot, trip["telegram_id"], t(
                    "trip_expired", date=short_date(trip["date"]), time=trip["time"]))
            elif mins <= REMIND_ALONE_MIN and not trip["reminded_30"]:
                await repo.update_trip(trip["id"], reminded_30=1)
                await safe_send(bot, trip["telegram_id"],
                                t("remind_alone", time=trip["time"], district=district),
                                reply_markup=inline.extend_window(trip["id"], trip["window_min"]))
        elif trip["status"] == "matched":
            if 0 < mins <= REMIND_CONFIRM_MIN and not trip["reminded_15"]:
                await repo.update_trip(trip["id"], reminded_15=1)
                await safe_send(bot, trip["telegram_id"],
                                t("remind_confirm", time=trip["dep_time"], district=district),
                                reply_markup=inline.going(trip["id"]))


async def process_groups(bot: Bot, repo: Repo, now: datetime) -> None:
    for group in await repo.formed_groups_waiting_price():
        if minutes_until(group["date"], group["time"], now) > -ASK_PRICE_AFTER_MIN:
            continue
        await repo.update_group(group["id"], price_asked=1)
        organizer = await repo.get_user(group["organizer_id"]) if group["organizer_id"] else None
        if organizer is not None:
            await safe_send(bot, organizer["telegram_id"], t(
                "ask_price_organizer", date=short_date(group["date"]), time=group["time"]),
                reply_markup=inline.ask_price(group["id"]))
    # Организатор не ответил за сутки — закрываем группу, чтобы она не висела в активных
    for group in await repo.stale_formed_groups():
        if minutes_until(group["date"], group["time"], now) <= -STALE_GROUP_MIN:
            await payments.cancel_group(repo, group["id"])


async def process_payments(bot: Bot, repo: Repo, settings: Settings) -> None:
    for payment in await repo.overdue_payments(payments.debt_cutoff()):
        await repo.mark_payment_overdue_notified(payment["id"])
        log.info("payment overdue id=%s", payment["id"])
        await notify_admins(bot, settings, t(
            "admin_payment_overdue", payment_id=payment["id"], group_id=payment["group_id"],
            user_id=payment["user_id"], amount=payment["amount"]))


async def tick(bot: Bot, repo: Repo, settings: Settings) -> None:
    now = now_local()
    for step in (process_trips(bot, repo, now), process_groups(bot, repo, now),
                 process_payments(bot, repo, settings)):
        try:
            await step
        except Exception:  # noqa: BLE001 — одна ошибка не должна останавливать остальные проверки
            log.exception("scheduler step failed")


def create_scheduler(bot: Bot, repo: Repo, settings: Settings) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=TIMEZONE)
    # Триггер передаём объектом, а не строкой "interval": в собранном .exe
    # APScheduler не находит триггеры по имени (они регистрируются через entry points)
    scheduler.add_job(tick, IntervalTrigger(minutes=1), kwargs=dict(bot=bot, repo=repo, settings=settings),
                      id="tick", max_instances=1, coalesce=True, next_run_time=now_local())
    return scheduler
