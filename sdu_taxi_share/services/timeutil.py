"""Работа со временем: всё время поездок — местное время Алматы."""
from __future__ import annotations

from datetime import date as date_cls, datetime, timedelta

from config import TIME_END_MIN, TIME_START_MIN, TIME_STEP_MIN, TIMEZONE


def now_local() -> datetime:
    return datetime.now(TIMEZONE)


def to_minutes(hhmm: str) -> int:
    hours, minutes = hhmm.split(":")
    return int(hours) * 60 + int(minutes)


def from_minutes(total: int) -> str:
    return f"{total // 60:02d}:{total % 60:02d}"


def departure_at(date_str: str, time_str: str) -> datetime:
    d = date_cls.fromisoformat(date_str)
    minutes = to_minutes(time_str)
    return datetime(d.year, d.month, d.day, minutes // 60, minutes % 60, tzinfo=TIMEZONE)


def minutes_until(date_str: str, time_str: str, now: datetime | None = None) -> float:
    now = now or now_local()
    return (departure_at(date_str, time_str) - now).total_seconds() / 60


def time_slots() -> list[str]:
    return [from_minutes(m) for m in range(TIME_START_MIN, TIME_END_MIN + 1, TIME_STEP_MIN)]


def available_slots(date_str: str, now: datetime | None = None) -> list[str]:
    """Слоты выезда, которые ещё не прошли (для «сегодня»)."""
    now = now or now_local()
    return [s for s in time_slots() if departure_at(date_str, s) > now]


def today_and_tomorrow(now: datetime | None = None) -> tuple[str, str]:
    now = now or now_local()
    today = now.date()
    return today.isoformat(), (today + timedelta(days=1)).isoformat()


def short_date(date_str: str) -> str:
    d = date_cls.fromisoformat(date_str)
    return f"{d.day:02d}.{d.month:02d}"
