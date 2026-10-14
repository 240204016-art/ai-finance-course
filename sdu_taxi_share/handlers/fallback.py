"""Последний роутер: всё, что не обработали остальные."""
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from keyboards import reply
from texts import t

router = Router(name="fallback")


@router.message(Command("stats", "complaints", "ban", "unban"))
async def admin_only(message: Message) -> None:
    await message.answer(t("admin_only"))


@router.message()
async def unknown_message(message: Message, user) -> None:
    if user is None:
        await message.answer(t("need_register"))
    else:
        await message.answer(t("unknown"), reply_markup=reply.main_menu())


@router.callback_query()
async def unknown_callback(call: CallbackQuery) -> None:
    await call.answer(t("stale_button"), show_alert=True)
