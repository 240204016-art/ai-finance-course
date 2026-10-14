"""Одноразовые коды подтверждения почты. В БД хранится только HMAC-хэш кода."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import re
import secrets
import smtplib
import ssl
import urllib.request
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from enum import Enum

from config import (CODE_MAX_ATTEMPTS, CODE_RESEND_COOLDOWN_SEC, CODE_TTL_MIN, EMAIL_DOMAIN,
                    Settings)
from db.repo import Repo
from texts import t

log = logging.getLogger(__name__)

_EMAIL_RE = re.compile(r"^[a-z0-9._%+-]+@" + re.escape(EMAIL_DOMAIN) + r"$")


class VerifyResult(Enum):
    OK = "ok"
    WRONG = "wrong"
    EXPIRED = "expired"
    TOO_MANY = "too_many"
    NOT_FOUND = "not_found"


def normalize_email(raw: str) -> str | None:
    email = raw.strip().lower()
    return email if _EMAIL_RE.match(email) else None


def generate_code() -> str:
    return f"{secrets.randbelow(10**6):06d}"


def hash_code(email: str, code: str, secret: str) -> str:
    return hmac.new(secret.encode(), f"{email}:{code}".encode(), hashlib.sha256).hexdigest()


async def resend_wait_seconds(repo: Repo, email: str) -> int:
    row = await repo.get_code(email)
    if row is None:
        return 0
    elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(row["sent_at"])).total_seconds()
    return max(0, int(CODE_RESEND_COOLDOWN_SEC - elapsed))


def _send_smtp(settings: Settings, to_email: str, code: str) -> None:
    msg = EmailMessage()
    msg["Subject"] = t("email_subject")
    msg["From"] = settings.smtp_from
    msg["To"] = to_email
    msg.set_content(t("email_body", code=code, ttl=CODE_TTL_MIN))
    context = ssl.create_default_context()
    if settings.smtp_port == 465:
        with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, context=context, timeout=20) as s:
            s.login(settings.smtp_user, settings.smtp_password)
            s.send_message(msg)
    else:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as s:
            s.starttls(context=context)
            s.login(settings.smtp_user, settings.smtp_password)
            s.send_message(msg)


BREVO_URL = "https://api.brevo.com/v3/smtp/email"


def build_brevo_request(settings: Settings, to_email: str, code: str) -> urllib.request.Request:
    payload = {
        "sender": {"email": settings.email_from, "name": settings.email_from_name},
        "to": [{"email": to_email}],
        "subject": t("email_subject"),
        "textContent": t("email_body", code=code, ttl=CODE_TTL_MIN),
    }
    return urllib.request.Request(
        BREVO_URL, data=json.dumps(payload).encode(), method="POST",
        headers={"api-key": settings.brevo_api_key, "content-type": "application/json",
                 "accept": "application/json"},
    )


def _send_brevo(settings: Settings, to_email: str, code: str) -> None:
    """Отправка через HTTPS API Brevo — работает там, где SMTP-порты закрыты (Railway Hobby)."""
    with urllib.request.urlopen(build_brevo_request(settings, to_email, code), timeout=20) as resp:
        if resp.status >= 300:
            raise RuntimeError(f"Brevo HTTP {resp.status}")


async def issue_code(repo: Repo, settings: Settings, email: str) -> bool:
    """Создаёт новый код, сохраняет его хэш и отправляет письмо. True — если успешно."""
    code = generate_code()
    expires = datetime.now(timezone.utc) + timedelta(minutes=CODE_TTL_MIN)
    await repo.upsert_code(email, hash_code(email, code, settings.code_secret),
                           expires.isoformat(timespec="seconds"))
    if settings.dev_mode:
        # Только для разработки: код в консоль, не в лог-файл
        print(f"[DEV_MODE] Код подтверждения для {email}: {code}", flush=True)
        return True
    try:
        sender = _send_brevo if settings.brevo_api_key else _send_smtp
        await asyncio.to_thread(sender, settings, email, code)
        return True
    except Exception as exc:  # noqa: BLE001 — любая ошибка SMTP
        # Код ответа помогает понять причину (401 — неверный ключ, 400 — неподтверждённый отправитель)
        log.error("email send failed: %s %s", type(exc).__name__, getattr(exc, "code", ""))
        await repo.delete_code(email)
        return False


async def verify_code(repo: Repo, settings: Settings, email: str, code: str) -> tuple[VerifyResult, int]:
    """Проверяет код. Возвращает результат и число оставшихся попыток."""
    row = await repo.get_code(email)
    if row is None:
        return VerifyResult.NOT_FOUND, 0
    if row["attempts"] >= CODE_MAX_ATTEMPTS:
        return VerifyResult.TOO_MANY, 0
    if datetime.fromisoformat(row["expires_at"]) < datetime.now(timezone.utc):
        return VerifyResult.EXPIRED, 0
    if hmac.compare_digest(row["code_hash"], hash_code(email, code.strip(), settings.code_secret)):
        await repo.delete_code(email)
        return VerifyResult.OK, 0
    await repo.increment_code_attempts(email)
    left = CODE_MAX_ATTEMPTS - row["attempts"] - 1
    return (VerifyResult.WRONG if left > 0 else VerifyResult.TOO_MANY), left
