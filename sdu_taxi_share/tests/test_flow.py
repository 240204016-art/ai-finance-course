"""Интеграционные тесты подбора/оплаты на SQLite в памяти."""
from datetime import datetime, timedelta

import pytest

from config import TIMEZONE
from db.database import connect
from db.repo import Repo
from services import matching, payments
from services.analytics import compute_funnel
from services.matching import TripRequest

DATE = "2026-10-15"


@pytest.fixture
async def repo():
    conn = await connect(":memory:")
    yield Repo(conn)
    await conn.close()


async def make_user(repo, n, gender="m"):
    return await repo.create_user(1000 + n, f"user{n}", f"User{n}", f"u{n}@sdu.edu.kz", gender)


def trip(user_id, time="08:00", **kw):
    return TripRequest(user_id=user_id, direction="to_sdu", district="almaly", date=DATE,
                       time=time, gender=kw.pop("gender", "m"), **kw)


async def test_group_forms_and_fills_to_four(repo):
    users = [await make_user(repo, i) for i in range(5)]
    r1 = await matching.create_and_match(repo, trip(users[0]))
    assert not r1.joined_existing and r1.size == 1
    r2 = await matching.create_and_match(repo, trip(users[1], "08:10"))
    assert r2.joined_existing and r2.formed_now and r2.group_id == r1.group_id
    r3 = await matching.create_and_match(repo, trip(users[2], "07:50"))
    r4 = await matching.create_and_match(repo, trip(users[3], "08:15"))
    assert r3.group_id == r4.group_id == r1.group_id and r4.size == 4 and not r4.formed_now
    r5 = await matching.create_and_match(repo, trip(users[4]))
    assert r5.group_id != r1.group_id and r5.size == 1
    group = await repo.get_group(r1.group_id)
    assert group["status"] == "formed" and group["organizer_id"] == users[0]


async def test_leave_reassigns_organizer_and_reopens(repo):
    a, b = await make_user(repo, 1), await make_user(repo, 2)
    r1 = await matching.create_and_match(repo, trip(a))
    r2 = await matching.create_and_match(repo, trip(b, "08:10"))
    now = datetime(2026, 10, 15, 6, 0, tzinfo=TIMEZONE)  # за 2 часа — не поздно
    res = await matching.leave_trip(repo, r1.trip_id, now)
    assert not res.late and res.became_alone and res.new_organizer_id == b
    group = await repo.get_group(r1.group_id)
    assert group["status"] == "open" and group["time"] == "08:10"
    assert (await repo.get_trip(r2.trip_id))["status"] == "waiting"


async def test_late_leave_is_detected(repo):
    a, b = await make_user(repo, 1), await make_user(repo, 2)
    await matching.create_and_match(repo, trip(a))
    r2 = await matching.create_and_match(repo, trip(b))
    now = datetime(2026, 10, 15, 7, 45, tzinfo=TIMEZONE)
    res = await matching.leave_trip(repo, r2.trip_id, now)
    assert res.late


async def test_extend_window_merges_lonely_trips(repo):
    a, b = await make_user(repo, 1), await make_user(repo, 2)
    r1 = await matching.create_and_match(repo, trip(a, "08:00"))
    r2 = await matching.create_and_match(repo, trip(b, "08:25"))
    assert r1.group_id != r2.group_id
    res = await matching.extend_window(repo, r2.trip_id, 30, "m")
    assert res is not None and res.group_id == r1.group_id and res.formed_now
    assert (await repo.get_group(r2.group_id))["status"] == "cancelled"


async def test_women_only(repo):
    m = await make_user(repo, 1, "m")
    f1, f2 = await make_user(repo, 2, "f"), await make_user(repo, 3, "f")
    r1 = await matching.create_and_match(repo, trip(f1, gender="f", women_only=True))
    rm = await matching.create_and_match(repo, trip(m))
    assert rm.group_id != r1.group_id
    rf = await matching.create_and_match(repo, trip(f2, gender="f"))
    assert rf.group_id == r1.group_id


async def test_complete_group_split_and_debt(repo):
    users = [await make_user(repo, i) for i in range(3)]
    for u in users:
        res = await matching.create_and_match(repo, trip(u))
    shares = await payments.complete_group(repo, res.group_id, 4000)
    assert [s.amount for s in shares] == [1334, 1333, 1333]
    assert shares[0].is_organizer and shares[0].user_id == users[0]
    later = datetime.now(TIMEZONE) + timedelta(hours=25)
    assert await payments.has_blocking_debt(repo, users[1], later)
    assert not await payments.has_blocking_debt(repo, users[0], later)
    assert not await payments.has_blocking_debt(repo, users[1])  # 24 часа ещё не прошли
    assert await payments.confirm_payment(repo, shares[1].payment_id)
    assert not await payments.has_blocking_debt(repo, users[1], later)
    assert (await repo.get_user(users[0]))["trips_count"] == 1


async def test_funnel(repo):
    users = [await make_user(repo, i) for i in range(2)]
    for u in users:
        await repo.add_event("registered", u, None)
    await matching.create_and_match(repo, trip(users[0]))
    counts = await repo.distinct_users_by_event()
    steps = compute_funnel(counts)
    assert [s.count for s in steps] == [2, 1, 0, 0]
    assert steps[1].pct_prev == 50.0 and steps[2].pct_prev == 0.0
    assert compute_funnel({})[1].pct_prev is None


async def test_delete_me_anonymizes_events(repo):
    u = await make_user(repo, 1)
    await repo.add_event("registered", u, None)
    await matching.create_and_match(repo, trip(u))
    await repo.delete_user(u)
    assert await repo.get_user(u) is None
    assert await repo.count("trips") == 0
    assert (await repo.distinct_users_by_event())["registered"] == 1
