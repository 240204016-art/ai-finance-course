"""Создание поездки, /my_trips, отмена, расширение окна, «Вы едете?»."""
from __future__ import annotations

from html import escape

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from config import (DIRECTIONS, DISTRICTS, EXTENDED_WINDOW_MIN, LATE_CANCEL_MIN,
                    MATCH_WINDOW_MIN, PAYMENT_DEADLINE_HOURS, Settings)
from db.repo import Repo
from handlers.middlewares import Registered
from keyboards import inline
from keyboards.callbacks import NewTripCb, TripCb
from services import matching, notify, payments
from services.matching import TripRequest
from services.timeutil import available_slots, minutes_until, short_date, today_and_tomorrow
from texts import t

router = Router(name="trips")
router.message.filter(Registered())
router.callback_query.filter(Registered())


class NewTrip(StatesGroup):
    choosing = State()


def _trip_summary(trip) -> dict:
    time = trip["dep_time"] if "dep_time" in trip.keys() else trip["time"]
    return dict(direction=notify.direction_label(trip["direction"]),
                district=notify.district_label(trip["district"]),
                date=short_date(trip["date"]), time=time)


# --- Создание поездки ---------------------------------------------------------

@router.message(Command("add_trip"))
@router.message(F.text == t("btn_add_trip"))
async def add_trip(message: Message, state: FSMContext, user, repo: Repo) -> None:
    await state.clear()
    if await payments.has_blocking_debt(repo, user["id"]):
        await message.answer(t("trip_debt_block", hours=PAYMENT_DEADLINE_HOURS))
        return
    await state.set_state(NewTrip.choosing)
    await message.answer(t("ask_direction"), reply_markup=inline.directions())


@router.callback_query(NewTripCb.filter(F.step == "cancel"))
async def new_trip_cancel(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await call.answer()
    await call.message.edit_text(t("action_cancelled"))


@router.callback_query(NewTrip.choosing, NewTripCb.filter(F.step == "dir"))
async def pick_direction(call: CallbackQuery, callback_data: NewTripCb, state: FSMContext) -> None:
    await call.answer()
    if callback_data.value not in DIRECTIONS:
        return
    await state.update_data(direction=callback_data.value)
    await call.message.edit_text(t("ask_district"), reply_markup=inline.districts())


@router.callback_query(NewTrip.choosing, NewTripCb.filter(F.step == "dist"))
async def pick_district(call: CallbackQuery, callback_data: NewTripCb, state: FSMContext) -> None:
    await call.answer()
    if callback_data.value not in DISTRICTS:
        return
    await state.update_data(district=callback_data.value)
    await call.message.edit_text(t("ask_date"), reply_markup=inline.dates(*today_and_tomorrow()))


@router.callback_query(NewTrip.choosing, NewTripCb.filter(F.step == "date"))
async def pick_date(call: CallbackQuery, callback_data: NewTripCb, state: FSMContext) -> None:
    await call.answer()
    today, tomorrow = today_and_tomorrow()
    if callback_data.value not in (today, tomorrow):
        await call.message.edit_text(t("ask_date"), reply_markup=inline.dates(today, tomorrow))
        return
    slots = available_slots(callback_data.value)
    if not slots:
        await call.message.edit_text(t("no_times_left"), reply_markup=inline.dates(today, tomorrow))
        return
    await state.update_data(date=callback_data.value)
    await call.message.edit_text(t("ask_hour"), reply_markup=inline.hours(slots))


@router.callback_query(NewTrip.choosing, NewTripCb.filter(F.step == "hour"))
async def pick_hour(call: CallbackQuery, callback_data: NewTripCb, state: FSMContext) -> None:
    await call.answer()
    data = await state.get_data()
    if "date" not in data:
        return
    slots = available_slots(data["date"])
    await call.message.edit_text(t("ask_minute"), reply_markup=inline.minutes(slots, callback_data.value))


@router.callback_query(NewTrip.choosing, NewTripCb.filter(F.step == "min"))
async def pick_minute(call: CallbackQuery, callback_data: NewTripCb, state: FSMContext,
                      user, repo: Repo, bot: Bot) -> None:
    await call.answer()
    data = await state.get_data()
    if "date" not in data:
        await call.message.edit_text(t("stale_button"))
        return
    slots = available_slots(data["date"])
    value = callback_data.value
    time = f"{value[:2]}:{value[2:]}"
    if time not in slots:
        await call.message.edit_text(t("trip_time_passed"),
                                     reply_markup=inline.hours(slots) if slots else None)
        return
    await state.update_data(time=time)
    if user["gender"] == "f":
        await call.message.edit_text(t("ask_women_only"), reply_markup=inline.women_only())
        return
    await _finish(call, state, user, repo, bot, women_only=False)


@router.callback_query(NewTrip.choosing, NewTripCb.filter(F.step == "wo"))
async def pick_women_only(call: CallbackQuery, callback_data: NewTripCb, state: FSMContext,
                          user, repo: Repo, bot: Bot) -> None:
    await call.answer()
    await _finish(call, state, user, repo, bot,
                  women_only=callback_data.value == "1" and user["gender"] == "f")


async def _finish(call: CallbackQuery, state: FSMContext, user, repo: Repo, bot: Bot,
                  women_only: bool) -> None:
    data = await state.get_data()
    await state.clear()
    if not all(k in data for k in ("direction", "district", "date", "time")):
        await call.message.edit_text(t("stale_button"))
        return
    if minutes_until(data["date"], data["time"]) <= 0:
        await call.message.edit_text(t("trip_time_passed"))
        return
    if await payments.has_blocking_debt(repo, user["id"]):
        await call.message.edit_text(t("trip_debt_block", hours=PAYMENT_DEADLINE_HOURS))
        return
    if await repo.has_active_trip(user["id"], data["direction"], data["date"]):
        await call.message.edit_text(t("trip_duplicate"))
        return

    req = TripRequest(user_id=user["id"], direction=data["direction"], district=data["district"],
                      date=data["date"], time=data["time"], women_only=women_only,
                      gender=user["gender"], window_min=MATCH_WINDOW_MIN)
    result = await matching.create_and_match(repo, req)
    summary = dict(direction=notify.direction_label(req.direction),
                   district=notify.district_label(req.district),
                   date=short_date(req.date), time=req.time)
    if result.size >= 2:
        await call.message.edit_text(t("trip_joined_open", **summary))
        await notify.notify_group(bot, repo, result.group_id, result.formed_now)
    else:
        await call.message.edit_text(t("trip_created_waiting", **summary))


# --- Мои поездки --------------------------------------------------------------

@router.message(Command("my_trips"))
@router.message(F.text == t("btn_my_trips"))
async def my_trips(message: Message, state: FSMContext, user, repo: Repo) -> None:
    await state.clear()
    active = await repo.active_trips_of_user(user["id"])
    past = await repo.past_trips_of_user(user["id"])
    unpaid = await repo.unpaid_payments_of_user(user["id"])

    parts = []
    if active:
        parts.append(t("my_trips_title"))
        parts += [t("trip_line", status=t(f"status_{tr['status']}"), **_trip_summary(tr))
                  for tr in active]
    else:
        parts.append(t("my_trips_empty"))
    if unpaid:
        parts.append("\n" + t("unpaid_title"))
        parts += [t("unpaid_line", group_id=p["group_id"], amount=p["amount"],
                    status=t(f"pay_status_{p['status']}")) for p in unpaid]
    if past:
        parts.append("\n" + t("past_trips_title"))
        parts += [t("trip_line", status=t(f"status_{tr['status']}"), **_trip_summary(tr)) for tr in past]
    await message.answer("\n".join(parts), reply_markup=inline.my_trips(active, unpaid))


async def _own_active_trip(repo: Repo, trip_id: int, user):
    """Активная поездка пользователя (с полем dep_time) или None."""
    return next((tr for tr in await repo.active_trips_of_user(user["id"]) if tr["id"] == trip_id), None)


@router.callback_query(TripCb.filter(F.action == "cancel"))
async def cancel_ask(call: CallbackQuery, callback_data: TripCb, user, repo: Repo) -> None:
    trip = await _own_active_trip(repo, callback_data.trip_id, user)
    if trip is None:
        await call.answer(t("stale_button"), show_alert=True)
        return
    await call.answer()
    others = len(await repo.group_members(trip["group_id"])) - 1 if trip["group_id"] else 0
    late = others > 0 and minutes_until(trip["date"], trip["dep_time"]) < LATE_CANCEL_MIN
    text = t("confirm_cancel_trip_late", minutes=LATE_CANCEL_MIN) if late else t("confirm_cancel_trip")
    await call.message.answer(text, reply_markup=inline.confirm_cancel(trip["id"]))


@router.callback_query(TripCb.filter(F.action == "cancel_no"))
async def cancel_no(call: CallbackQuery) -> None:
    await call.answer()
    await call.message.edit_text(t("action_cancelled"))


@router.callback_query(TripCb.filter(F.action.in_({"cancel_yes", "go_no"})))
async def cancel_yes(call: CallbackQuery, callback_data: TripCb, user, repo: Repo,
                     settings: Settings, bot: Bot) -> None:
    trip = await _own_active_trip(repo, callback_data.trip_id, user)
    if trip is None:
        await call.answer(t("stale_button"), show_alert=True)
        return
    await call.answer()
    result = await notify.leave_and_notify(bot, repo, settings, trip["id"], user["name"])
    text = t("trip_cancelled_late") if result and result.late else t("trip_cancelled")
    await call.message.edit_text(text)


@router.callback_query(TripCb.filter(F.action == "go_yes"))
async def going_yes(call: CallbackQuery, callback_data: TripCb, user, repo: Repo, bot: Bot) -> None:
    trip = await _own_active_trip(repo, callback_data.trip_id, user)
    if trip is None:
        await call.answer(t("stale_button"), show_alert=True)
        return
    await call.answer()
    await repo.update_trip(trip["id"], confirmed=1)
    await call.message.edit_text(t("going_confirmed"))
    if trip["group_id"]:
        for member in await repo.group_members(trip["group_id"]):
            if member["user_id"] != user["id"]:
                await notify.safe_send(bot, member["telegram_id"],
                                       t("member_confirmed", name=escape(user["name"])))


@router.callback_query(TripCb.filter(F.action == "extend"))
async def extend(call: CallbackQuery, callback_data: TripCb, user, repo: Repo, bot: Bot) -> None:
    trip = await _own_active_trip(repo, callback_data.trip_id, user)
    if trip is None or minutes_until(trip["date"], trip["dep_time"]) <= 0:
        await call.answer(t("stale_button"), show_alert=True)
        return
    if trip["status"] != "waiting":  # попутчик уже нашёлся
        await call.answer()
        await call.message.edit_reply_markup(reply_markup=None)
        return
    if trip["window_min"] >= EXTENDED_WINDOW_MIN:
        await call.answer(t("window_already_extended"), show_alert=True)
        return
    await call.answer()
    result = await matching.extend_window(repo, trip["id"], EXTENDED_WINDOW_MIN, user["gender"])
    if result is None:
        await call.message.edit_text(t("window_extended_wait"))
        return
    await call.message.edit_text(t("window_extended_found"))
    await notify.notify_group(bot, repo, result.group_id, result.formed_now)
