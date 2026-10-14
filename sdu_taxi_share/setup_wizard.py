"""Мастер первого запуска: спрашивает токен и ID в консоли и сохраняет их в .env.

Нужен для запуска .exe двойным щелчком — без ручного редактирования файлов.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Callable

TOKEN_RE = re.compile(r"^\d{5,}:[A-Za-z0-9_-]{30,}$")
GMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _ask(prompt: str, validate: Callable[[str], bool], ask: Callable[[str], str],
         optional: bool = False) -> str:
    while True:
        value = ask(prompt).strip()
        if optional and not value:
            return ""
        if validate(value):
            return value
        print("  Неверный формат, попробуйте ещё раз.")


def build_env(token: str, admin_id: str, gmail: str = "", app_password: str = "") -> str:
    lines = [
        "# Создано мастером первого запуска SDU Taxi Share",
        f"BOT_TOKEN={token}",
        f"ADMIN_IDS={admin_id}",
    ]
    if gmail and app_password:
        lines += [
            "SMTP_HOST=smtp.gmail.com",
            "SMTP_PORT=465",
            f"SMTP_USER={gmail}",
            f"SMTP_PASSWORD={app_password}",
            "DEV_MODE=false",
        ]
    else:
        lines += [
            "# Почта не настроена: коды подтверждения печатаются в окне бота.",
            "# Чтобы отправлять коды студентам на почту, заполните SMTP_* (см. .env.example)",
            "# и поставьте DEV_MODE=false.",
            "DEV_MODE=true",
        ]
    return "\n".join(lines) + "\n"


def run_wizard(env_path: Path, ask: Callable[[str], str] = input) -> bool:
    """Возвращает True, если .env создан."""
    print()
    print("=" * 64)
    print(" SDU Taxi Share — первый запуск")
    print("=" * 64)
    print(" Файл настроек .env не найден. Ответьте на 2–4 вопроса, и бот")
    print(" сохранит настройки в", env_path)
    print()
    print(" 1) Токен бота: в Telegram откройте @BotFather → /newbot.")
    print("    Пример: 123456789:AAH4kq...  (вставить в окно: правый клик)")
    token = _ask(" Токен: ", lambda v: bool(TOKEN_RE.match(v)), ask)
    print()
    print(" 2) Ваш Telegram ID: напишите боту @userinfobot, он пришлёт число Id.")
    admin_id = _ask(" Ваш ID: ", str.isdigit, ask)
    print()
    print(" 3) Почта для отправки кодов студентам (Gmail). Можно пропустить —")
    print("    нажмите Enter, тогда коды будут видны только в этом окне (для теста).")
    gmail = _ask(" Gmail (или Enter): ", lambda v: bool(GMAIL_RE.match(v)), ask, optional=True)
    app_password = ""
    if gmail:
        print("    Нужен «пароль приложения» Google (16 букв): Аккаунт Google → Безопасность →")
        print("    Двухэтапная аутентификация → Пароли приложений.")
        app_password = _ask(" Пароль приложения: ", lambda v: len(v.replace(" ", "")) >= 8, ask)
        app_password = app_password.replace(" ", "")
    env_path.write_text(build_env(token, admin_id, gmail, app_password), encoding="utf-8")
    print()
    print(" Готово! Настройки сохранены. Изменить их можно в файле .env (Блокнотом).")
    print("=" * 64)
    print()
    return True
