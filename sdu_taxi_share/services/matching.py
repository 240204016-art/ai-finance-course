"""Подбор попутчиков.

Чистые функции (TripRequest, GroupInfo, is_compatible, pick_best_group) не зависят
от БД и покрыты unit-тестами. Асинхронные функции ниже применяют их к данным из БД.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime

from config import GROUP_MAX_SIZE, GROUP_MIN_SIZE, LATE_CANCEL_MIN, MATCH_WINDOW_MIN
from db.repo import Repo
from services import analytics
from services.timeutil import minutes_until, to_minutes

log = logging.getLogger(__name__)

# Подбор и выход из группы меняют общие данные — выполняем их последовательно
_lock = asyncio.Lock()


# --- Чистая логика ------------------------------------------------------------

@dataclass(frozen=True)
class TripRequest:
    user_id: int
    direction: str
    district: str
    date: str
    time: str
    women_only: bool = False
    gender: str | None = None
    window_min: int = MATCH_WINDOW_MIN


@dataclass(frozen=True)
class GroupInfo:
    id: int
    direction: str
    district: str
    date: str
    time: str
    women_only: bool = False
    window_min: int = MATCH_WINDOW_MIN
    status: str = "open"
    member_ids: tuple[int, ...] = field(default_factory=tuple)
    member_genders: tuple[str | None, ...] = field(default_factory=tuple)

    @property
    def size(self) -> int:
        return len(self.member_ids)


def time_diff_minutes(a: str, b: str) -> int:
    return abs(to_minutes(a) - to_minutes(b))


def is_compatible(req: TripRequest, group: GroupInfo, max_size: int = GROUP_MAX_SIZE) -> bool:
    if group.status not in ("open", "formed"):
        return False
    if (req.direction, req.district, req.date) != (group.direction, group.district, group.date):
        return False
    if group.size >= max_size or req.user_id in group.member_ids:
        return False
    window = max(req.window_min, group.window_min)
    if time_diff_minutes(req.time, group.time) > window:
        return False
    # Группа «только девушки» принимает только девушек
    if group.women_only and req.gender != "f":
        return False
    # Девушка с флажком «только девушки» идёт только в группу, где одни девушки
    if req.women_only and any(g != "f" for g in group.member_genders):
        return False
    return True


def pick_best_group(req: TripRequest, groups: list[GroupInfo]) -> GroupInfo | None:
    """Ближайшая по времени подходящая группа; при равенстве — более полная, затем более старая."""
    suitable = [g for g in groups if is_compatible(req, g)]
    if not suitable:
        return None
    return min(suitable, key=lambda g: (time_diff_minutes(req.time, g.time), -g.size, g.id))


# --- Работа с БД --------------------------------------------------------------

@dataclass
class MatchResult:
    trip_id: int
    group_id: int
    joined_existing: bool
    formed_now: bool  # группа только что достигла минимального размера
    size: int


@dataclass
class LeaveResult:
    group_id: int | None
    late: bool
    remaining: list = field(default_factory=list)  # строки group_members
    new_organizer_id: int | None = None
    became_alone: bool = False


async def _load_groups(repo: Repo, direction: str, district: str, date: str,
                       exclude_group_id: int | None = None) -> list[GroupInfo]:
    groups = []
    for row in await repo.candidate_groups(direction, district, date):
        if row["id"] == exclude_group_id:
            continue
        members = await repo.group_members(row["id"])
        groups.append(GroupInfo(
            id=row["id"], direction=row["direction"], district=row["district"],
            date=row["date"], time=row["time"], women_only=bool(row["women_only"]),
            window_min=row["window_min"], status=row["status"],
            member_ids=tuple(m["user_id"] for m in members),
            member_genders=tuple(m["gender"] for m in members),
        ))
    return groups


async def _join(repo: Repo, trip_id: int, req: TripRequest, group: GroupInfo) -> MatchResult:
    new_size = group.size + 1
    formed_now = group.size < GROUP_MIN_SIZE <= new_size
    await repo.update_trip(trip_id, group_id=group.id, status="matched")
    updates = {"window_min": max(group.window_min, req.window_min)}
    if req.women_only:
        updates["women_only"] = 1
    if new_size >= GROUP_MIN_SIZE:
        updates["status"] = "formed"
        await repo.set_group_trips_status(group.id, "matched")
    await repo.update_group(group.id, **updates)

    # Событие «группа собрана» — для каждого участника, оказавшегося в собранной группе
    if formed_now:
        for user_id in (*group.member_ids, req.user_id):
            await analytics.log_event(repo, analytics.EV_GROUP_FORMED, user_id, group.id)
    elif new_size >= GROUP_MIN_SIZE:
        await analytics.log_event(repo, analytics.EV_GROUP_FORMED, req.user_id, group.id)
    log.info("trip=%s joined group=%s size=%s", trip_id, group.id, new_size)
    return MatchResult(trip_id, group.id, True, formed_now, new_size)


async def create_and_match(repo: Repo, req: TripRequest) -> MatchResult:
    async with _lock:
        trip_id = await repo.create_trip(req.user_id, req.direction, req.district, req.date,
                                         req.time, req.women_only, req.window_min)
        await analytics.log_event(repo, analytics.EV_TRIP_CREATED, req.user_id, trip_id)
        best = pick_best_group(req, await _load_groups(repo, req.direction, req.district, req.date))
        if best is not None:
            return await _join(repo, trip_id, req, best)

        group_id = await repo.create_group(req.direction, req.district, req.date, req.time,
                                           req.women_only, req.window_min, req.user_id)
        await repo.update_trip(trip_id, group_id=group_id, status="waiting")
        log.info("trip=%s created group=%s", trip_id, group_id)
        return MatchResult(trip_id, group_id, False, False, 1)


async def extend_window(repo: Repo, trip_id: int, window_min: int,
                        gender: str | None) -> MatchResult | None:
    """Расширяет окно одиночной поездки и пробует найти группу заново."""
    async with _lock:
        trip = await repo.get_trip(trip_id)
        if trip is None or trip["status"] != "waiting":
            return None
        await repo.update_trip(trip_id, window_min=window_min)
        if trip["group_id"]:
            await repo.update_group(trip["group_id"], window_min=window_min)
        req = TripRequest(
            user_id=trip["user_id"], direction=trip["direction"], district=trip["district"],
            date=trip["date"], time=trip["time"], women_only=bool(trip["women_only"]),
            gender=gender, window_min=window_min,
        )
        groups = await _load_groups(repo, req.direction, req.district, req.date,
                                    exclude_group_id=trip["group_id"])
        best = pick_best_group(req, groups)
        if best is None:
            return None
        if trip["group_id"]:
            await repo.update_group(trip["group_id"], status="cancelled")
        return await _join(repo, trip_id, req, best)


async def leave_trip(repo: Repo, trip_id: int, now: datetime | None = None,
                     status: str = "cancelled") -> LeaveResult | None:
    """Выход участника из поездки/группы с пересчётом состояния группы."""
    async with _lock:
        trip = await repo.get_trip(trip_id)
        if trip is None or trip["status"] not in ("waiting", "matched"):
            return None
        await repo.update_trip(trip_id, status=status)
        group_id = trip["group_id"]
        if group_id is None:
            return LeaveResult(None, False)

        group = await repo.get_group(group_id)
        remaining = await repo.group_members(group_id)
        dep_time = group["time"] if trip["status"] == "matched" else trip["time"]
        late = bool(remaining) and minutes_until(trip["date"], dep_time, now) < LATE_CANCEL_MIN
        result = LeaveResult(group_id, late, remaining)

        if not remaining:
            await repo.update_group(group_id, status="cancelled")
        else:
            if group["organizer_id"] == trip["user_id"]:
                # Новый организатор — следующий по порядку; время группы — его время
                result.new_organizer_id = remaining[0]["user_id"]
                await repo.update_group(group_id, organizer_id=result.new_organizer_id,
                                        time=remaining[0]["trip_time"])
            if len(remaining) < GROUP_MIN_SIZE:
                result.became_alone = True
                await repo.update_group(group_id, status="open")
                await repo.update_trip(remaining[0]["trip_id"], status="waiting", reminded_30=0)
        log.info("trip=%s left group=%s late=%s remaining=%s", trip_id, group_id, late, len(remaining))
        return result
