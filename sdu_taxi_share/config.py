"""Конфигурация бота: переменные окружения (.env) и константы предметной области."""
from __future__ import annotations

import hashlib
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

# Папка с .env, базой и логами. Для собранного .exe — папка, где лежит сам .exe.
IS_FROZEN = getattr(sys, "frozen", False)
BASE_DIR = Path(sys.executable).resolve().parent if IS_FROZEN else Path(__file__).resolve().parent

# --- Предметная область -------------------------------------------------------

TIMEZONE = ZoneInfo("Asia/Almaty")

EMAIL_DOMAIN = "sdu.edu.kz"

# Направления: код -> ключ текста в texts.py
DIRECTIONS = ("to_sdu", "to_almaty")

# Районы Алматы: код (хранится в БД и callback_data) -> название (на казахском)
DISTRICTS: dict[str, str] = {
    "alatau": "Алатау ауданы",
    "almaly": "Алмалы ауданы",
    "auezov": "Әуезов ауданы",
    "bostandyk": "Бостандық ауданы",
    "zhetysu": "Жетісу ауданы",
    "medeu": "Медеу ауданы",
    "nauryzbay": "Наурызбай ауданы",
    "turksib": "Түрксіб ауданы",
}

# Время выезда: с 06:00 до 22:00 с шагом 15 минут
TIME_START_MIN = 6 * 60
TIME_END_MIN = 22 * 60
TIME_STEP_MIN = 15

# Подбор
MATCH_WINDOW_MIN = 15
EXTENDED_WINDOW_MIN = 30
GROUP_MIN_SIZE = 2
GROUP_MAX_SIZE = 4

# Почтовые коды
CODE_TTL_MIN = 10
CODE_MAX_ATTEMPTS = 5
CODE_RESEND_COOLDOWN_SEC = 60

# Напоминания и отмена
REMIND_ALONE_MIN = 30
REMIND_CONFIRM_MIN = 15
LATE_CANCEL_MIN = 30
LATE_CANCEL_PENALTY_SCORE = 1  # поздняя отмена учитывается как оценка 1
ASK_PRICE_AFTER_MIN = 60  # через сколько минут после выезда спросить сумму

# Оплата
PAYMENT_DEADLINE_HOURS = 24
MAX_TRIP_PRICE = 100_000  # тенге, защита от опечаток

# Рейтинг
LOW_RATING_THRESHOLD = 3.0
LOW_RATING_MIN_COUNT = 3


# --- Переменные окружения -----------------------------------------------------

def _parse_bool(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _parse_ids(value: str | None) -> frozenset[int]:
    ids = set()
    for part in (value or "").replace(";", ",").split(","):
        part = part.strip()
        if part.lstrip("-").isdigit():
            ids.add(int(part))
    return frozenset(ids)


@dataclass(frozen=True)
class Settings:
    bot_token: str
    admin_ids: frozenset[int] = field(default_factory=frozenset)
    smtp_host: str = ""
    smtp_port: int = 465
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    brevo_api_key: str = ""
    email_from: str = ""
    email_from_name: str = "SDU Taxi Share"
    dev_mode: bool = False
    db_path: Path = BASE_DIR / "data" / "bot.db"
    log_path: Path = BASE_DIR / "logs" / "bot.log"
    code_secret: str = ""

    def is_admin(self, telegram_id: int) -> bool:
        return telegram_id in self.admin_ids

    @property
    def email_configured(self) -> bool:
        return bool(self.brevo_api_key or self.smtp_host)


def _default_db_path() -> Path:
    # На Railway к сервису подключается постоянный диск (Volume): база должна лежать на нём,
    # иначе при каждом обновлении бота данные будут теряться.
    volume = os.getenv("RAILWAY_VOLUME_MOUNT_PATH", "").strip()
    return Path(volume) / "bot.db" if volume else BASE_DIR / "data" / "bot.db"


def load_settings(env_file: Path | None = None) -> Settings:
    load_dotenv(env_file or BASE_DIR / ".env")
    token = os.getenv("BOT_TOKEN", "").strip()
    # Секрет для хэширования кодов: отдельный CODE_SECRET или производный от токена.
    secret = os.getenv("CODE_SECRET", "").strip() or hashlib.sha256(
        ("sdu-taxi-share:" + token).encode()
    ).hexdigest()
    smtp_user = os.getenv("SMTP_USER", "").strip()
    db_path = os.getenv("DB_PATH", "").strip()
    return Settings(
        bot_token=token,
        admin_ids=_parse_ids(os.getenv("ADMIN_IDS")),
        smtp_host=os.getenv("SMTP_HOST", "").strip(),
        smtp_port=int(os.getenv("SMTP_PORT", "465") or 465),
        smtp_user=smtp_user,
        smtp_password=os.getenv("SMTP_PASSWORD", ""),
        smtp_from=os.getenv("SMTP_FROM", "").strip() or smtp_user,
        brevo_api_key=os.getenv("BREVO_API_KEY", "").strip(),
        email_from=os.getenv("EMAIL_FROM", "").strip() or os.getenv("SMTP_FROM", "").strip() or smtp_user,
        email_from_name=os.getenv("EMAIL_FROM_NAME", "").strip() or "SDU Taxi Share",
        dev_mode=_parse_bool(os.getenv("DEV_MODE")),
        db_path=Path(db_path) if db_path else _default_db_path(),
        code_secret=secret,
    )
