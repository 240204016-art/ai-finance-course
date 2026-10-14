"""Точка входа: python main.py"""
from __future__ import annotations

import asyncio
import logging
import sys
from logging.handlers import RotatingFileHandler

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

from config import Settings, load_settings
from db.database import connect
from db.repo import Repo
from handlers import admin, fallback, payments, profile, ratings, start, trips
from handlers.middlewares import UserMiddleware
from services.scheduler import create_scheduler

log = logging.getLogger("sdu_taxi_share")


def setup_logging(settings: Settings) -> None:
    settings.log_path.parent.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    file_handler = RotatingFileHandler(settings.log_path, maxBytes=2_000_000, backupCount=5,
                                       encoding="utf-8")
    file_handler.setFormatter(fmt)
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    logging.basicConfig(level=logging.INFO, handlers=[file_handler, console])
    logging.getLogger("apscheduler").setLevel(logging.WARNING)


def build_dispatcher(repo: Repo, settings: Settings) -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage())
    dp["repo"] = repo
    dp["settings"] = settings
    dp.message.outer_middleware(UserMiddleware())
    dp.callback_query.outer_middleware(UserMiddleware())
    # Порядок важен: fallback — последним
    dp.include_routers(start.router, admin.router, profile.router, trips.router,
                       payments.router, ratings.router, fallback.router)
    return dp


async def main() -> None:
    settings = load_settings()
    setup_logging(settings)
    if not settings.bot_token:
        log.error("BOT_TOKEN не задан. Скопируйте .env.example в .env и укажите токен.")
        sys.exit(1)
    if not settings.dev_mode and not settings.smtp_host:
        log.warning("SMTP_HOST не задан и DEV_MODE=false — письма с кодами не будут отправляться.")

    conn = await connect(settings.db_path)
    repo = Repo(conn)
    bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = build_dispatcher(repo, settings)
    scheduler = create_scheduler(bot, repo, settings)
    try:
        await bot.set_my_commands([
            BotCommand(command="start", description="Тіркелу / басты мәзір"),
            BotCommand(command="my_trips", description="Менің сапарларым"),
            BotCommand(command="profile", description="Профиль"),
            BotCommand(command="help", description="Көмек"),
            BotCommand(command="rules", description="Қауіпсіздік ережелері"),
            BotCommand(command="delete_me", description="Деректерімді өшіру"),
        ])
        scheduler.start()
        log.info("bot started dev_mode=%s", settings.dev_mode)
        await dp.start_polling(bot)
    finally:
        if scheduler.running:
            scheduler.shutdown(wait=False)
        await bot.session.close()
        await conn.close()
        log.info("bot stopped")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
