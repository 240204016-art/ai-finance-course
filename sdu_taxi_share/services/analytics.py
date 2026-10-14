"""События эксперимента и воронка конверсии."""
from __future__ import annotations

import logging
from dataclasses import dataclass

from db.repo import Repo

log = logging.getLogger(__name__)

EV_REGISTERED = "registered"
EV_TRIP_CREATED = "trip_created"
EV_GROUP_FORMED = "group_formed"
EV_TRIP_COMPLETED = "trip_completed"
EV_PAYMENT_CONFIRMED = "payment_confirmed"

FUNNEL_STEPS = (EV_REGISTERED, EV_TRIP_CREATED, EV_GROUP_FORMED, EV_TRIP_COMPLETED)


async def log_event(repo: Repo, event_type: str, user_id: int | None = None,
                    ref_id: int | None = None) -> None:
    await repo.add_event(event_type, user_id, ref_id)
    # В лог пишем только внутренние идентификаторы, без персональных данных
    log.info("event=%s user_id=%s ref_id=%s", event_type, user_id, ref_id)


@dataclass(frozen=True)
class FunnelStep:
    key: str
    count: int
    pct_prev: float | None  # доля от предыдущего шага, %
    pct_first: float | None  # доля от первого шага, %


def _pct(part: int, whole: int) -> float | None:
    return round(part * 100 / whole, 1) if whole else None


def compute_funnel(counts: dict[str, int], steps: tuple[str, ...] = FUNNEL_STEPS) -> list[FunnelStep]:
    result: list[FunnelStep] = []
    first = counts.get(steps[0], 0)
    prev = None
    for key in steps:
        n = counts.get(key, 0)
        result.append(FunnelStep(
            key=key,
            count=n,
            pct_prev=None if prev is None else _pct(n, prev),
            pct_first=_pct(n, first),
        ))
        prev = n
    return result
