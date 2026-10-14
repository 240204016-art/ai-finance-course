"""Ввод суммы организатором, деление, «Я оплатил», подтверждение оплаты."""
from __future__ import annotations

from html import escape

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from config import MAX_TRIP_PRICE, PAYMENT_DEADLINE_HOURS
from db.repo import Repo
from handlers.middlewares import Registered
from keyboards import inline
from keyboards.callbacks import GroupCb, PayCb
from services import notify, payments
from services.timeutil import short_date
from texts import t

router = Router(name="payments")
router.message.filter(Registered())
router.callback_query.filter(Registered())


class PriceInput(StatesGroup):
    amount = State()


async def _organizer_group(repo: Repo, group_id: int, user):
    group = await repo.get_group(group_id)
    if group is None or group["organizer_id"] != user["id"]:
        return None
    return group


@router.callback_query(GroupCb.filter(F.action == "price"))
async def ask_amount(call: CallbackQuery, callback_data: GroupCb, state: FSMContext,
                     user, repo: Repo) -> None:
    group = await _organizer_group(repo, callback_data.group_id, user)
    if group is None:
        await call.answer(t("not_organizer"), show_alert=True)
        return
    if group["status"] != "formed":
        await call.answer(t("price_already_set"), show_alert=True)
        return
    await call.answer()
    await state.set_state(PriceInput.amount)
    await state.update_data(group_id=group["id"])
    await call.message.answer(t("enter_price"))


def _parse_amount(text: str) -> int | None:
    digits = "".join(ch for ch in text if not ch.isspace()).lower()
    for suffix in ("₸", "тг", "tg", "kzt", "теңге", "тенге"):
        digits = digits.removesuffix(suffix)
    if not digits.isdigit():
        return None
    value = int(digits)
    return value if 1 <= value <= MAX_TRIP_PRICE else None


@router.message(PriceInput.amount, F.text)
async def receive_amount(message: Message, state: FSMContext, user, repo: Repo, bot: Bot) -> None:
    amount = _parse_amount(message.text)
    if amount is None:
        await message.answer(t("price_invalid", max=MAX_TRIP_PRICE))
        return
    group_id = (await state.get_data())["group_id"]
    await state.clear()
    group = await _organizer_group(repo, group_id, user)
    if group is None:
        await message.answer(t("not_organizer"))
        return
    shares = await payments.complete_group(repo, group_id, amount)
    if shares is None:
        await message.answer(t("price_already_set"))
        return

    organizer = next(s for s in shares if s.is_organizer)
    summary = t("split_summary", total=amount, count=len(shares),
                lines="\n".join(t("split_line", name=escape(s.name), amount=s.amount) for s in shares))
    for share in shares:
        if share.is_organizer:
            await notify.safe_send(bot, share.telegram_id, summary + t("organizer_wait_payments"))
        else:
            await notify.safe_send(
                bot, share.telegram_id,
                summary + t("pay_to_organizer", amount=share.amount, organizer=escape(organizer.name),
                            hours=PAYMENT_DEADLINE_HOURS),
                reply_markup=inline.i_paid(share.payment_id))
    await notify.send_rating_prompts(bot, repo, group_id)


@router.callback_query(GroupCb.filter(F.action == "not_happened"))
async def not_happened(call: CallbackQuery, callback_data: GroupCb, user, repo: Repo, bot: Bot) -> None:
    group = await _organizer_group(repo, callback_data.group_id, user)
    if group is None:
        await call.answer(t("not_organizer"), show_alert=True)
        return
    if group["status"] != "formed":
        await call.answer(t("stale_button"), show_alert=True)
        return
    await call.answer()
    members = await payments.cancel_group(repo, group["id"])
    await call.message.edit_text(t("trip_not_happened_done"))
    for member in members:
        if member["user_id"] != user["id"]:
            await notify.safe_send(bot, member["telegram_id"], t(
                "trip_not_happened_member", date=short_date(group["date"]), time=group["time"]))


@router.callback_query(PayCb.filter(F.action == "paid"))
async def mark_paid(call: CallbackQuery, callback_data: PayCb, user, repo: Repo, bot: Bot) -> None:
    payment = await repo.get_payment(callback_data.payment_id)
    if payment is None or payment["user_id"] != user["id"] or payment["status"] != "pending":
        await call.answer(t("payment_already_done"), show_alert=True)
        return
    await call.answer()
    await repo.set_payment_status(payment["id"], "marked_paid")
    await call.message.edit_reply_markup(reply_markup=None)
    await call.message.answer(t("payment_marked"))
    group = await repo.get_group(payment["group_id"])
    organizer = await repo.get_user(group["organizer_id"]) if group["organizer_id"] else None
    if organizer is not None:
        await notify.safe_send(bot, organizer["telegram_id"],
                               t("payment_check_organizer", name=escape(user["name"]),
                                 amount=payment["amount"]),
                               reply_markup=inline.confirm_payment(payment["id"]))


@router.callback_query(PayCb.filter(F.action.in_({"confirm", "reject"})))
async def organizer_decision(call: CallbackQuery, callback_data: PayCb, user, repo: Repo,
                             bot: Bot) -> None:
    payment = await repo.get_payment(callback_data.payment_id)
    group = await repo.get_group(payment["group_id"]) if payment else None
    if group is None or group["organizer_id"] != user["id"]:
        await call.answer(t("not_organizer"), show_alert=True)
        return
    if payment["status"] == "confirmed":
        await call.answer(t("payment_already_done"), show_alert=True)
        return
    await call.answer()
    payer = await repo.get_user(payment["user_id"])
    if callback_data.action == "confirm":
        await payments.confirm_payment(repo, payment["id"])
        await call.message.edit_text(t("payment_confirmed_org"))
        if payer:
            await notify.safe_send(bot, payer["telegram_id"],
                                   t("payment_confirmed_payer", amount=payment["amount"]))
    else:
        await repo.set_payment_status(payment["id"], "pending")
        await call.message.edit_text(t("payment_rejected_org"))
        if payer:
            await notify.safe_send(bot, payer["telegram_id"],
                                   t("payment_rejected_payer", amount=payment["amount"]),
                                   reply_markup=inline.i_paid(payment["id"]))
