"""Регистрация (/start), /help, /rules, /cancel, /delete_me."""
from __future__ import annotations

import logging
from html import escape

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from config import CODE_TTL_MIN, EMAIL_DOMAIN, Settings
from db.repo import Repo
from handlers.middlewares import Registered
from keyboards import inline, reply
from keyboards.callbacks import ProfileCb, RegCb
from services import analytics, email_codes, notify
from services.email_codes import VerifyResult
from texts import t

log = logging.getLogger(__name__)
router = Router(name="start")


class Reg(StatesGroup):
    name = State()
    email = State()
    code = State()
    gender = State()


# --- Общие команды ------------------------------------------------------------

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, user) -> None:
    await state.clear()
    if user is not None:
        await message.answer(t("welcome_back", name=escape(user["name"])),
                             reply_markup=reply.main_menu())
        return
    await state.set_state(Reg.name)
    await message.answer(t("welcome"), reply_markup=reply.remove())


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext, user) -> None:
    await state.clear()
    if user is None:
        await message.answer(t("action_cancelled") + "\n" + t("need_register"))
    else:
        await message.answer(t("action_cancelled"), reply_markup=reply.main_menu())


@router.message(Command("help"))
@router.message(F.text == t("btn_help"))
async def cmd_help(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(t("help"))


@router.message(Command("rules"))
async def cmd_rules(message: Message) -> None:
    await message.answer(t("rules"))


# --- Регистрация --------------------------------------------------------------

@router.message(Reg.name, F.text)
async def reg_name(message: Message, state: FSMContext) -> None:
    name = " ".join(message.text.split())
    if not 2 <= len(name) <= 40 or name.startswith("/"):
        await message.answer(t("ask_name_invalid"))
        return
    await state.update_data(name=name)
    await state.set_state(Reg.email)
    await message.answer(t("ask_email", domain=EMAIL_DOMAIN))


async def _send_code(message: Message, repo: Repo, settings: Settings, state: FSMContext,
                     email: str) -> None:
    wait = await email_codes.resend_wait_seconds(repo, email)
    if wait > 0:
        await state.set_state(Reg.code)
        await message.answer(t("code_resend_wait", sec=wait), reply_markup=inline.resend_code())
        return
    if not await email_codes.issue_code(repo, settings, email):
        await state.clear()
        await message.answer(t("code_send_failed"))
        return
    await state.set_state(Reg.code)
    await message.answer(t("code_sent", email=escape(email), ttl=CODE_TTL_MIN),
                         reply_markup=inline.resend_code())


@router.message(Reg.email, F.text)
async def reg_email(message: Message, state: FSMContext, repo: Repo, settings: Settings) -> None:
    email = email_codes.normalize_email(message.text)
    if email is None:
        await message.answer(t("email_invalid", domain=EMAIL_DOMAIN))
        return
    if await repo.email_taken(email):
        await message.answer(t("email_taken"))
        return
    await state.update_data(email=email)
    await _send_code(message, repo, settings, state, email)


@router.callback_query(Reg.code, RegCb.filter(F.action == "resend"))
async def reg_resend(call: CallbackQuery, state: FSMContext, repo: Repo, settings: Settings) -> None:
    await call.answer()
    email = (await state.get_data()).get("email")
    if not email:
        await call.message.answer(t("stale_button"))
        return
    await _send_code(call.message, repo, settings, state, email)


@router.message(Reg.code, F.text)
async def reg_code(message: Message, state: FSMContext, repo: Repo, settings: Settings) -> None:
    code = message.text.strip()
    if not (len(code) == 6 and code.isdigit()):
        await message.answer(t("code_format"))
        return
    email = (await state.get_data())["email"]
    result, left = await email_codes.verify_code(repo, settings, email, code)
    if result is VerifyResult.OK:
        await state.set_state(Reg.gender)
        await message.answer(t("ask_gender"), reply_markup=inline.gender_choice())
    elif result is VerifyResult.WRONG:
        await message.answer(t("code_wrong", left=left))
    else:
        key = {VerifyResult.EXPIRED: "code_expired", VerifyResult.TOO_MANY: "code_too_many",
               VerifyResult.NOT_FOUND: "code_not_found"}[result]
        await message.answer(t(key), reply_markup=inline.resend_code())


@router.callback_query(Reg.gender, RegCb.filter(F.action.startswith("gender_")))
async def reg_gender(call: CallbackQuery, callback_data: RegCb, state: FSMContext,
                     repo: Repo) -> None:
    data = await state.get_data()
    gender = {"gender_m": "m", "gender_f": "f"}.get(callback_data.action)
    await state.clear()
    await call.answer()
    if await repo.get_user_by_tg(call.from_user.id) is not None:
        await call.message.answer(t("main_menu"), reply_markup=reply.main_menu())
        return
    if await repo.email_taken(data["email"]):
        await call.message.answer(t("email_taken") + "\n/start")
        return
    user_id = await repo.create_user(call.from_user.id, call.from_user.username,
                                     data["name"], data["email"], gender)
    await analytics.log_event(repo, analytics.EV_REGISTERED, user_id)
    await call.message.edit_reply_markup(reply_markup=None)
    await call.message.answer(t("registered", name=escape(data["name"])),
                              reply_markup=reply.main_menu())


# --- Удаление данных ----------------------------------------------------------

@router.message(Command("delete_me"), Registered())
async def cmd_delete_me(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(t("confirm_delete"), reply_markup=inline.confirm_delete())


@router.callback_query(ProfileCb.filter(F.action == "delete_no"))
async def delete_no(call: CallbackQuery) -> None:
    await call.answer()
    await call.message.edit_text(t("action_cancelled"))


@router.callback_query(ProfileCb.filter(F.action == "delete_yes"), Registered())
async def delete_yes(call: CallbackQuery, user, repo: Repo, settings: Settings, bot: Bot,
                     state: FSMContext) -> None:
    await call.answer()
    await state.clear()
    for trip in await repo.active_trips_of_user(user["id"]):
        await notify.leave_and_notify(bot, repo, settings, trip["id"], user["name"],
                                      penalize_late=False)
    await repo.delete_user(user["id"])
    log.info("user deleted id=%s", user["id"])
    await call.message.delete()
    await call.message.answer(t("deleted"), reply_markup=reply.remove())
