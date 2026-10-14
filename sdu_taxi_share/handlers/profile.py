"""/profile и настройки."""
from __future__ import annotations

from html import escape

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from db.repo import Repo
from handlers.middlewares import Registered
from keyboards import inline
from keyboards.callbacks import ProfileCb
from services.ratings import average
from texts import t

router = Router(name="profile")
router.message.filter(Registered())
router.callback_query.filter(Registered())


def profile_text(user) -> str:
    avg = average(user["rating_sum"], user["rating_count"])
    rating = t("rating_none") if avg is None else t("rating_value", rating=avg, count=user["rating_count"])
    return t(
        "profile",
        name=escape(user["name"]),
        rating=rating,
        trips=user["trips_count"],
        gender=t(f"gender_{user['gender'] or 'none'}"),
        show_username=t("on") if user["show_username"] else t("off"),
    )


@router.message(Command("profile"))
@router.message(F.text == t("btn_profile"))
async def cmd_profile(message: Message, state: FSMContext, user) -> None:
    await state.clear()
    await message.answer(profile_text(user), reply_markup=inline.profile(bool(user["show_username"])))


@router.callback_query(ProfileCb.filter(F.action == "toggle_username"))
async def toggle_username(call: CallbackQuery, user, repo: Repo) -> None:
    await repo.update_user(user["id"], show_username=0 if user["show_username"] else 1)
    user = await repo.get_user(user["id"])
    await call.answer(t("settings_saved"))
    await call.message.edit_text(profile_text(user), reply_markup=inline.profile(bool(user["show_username"])))


@router.callback_query(ProfileCb.filter(F.action == "gender"))
async def change_gender(call: CallbackQuery) -> None:
    await call.answer()
    await call.message.edit_reply_markup(reply_markup=inline.profile_gender())


@router.callback_query(ProfileCb.filter(F.action.in_({"gender_m", "gender_f", "gender_none"})))
async def set_gender(call: CallbackQuery, callback_data: ProfileCb, user, repo: Repo) -> None:
    gender = {"gender_m": "m", "gender_f": "f"}.get(callback_data.action)
    await repo.update_user(user["id"], gender=gender)
    user = await repo.get_user(user["id"])
    await call.answer(t("settings_saved"))
    await call.message.edit_text(profile_text(user), reply_markup=inline.profile(bool(user["show_username"])))
