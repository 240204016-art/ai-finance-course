"""Рейтинг пользователей."""
from __future__ import annotations

from config import LOW_RATING_MIN_COUNT, LOW_RATING_THRESHOLD
from db.repo import Repo


def average(rating_sum: int, rating_count: int) -> float | None:
    return rating_sum / rating_count if rating_count else None


def is_low(rating_sum: int, rating_count: int) -> bool:
    avg = average(rating_sum, rating_count)
    return rating_count >= LOW_RATING_MIN_COUNT and avg is not None and avg < LOW_RATING_THRESHOLD


async def apply_score(repo: Repo, user_id: int, score: int):
    """Учитывает оценку (или штраф). Возвращает пользователя, если нужно предупредить админа."""
    user = await repo.add_score(user_id, score)
    if user is None:
        return None
    low = is_low(user["rating_sum"], user["rating_count"])
    if low and not user["low_rating_notified"]:
        await repo.update_user(user_id, low_rating_notified=1)
        return user
    if not low and user["low_rating_notified"]:
        await repo.update_user(user_id, low_rating_notified=0)
    return None
