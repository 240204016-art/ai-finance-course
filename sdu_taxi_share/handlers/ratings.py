"""Оценка попутчиков (1–5) и жалобы."""
from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from config import Settings
from db.repo import Repo
from handlers.middlewares import Registered
from keyboards import inline
from keyboards.callbacks import RateCb
from services import notify, ratings
from texts import t

router = Router(name="ratings")
router.message.filter(Registered())
router.callback_query.filter(Registered())


class Complaint(StatesGroup):
    text = State()


async def _were_together(repo: Repo, group_id: int, a: int, b: int) -> bool:
    if a == b:
        return False
    ids = {m["user_id"] for m in await repo.completed_group_members(group_id)}
    return a in ids and b in ids


@router.callback_query(RateCb.filter(F.score.in_({1, 2, 3, 4, 5})))
async def rate(call: CallbackQuery, callback_data: RateCb, user, repo: Repo,
               settings: Settings, bot: Bot) -> None:
    cb = callback_data
    if not await _were_together(repo, cb.group_id, user["id"], cb.to_user):
        await call.answer(t("stale_button"), show_alert=True)
        return
    if await repo.rating_exists(cb.group_id, user["id"], cb.to_user):
        await call.answer(t("rate_already"), show_alert=True)
        return
    await repo.add_rating(cb.group_id, user["id"], cb.to_user, cb.score)
    alert_user = await ratings.apply_score(repo, cb.to_user, cb.score)
    if alert_user is not None:
        await notify.alert_low_rating(bot, settings, alert_user)
    await call.answer(t("rate_thanks", score=cb.score))
    await call.message.edit_reply_markup(
        reply_markup=inline.rate(cb.group_id, cb.to_user, with_scores=False))


@router.callback_query(RateCb.filter(F.score == 0))
async def complaint_start(call: CallbackQuery, callback_data: RateCb, state: FSMContext,
                          user, repo: Repo) -> None:
    if not await _were_together(repo, callback_data.group_id, user["id"], callback_data.to_user):
        await call.answer(t("stale_button"), show_alert=True)
        return
    await call.answer()
    await state.set_state(Complaint.text)
    await state.update_data(group_id=callback_data.group_id, to_user=callback_data.to_user)
    await call.message.answer(t("ask_complaint"))


@router.message(Complaint.text, F.text)
async def complaint_text(message: Message, state: FSMContext, user, repo: Repo,
                         settings: Settings, bot: Bot) -> None:
    text = message.text.strip()
    if len(text) > 1000:
        await message.answer(t("complaint_too_long"))
        return
    data = await state.get_data()
    await state.clear()
    complaint_id = await repo.add_complaint(data["group_id"], user["id"], data["to_user"], text)
    await message.answer(t("complaint_saved"))
    await notify.notify_admins(bot, settings, t(
        "admin_new_complaint", id=complaint_id, group_id=data["group_id"],
        from_id=user["id"], to_id=data["to_user"]) + "\n/complaints")
