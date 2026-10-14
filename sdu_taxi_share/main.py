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

from aiogram.exceptions import TelegramNetworkError, TelegramUnauthorizedError

from config import BASE_DIR, IS_FROZEN, Settings, load_settings
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


async def selftest() -> None:
    """Проверка собранного .exe без обращения к Telegram: БД, роутеры, планировщик, часовой пояс."""
    from services.scheduler import tick
    from services.timeutil import now_local

    settings = Settings(bot_token="1:selftest", dev_mode=True, code_secret="x")
    conn = await connect(":memory:")
    repo = Repo(conn)
    bot = Bot(settings.bot_token)
    build_dispatcher(repo, settings)
    scheduler = create_scheduler(bot, repo, settings)
    assert [job.id for job in scheduler.get_jobs()] == ["tick"]
    await tick(bot, repo, settings)
    await bot.session.close()
    await conn.close()
    print(f"selftest OK, Almaty time {now_local():%Y-%m-%d %H:%M}")


async def main() -> None:
    settings = load_settings()
    if not settings.bot_token and sys.stdin and sys.stdin.isatty() \
            and not (BASE_DIR / ".env").exists():
        from setup_wizard import run_wizard
        run_wizard(BASE_DIR / ".env")
        settings = load_settings()
    setup_logging(settings)
    if not settings.bot_token:
        log.error("BOT_TOKEN не задан. Укажите токен бота в файле %s", BASE_DIR / ".env")
        sys.exit(1)
    if not settings.dev_mode and not settings.email_configured:
        log.warning("Не заданы BREVO_API_KEY или SMTP_HOST, а DEV_MODE=false — "
                    "письма с кодами не будут отправляться.")

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
        if IS_FROZEN:
            print("\n Бот работает. Не закрывайте это окно — иначе бот остановится.\n"
                  " Остановить: Ctrl+C или закрыть окно.\n", flush=True)
        await dp.start_polling(bot)
    finally:
        if scheduler.running:
            scheduler.shutdown(wait=False)
        await bot.session.close()
        await conn.close()
        log.info("bot stopped")


def run() -> int:
    if "--selftest" in sys.argv:
        asyncio.run(selftest())
        return 0
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        return 0
    except TelegramUnauthorizedError:
        log.error("Telegram не принял токен. Проверьте BOT_TOKEN в файле %s", BASE_DIR / ".env")
        return 1
    except TelegramNetworkError:
        log.error("Нет связи с Telegram. Проверьте интернет и запустите бота снова.")
        return 1
    except SystemExit as exc:
        return int(exc.code or 0)
    return 0


if __name__ == "__main__":
    code = run()
    # В .exe окно консоли закрывается сразу — даём прочитать сообщение об ошибке
    if IS_FROZEN and code != 0 and "--selftest" not in sys.argv:
        try:
            input("\nНажмите Enter, чтобы закрыть окно...")
        except EOFError:
            pass
    sys.exit(code)
