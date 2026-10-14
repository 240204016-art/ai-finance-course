from aiogram.types import KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove

from texts import t

MENU_BUTTON_KEYS = ("btn_add_trip", "btn_my_trips", "btn_profile", "btn_help")


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=t("btn_add_trip")), KeyboardButton(text=t("btn_my_trips"))],
            [KeyboardButton(text=t("btn_profile")), KeyboardButton(text=t("btn_help"))],
        ],
        resize_keyboard=True,
    )


def remove() -> ReplyKeyboardRemove:
    return ReplyKeyboardRemove()
