"""Inline-клавиатуры."""
from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import DIRECTIONS, DISTRICTS, EXTENDED_WINDOW_MIN
from keyboards.callbacks import (GroupCb, NewTripCb, PayCb, ProfileCb, RateCb, RegCb, TripCb)
from services.timeutil import short_date
from texts import t


def _cancel_row(builder: InlineKeyboardBuilder) -> None:
    builder.button(text=t("btn_cancel"), callback_data=NewTripCb(step="cancel"))


# --- Регистрация ---------------------------------------------------------------

def resend_code() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text=t("btn_resend_code"), callback_data=RegCb(action="resend"))
    return b.as_markup()


def gender_choice() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text=t("btn_gender_m"), callback_data=RegCb(action="gender_m"))
    b.button(text=t("btn_gender_f"), callback_data=RegCb(action="gender_f"))
    b.button(text=t("btn_skip"), callback_data=RegCb(action="gender_skip"))
    b.adjust(2, 1)
    return b.as_markup()


# --- Создание поездки ----------------------------------------------------------

def directions() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for code in DIRECTIONS:
        b.button(text=t(f"dir_{code}"), callback_data=NewTripCb(step="dir", value=code))
    _cancel_row(b)
    b.adjust(1)
    return b.as_markup()


def districts() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for code, name in DISTRICTS.items():
        b.button(text=name, callback_data=NewTripCb(step="dist", value=code))
    _cancel_row(b)
    b.adjust(2)
    return b.as_markup()


def dates(today: str, tomorrow: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text=t("btn_today", date=short_date(today)), callback_data=NewTripCb(step="date", value=today))
    b.button(text=t("btn_tomorrow", date=short_date(tomorrow)),
             callback_data=NewTripCb(step="date", value=tomorrow))
    _cancel_row(b)
    b.adjust(2, 1)
    return b.as_markup()


def hours(slots: list[str]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    seen = []
    for slot in slots:
        hour = slot[:2]
        if hour not in seen:
            seen.append(hour)
            b.button(text=f"{hour}:__", callback_data=NewTripCb(step="hour", value=hour))
    _cancel_row(b)
    b.adjust(*([4] * ((len(seen) + 3) // 4)), 1)
    return b.as_markup()


def minutes(slots: list[str], hour: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    count = 0
    for slot in slots:
        if slot.startswith(hour + ":"):
            b.button(text=slot, callback_data=NewTripCb(step="min", value=slot.replace(":", "")))
            count += 1
    _cancel_row(b)
    b.adjust(count or 1, 1)
    return b.as_markup()


def women_only() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text=t("btn_women_only"), callback_data=NewTripCb(step="wo", value="1"))
    b.button(text=t("btn_any_gender"), callback_data=NewTripCb(step="wo", value="0"))
    _cancel_row(b)
    b.adjust(1)
    return b.as_markup()


# --- Поездки -------------------------------------------------------------------

def my_trips(active_trips, unpaid) -> InlineKeyboardMarkup | None:
    b = InlineKeyboardBuilder()
    for trip in active_trips:
        b.button(text=t("btn_cancel_trip", date=short_date(trip["date"]), time=trip["dep_time"]),
                 callback_data=TripCb(action="cancel", trip_id=trip["id"]))
    for payment in unpaid:
        if payment["status"] == "pending":
            b.button(text=f"{t('btn_i_paid')} — {payment['amount']} ₸",
                     callback_data=PayCb(action="paid", payment_id=payment["id"]))
    b.adjust(1)
    return b.as_markup() if (active_trips or unpaid) else None


def confirm_cancel(trip_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text=t("btn_yes"), callback_data=TripCb(action="cancel_yes", trip_id=trip_id))
    b.button(text=t("btn_no"), callback_data=TripCb(action="cancel_no", trip_id=trip_id))
    return b.as_markup()


def extend_window(trip_id: int, current_window: int) -> InlineKeyboardMarkup | None:
    if current_window >= EXTENDED_WINDOW_MIN:
        return None
    b = InlineKeyboardBuilder()
    b.button(text=t("btn_extend_window"), callback_data=TripCb(action="extend", trip_id=trip_id))
    return b.as_markup()


def going(trip_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text=t("btn_going_yes"), callback_data=TripCb(action="go_yes", trip_id=trip_id))
    b.button(text=t("btn_going_no"), callback_data=TripCb(action="go_no", trip_id=trip_id))
    return b.as_markup()


# --- Оплата и оценка -----------------------------------------------------------

def ask_price(group_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text=t("btn_enter_price"), callback_data=GroupCb(action="price", group_id=group_id))
    b.button(text=t("btn_trip_not_happened"), callback_data=GroupCb(action="not_happened", group_id=group_id))
    b.adjust(1)
    return b.as_markup()


def i_paid(payment_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text=t("btn_i_paid"), callback_data=PayCb(action="paid", payment_id=payment_id))
    return b.as_markup()


def confirm_payment(payment_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text=t("btn_confirm_payment"), callback_data=PayCb(action="confirm", payment_id=payment_id))
    b.button(text=t("btn_reject_payment"), callback_data=PayCb(action="reject", payment_id=payment_id))
    return b.as_markup()


def rate(group_id: int, to_user: int, with_scores: bool = True) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    if with_scores:
        for score in range(1, 6):
            b.button(text=f"{score}⭐",
                     callback_data=RateCb(group_id=group_id, to_user=to_user, score=score))
    b.button(text=t("btn_complaint"), callback_data=RateCb(group_id=group_id, to_user=to_user, score=0))
    if with_scores:
        b.adjust(5, 1)
    return b.as_markup()


# --- Профиль -------------------------------------------------------------------

def profile(show_username: bool) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text=t("btn_toggle_username", state=t("on") if show_username else t("off")),
             callback_data=ProfileCb(action="toggle_username"))
    b.button(text=t("btn_change_gender"), callback_data=ProfileCb(action="gender"))
    b.adjust(1)
    return b.as_markup()


def profile_gender() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text=t("btn_gender_m"), callback_data=ProfileCb(action="gender_m"))
    b.button(text=t("btn_gender_f"), callback_data=ProfileCb(action="gender_f"))
    b.button(text=t("btn_skip"), callback_data=ProfileCb(action="gender_none"))
    b.adjust(2, 1)
    return b.as_markup()


def confirm_delete() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text=t("btn_delete_yes"), callback_data=ProfileCb(action="delete_yes"))
    b.button(text=t("btn_cancel"), callback_data=ProfileCb(action="delete_no"))
    return b.as_markup()
