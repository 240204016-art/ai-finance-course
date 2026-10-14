"""Фабрики callback_data. Значения не должны содержать ':' (разделитель aiogram)."""
from aiogram.filters.callback_data import CallbackData


class RegCb(CallbackData, prefix="reg"):
    action: str  # resend | gender_m | gender_f | gender_skip


class NewTripCb(CallbackData, prefix="nt"):
    step: str  # dir | dist | date | hour | min | wo | cancel
    value: str = ""


class TripCb(CallbackData, prefix="tr"):
    action: str  # cancel | cancel_yes | cancel_no | extend | go_yes | go_no
    trip_id: int


class GroupCb(CallbackData, prefix="gr"):
    action: str  # price | not_happened
    group_id: int


class PayCb(CallbackData, prefix="pay"):
    action: str  # paid | confirm | reject
    payment_id: int


class RateCb(CallbackData, prefix="rate"):
    group_id: int
    to_user: int
    score: int  # 1..5; 0 — жалоба


class ProfileCb(CallbackData, prefix="pf"):
    action: str  # toggle_username | gender | gender_m | gender_f | gender_none | delete_yes | delete_no
