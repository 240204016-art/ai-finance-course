"""Доступ к данным. Все SQL-запросы бота собраны здесь."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

import aiosqlite

ACTIVE_TRIP_STATUSES = ("waiting", "matched")
ACTIVE_GROUP_STATUSES = ("open", "formed")

_UPDATABLE = {
    "users": {"username", "name", "gender", "show_username", "rating_sum", "rating_count",
              "trips_count", "is_banned", "low_rating_notified"},
    "groups": {"time", "women_only", "window_min", "organizer_id", "status", "total_price",
               "price_asked"},
    "trips": {"status", "group_id", "window_min", "confirmed", "reminded_30", "reminded_15"},
}


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _placeholders(items: Iterable[Any]) -> str:
    return ",".join("?" for _ in items)


class Repo:
    def __init__(self, conn: aiosqlite.Connection):
        self.conn = conn

    # --- helpers --------------------------------------------------------------

    async def _one(self, sql: str, params: Iterable[Any] = ()) -> aiosqlite.Row | None:
        async with self.conn.execute(sql, tuple(params)) as cur:
            return await cur.fetchone()

    async def _all(self, sql: str, params: Iterable[Any] = ()) -> list[aiosqlite.Row]:
        async with self.conn.execute(sql, tuple(params)) as cur:
            return list(await cur.fetchall())

    async def _write(self, sql: str, params: Iterable[Any] = ()) -> int:
        cur = await self.conn.execute(sql, tuple(params))
        await self.conn.commit()
        return cur.lastrowid

    async def _scalar(self, sql: str, params: Iterable[Any] = ()) -> Any:
        row = await self._one(sql, params)
        return row[0] if row else None

    async def _update(self, table: str, row_id: int, **fields: Any) -> None:
        if not fields:
            return
        unknown = set(fields) - _UPDATABLE[table]
        if unknown:
            raise ValueError(f"Нельзя обновить поля {unknown} в {table}")
        assignments = ", ".join(f"{k} = ?" for k in fields)
        await self._write(f"UPDATE {table} SET {assignments} WHERE id = ?",
                          [*fields.values(), row_id])

    # --- users ----------------------------------------------------------------

    async def get_user_by_tg(self, telegram_id: int) -> aiosqlite.Row | None:
        return await self._one("SELECT * FROM users WHERE telegram_id = ?", [telegram_id])

    async def get_user(self, user_id: int) -> aiosqlite.Row | None:
        return await self._one("SELECT * FROM users WHERE id = ?", [user_id])

    async def email_taken(self, email: str) -> bool:
        return await self._one("SELECT 1 FROM users WHERE email = ?", [email]) is not None

    async def create_user(self, telegram_id: int, username: str | None, name: str,
                          email: str, gender: str | None) -> int:
        return await self._write(
            "INSERT INTO users (telegram_id, username, name, email, gender, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [telegram_id, username, name, email, gender, utcnow()],
        )

    async def update_user(self, user_id: int, **fields: Any) -> None:
        await self._update("users", user_id, **fields)

    async def add_score(self, user_id: int, score: int) -> aiosqlite.Row | None:
        await self._write(
            "UPDATE users SET rating_sum = rating_sum + ?, rating_count = rating_count + 1 "
            "WHERE id = ?", [score, user_id])
        return await self.get_user(user_id)

    async def increment_trips_count(self, user_ids: list[int]) -> None:
        if not user_ids:
            return
        await self._write(
            f"UPDATE users SET trips_count = trips_count + 1 WHERE id IN ({_placeholders(user_ids)})",
            user_ids)

    async def delete_user(self, user_id: int) -> None:
        """Удаляет пользователя и связанные данные. События обезличиваются."""
        user = await self.get_user(user_id)
        await self.conn.execute("UPDATE events SET user_id = ? WHERE user_id = ?",
                                [-user_id, user_id])
        await self.conn.execute("UPDATE ratings SET complaint_text = NULL WHERE from_user = ?",
                                [user_id])
        if user is not None:
            await self.conn.execute("DELETE FROM email_codes WHERE email = ?", [user["email"]])
        # trips и payments удаляются каскадно, ratings/groups получают NULL
        await self.conn.execute("DELETE FROM users WHERE id = ?", [user_id])
        await self.conn.commit()

    # --- email codes ----------------------------------------------------------

    async def upsert_code(self, email: str, code_hash: str, expires_at: str) -> None:
        await self._write(
            "INSERT INTO email_codes (email, code_hash, expires_at, attempts, sent_at) "
            "VALUES (?, ?, ?, 0, ?) ON CONFLICT(email) DO UPDATE SET "
            "code_hash = excluded.code_hash, expires_at = excluded.expires_at, "
            "attempts = 0, sent_at = excluded.sent_at",
            [email, code_hash, expires_at, utcnow()],
        )

    async def get_code(self, email: str) -> aiosqlite.Row | None:
        return await self._one("SELECT * FROM email_codes WHERE email = ?", [email])

    async def increment_code_attempts(self, email: str) -> None:
        await self._write("UPDATE email_codes SET attempts = attempts + 1 WHERE email = ?", [email])

    async def delete_code(self, email: str) -> None:
        await self._write("DELETE FROM email_codes WHERE email = ?", [email])

    # --- groups ---------------------------------------------------------------

    async def create_group(self, direction: str, district: str, date: str, time: str,
                           women_only: bool, window_min: int, organizer_id: int) -> int:
        return await self._write(
            "INSERT INTO groups (direction, district, date, time, women_only, window_min, "
            "organizer_id, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'open', ?)",
            [direction, district, date, time, int(women_only), window_min, organizer_id, utcnow()],
        )

    async def get_group(self, group_id: int) -> aiosqlite.Row | None:
        return await self._one("SELECT * FROM groups WHERE id = ?", [group_id])

    async def update_group(self, group_id: int, **fields: Any) -> None:
        await self._update("groups", group_id, **fields)

    async def candidate_groups(self, direction: str, district: str, date: str) -> list[aiosqlite.Row]:
        return await self._all(
            f"SELECT * FROM groups WHERE direction = ? AND district = ? AND date = ? "
            f"AND status IN ({_placeholders(ACTIVE_GROUP_STATUSES)}) ORDER BY id",
            [direction, district, date, *ACTIVE_GROUP_STATUSES],
        )

    async def group_members(self, group_id: int) -> list[aiosqlite.Row]:
        """Активные участники группы в порядке присоединения."""
        return await self._all(
            "SELECT t.id AS trip_id, t.time AS trip_time, t.confirmed, t.window_min, u.id AS user_id, u.telegram_id, "
            "u.name, u.username, u.show_username, u.gender, u.rating_sum, u.rating_count "
            "FROM trips t JOIN users u ON u.id = t.user_id "
            f"WHERE t.group_id = ? AND t.status IN ({_placeholders(ACTIVE_TRIP_STATUSES)}) "
            "ORDER BY t.id",
            [group_id, *ACTIVE_TRIP_STATUSES],
        )

    async def completed_group_members(self, group_id: int) -> list[aiosqlite.Row]:
        return await self._all(
            "SELECT t.id AS trip_id, u.id AS user_id, u.telegram_id, u.name, u.username, "
            "u.show_username FROM trips t JOIN users u ON u.id = t.user_id "
            "WHERE t.group_id = ? AND t.status = 'completed' ORDER BY t.id",
            [group_id],
        )

    async def formed_groups_waiting_price(self) -> list[aiosqlite.Row]:
        return await self._all(
            "SELECT * FROM groups WHERE status = 'formed' AND price_asked = 0")

    # --- trips ----------------------------------------------------------------

    async def create_trip(self, user_id: int, direction: str, district: str, date: str,
                          time: str, women_only: bool, window_min: int) -> int:
        return await self._write(
            "INSERT INTO trips (user_id, direction, district, date, time, women_only, window_min, "
            "status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'waiting', ?)",
            [user_id, direction, district, date, time, int(women_only), window_min, utcnow()],
        )

    async def get_trip(self, trip_id: int) -> aiosqlite.Row | None:
        return await self._one("SELECT * FROM trips WHERE id = ?", [trip_id])

    async def update_trip(self, trip_id: int, **fields: Any) -> None:
        await self._update("trips", trip_id, **fields)

    async def set_group_trips_status(self, group_id: int, status: str) -> None:
        await self._write(
            f"UPDATE trips SET status = ? WHERE group_id = ? "
            f"AND status IN ({_placeholders(ACTIVE_TRIP_STATUSES)})",
            [status, group_id, *ACTIVE_TRIP_STATUSES],
        )

    async def has_active_trip(self, user_id: int, direction: str, date: str) -> bool:
        row = await self._one(
            f"SELECT 1 FROM trips WHERE user_id = ? AND direction = ? AND date = ? "
            f"AND status IN ({_placeholders(ACTIVE_TRIP_STATUSES)})",
            [user_id, direction, date, *ACTIVE_TRIP_STATUSES],
        )
        return row is not None

    async def active_trips_of_user(self, user_id: int) -> list[aiosqlite.Row]:
        return await self._all(
            f"SELECT * FROM trips WHERE user_id = ? AND status IN "
            f"({_placeholders(ACTIVE_TRIP_STATUSES)}) ORDER BY date, time",
            [user_id, *ACTIVE_TRIP_STATUSES],
        )

    async def past_trips_of_user(self, user_id: int, limit: int = 10) -> list[aiosqlite.Row]:
        return await self._all(
            f"SELECT * FROM trips WHERE user_id = ? AND status NOT IN "
            f"({_placeholders(ACTIVE_TRIP_STATUSES)}) ORDER BY date DESC, time DESC LIMIT ?",
            [user_id, *ACTIVE_TRIP_STATUSES, limit],
        )

    async def all_active_trips(self) -> list[aiosqlite.Row]:
        return await self._all(
            "SELECT t.*, u.telegram_id FROM trips t JOIN users u ON u.id = t.user_id "
            f"WHERE t.status IN ({_placeholders(ACTIVE_TRIP_STATUSES)})",
            ACTIVE_TRIP_STATUSES,
        )

    # --- payments -------------------------------------------------------------

    async def create_payment(self, group_id: int, user_id: int, amount: int, status: str) -> int:
        now = utcnow()
        return await self._write(
            "INSERT INTO payments (group_id, user_id, amount, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [group_id, user_id, amount, status, now, now],
        )

    async def get_payment(self, payment_id: int) -> aiosqlite.Row | None:
        return await self._one("SELECT * FROM payments WHERE id = ?", [payment_id])

    async def set_payment_status(self, payment_id: int, status: str) -> None:
        await self._write("UPDATE payments SET status = ?, updated_at = ? WHERE id = ?",
                          [status, utcnow(), payment_id])

    async def mark_payment_overdue_notified(self, payment_id: int) -> None:
        await self._write("UPDATE payments SET overdue_notified = 1 WHERE id = ?", [payment_id])

    async def unpaid_payments_of_user(self, user_id: int) -> list[aiosqlite.Row]:
        return await self._all(
            "SELECT * FROM payments WHERE user_id = ? AND status != 'confirmed' ORDER BY id",
            [user_id])

    async def overdue_payments(self, created_before: str) -> list[aiosqlite.Row]:
        return await self._all(
            "SELECT * FROM payments WHERE status != 'confirmed' AND overdue_notified = 0 "
            "AND created_at < ?", [created_before])

    async def has_overdue_debt(self, user_id: int, created_before: str) -> bool:
        row = await self._one(
            "SELECT 1 FROM payments WHERE user_id = ? AND status != 'confirmed' "
            "AND created_at < ?", [user_id, created_before])
        return row is not None

    # --- ratings --------------------------------------------------------------

    async def rating_exists(self, group_id: int, from_user: int, to_user: int) -> bool:
        row = await self._one(
            "SELECT 1 FROM ratings WHERE group_id = ? AND from_user = ? AND to_user = ? "
            "AND score IS NOT NULL", [group_id, from_user, to_user])
        return row is not None

    async def add_rating(self, group_id: int, from_user: int, to_user: int, score: int) -> int:
        return await self._write(
            "INSERT INTO ratings (group_id, from_user, to_user, score, created_at) "
            "VALUES (?, ?, ?, ?, ?)", [group_id, from_user, to_user, score, utcnow()])

    async def add_complaint(self, group_id: int, from_user: int, to_user: int, text: str) -> int:
        return await self._write(
            "INSERT INTO ratings (group_id, from_user, to_user, complaint_text, created_at) "
            "VALUES (?, ?, ?, ?, ?)", [group_id, from_user, to_user, text, utcnow()])

    async def list_complaints(self, limit: int = 20) -> list[aiosqlite.Row]:
        return await self._all(
            "SELECT r.id, r.group_id, r.from_user, r.to_user, r.complaint_text, r.created_at, "
            "fu.name AS from_name, tu.name AS to_name "
            "FROM ratings r LEFT JOIN users fu ON fu.id = r.from_user "
            "LEFT JOIN users tu ON tu.id = r.to_user "
            "WHERE r.complaint_text IS NOT NULL ORDER BY r.id DESC LIMIT ?", [limit])

    # --- events & stats -------------------------------------------------------

    async def add_event(self, event_type: str, user_id: int | None, ref_id: int | None) -> None:
        await self._write("INSERT INTO events (type, user_id, ref_id, created_at) VALUES (?, ?, ?, ?)",
                          [event_type, user_id, ref_id, utcnow()])

    async def distinct_users_by_event(self) -> dict[str, int]:
        rows = await self._all(
            "SELECT type, COUNT(DISTINCT user_id) AS n FROM events GROUP BY type")
        return {row["type"]: row["n"] for row in rows}

    async def distinct_refs_by_event(self) -> dict[str, int]:
        rows = await self._all(
            "SELECT type, COUNT(DISTINCT ref_id) AS n FROM events GROUP BY type")
        return {row["type"]: row["n"] for row in rows}

    async def count(self, table: str) -> int:
        if table not in {"users", "trips", "groups"}:
            raise ValueError(table)
        return await self._scalar(f"SELECT COUNT(*) FROM {table}")
