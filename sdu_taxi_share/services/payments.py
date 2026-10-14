"""Деление стоимости поездки и учёт долгов."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from config import PAYMENT_DEADLINE_HOURS
from db.repo import Repo
from services import analytics

log = logging.getLogger(__name__)


def split_amount(total: int, n: int) -> list[int]:
    """Делит сумму в целых тенге поровну на n человек.

    Остаток от деления распределяется по 1 ₸ начиная с первых участников
    (первым всегда идёт организатор), поэтому сумма долей всегда равна total.
    """
    if n < 1:
        raise ValueError("Количество участников должно быть не меньше 1")
    if total < 0:
        raise ValueError("Сумма не может быть отрицательной")
    base, remainder = divmod(total, n)
    return [base + (1 if i < remainder else 0) for i in range(n)]


def debt_cutoff(now: datetime | None = None) -> str:
    """Момент, раньше которого созданный и неоплаченный платёж считается просроченным."""
    now = now or datetime.now(timezone.utc)
    return (now - timedelta(hours=PAYMENT_DEADLINE_HOURS)).isoformat(timespec="seconds")


async def has_blocking_debt(repo: Repo, user_id: int, now: datetime | None = None) -> bool:
    return await repo.has_overdue_debt(user_id, debt_cutoff(now))


@dataclass
class Share:
    user_id: int
    telegram_id: int
    name: str
    amount: int
    payment_id: int
    is_organizer: bool


async def complete_group(repo: Repo, group_id: int, total: int) -> list[Share] | None:
    """Отмечает поездку состоявшейся, делит сумму и создаёт записи об оплате."""
    group = await repo.get_group(group_id)
    if group is None or group["status"] != "formed":
        return None
    members = list(await repo.group_members(group_id))
    if not members:
        return None
    # Организатор — первым в списке
    members.sort(key=lambda m: (m["user_id"] != group["organizer_id"], m["trip_id"]))
    amounts = split_amount(total, len(members))

    await repo.set_group_trips_status(group_id, "completed")
    await repo.update_group(group_id, status="completed", total_price=total)
    await repo.increment_trips_count([m["user_id"] for m in members])

    shares = []
    for member, amount in zip(members, amounts):
        is_org = member["user_id"] == group["organizer_id"]
        payment_id = await repo.create_payment(group_id, member["user_id"], amount,
                                               "confirmed" if is_org else "pending")
        await analytics.log_event(repo, analytics.EV_TRIP_COMPLETED, member["user_id"], group_id)
        shares.append(Share(member["user_id"], member["telegram_id"], member["name"],
                            amount, payment_id, is_org))
    log.info("group=%s completed members=%s", group_id, len(members))
    return shares


async def cancel_group(repo: Repo, group_id: int) -> list:
    """Организатор отметил, что поездка не состоялась. Возвращает участников."""
    members = list(await repo.group_members(group_id))
    await repo.set_group_trips_status(group_id, "cancelled")
    await repo.update_group(group_id, status="cancelled")
    log.info("group=%s marked not happened", group_id)
    return members


async def confirm_payment(repo: Repo, payment_id: int) -> bool:
    payment = await repo.get_payment(payment_id)
    if payment is None or payment["status"] == "confirmed":
        return False
    await repo.set_payment_status(payment_id, "confirmed")
    await analytics.log_event(repo, analytics.EV_PAYMENT_CONFIRMED, payment["user_id"],
                              payment["group_id"])
    return True
