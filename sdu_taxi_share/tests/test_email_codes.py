from pathlib import Path

import pytest

from config import Settings
from db.database import connect
from db.repo import Repo
from services import email_codes
from services.email_codes import VerifyResult

SETTINGS = Settings(bot_token="x", dev_mode=True, code_secret="secret")


@pytest.fixture
async def repo():
    conn = await connect(":memory:")
    yield Repo(conn)
    await conn.close()


@pytest.mark.parametrize("raw,ok", [
    ("Student@SDU.edu.kz ", "student@sdu.edu.kz"),
    ("a.b@sdu.edu.kz", "a.b@sdu.edu.kz"),
    ("a@gmail.com", None),
    ("a@sdu.edu.kz.evil.com", None),
    ("a@mail.sdu.edu.kz", None),
])
def test_normalize_email(raw, ok):
    assert email_codes.normalize_email(raw) == ok


async def test_code_is_hashed_and_verified(repo, capsys):
    email = "s@sdu.edu.kz"
    assert await email_codes.issue_code(repo, SETTINGS, email)
    code = capsys.readouterr().out.strip().rsplit(" ", 1)[-1]
    row = await repo.get_code(email)
    assert code not in row["code_hash"] and len(code) == 6
    assert (await email_codes.verify_code(repo, SETTINGS, email, code))[0] is VerifyResult.OK
    assert await repo.get_code(email) is None


async def test_max_attempts(repo, capsys):
    email = "s@sdu.edu.kz"
    await email_codes.issue_code(repo, SETTINGS, email)
    code = capsys.readouterr().out.strip().rsplit(" ", 1)[-1]
    wrong = "000000" if code != "000000" else "111111"
    results = [await email_codes.verify_code(repo, SETTINGS, email, wrong) for _ in range(5)]
    assert [r[1] for r in results[:4]] == [4, 3, 2, 1]
    assert results[4][0] is VerifyResult.TOO_MANY
    assert (await email_codes.verify_code(repo, SETTINGS, email, code))[0] is VerifyResult.TOO_MANY


def test_brevo_request_payload():
    import json
    settings = Settings(bot_token="x", brevo_api_key="key-123", email_from="bot@gmail.com",
                        code_secret="s")
    req = email_codes.build_brevo_request(settings, "s@sdu.edu.kz", "654321")
    body = json.loads(req.data)
    assert req.full_url == "https://api.brevo.com/v3/smtp/email" and req.get_method() == "POST"
    assert req.get_header("Api-key") == "key-123"
    assert body["to"] == [{"email": "s@sdu.edu.kz"}]
    assert body["sender"]["email"] == "bot@gmail.com"
    assert "654321" in body["textContent"]


async def test_issue_code_uses_brevo_when_key_set(repo, monkeypatch):
    sent = []
    monkeypatch.setattr(email_codes, "_send_brevo", lambda s, e, c: sent.append((e, c)))
    monkeypatch.setattr(email_codes, "_send_smtp", lambda *a: pytest.fail("SMTP не должен вызываться"))
    settings = Settings(bot_token="x", brevo_api_key="k", email_from="bot@gmail.com", code_secret="s")
    assert await email_codes.issue_code(repo, settings, "s@sdu.edu.kz")
    assert sent and sent[0][0] == "s@sdu.edu.kz"


async def test_failed_send_removes_code(repo, monkeypatch):
    def boom(*a):
        raise OSError("network")
    monkeypatch.setattr(email_codes, "_send_brevo", boom)
    settings = Settings(bot_token="x", brevo_api_key="k", email_from="bot@gmail.com", code_secret="s")
    assert not await email_codes.issue_code(repo, settings, "s@sdu.edu.kz")
    assert await repo.get_code("s@sdu.edu.kz") is None


def test_db_path_uses_railway_volume(monkeypatch, tmp_path):
    from config import load_settings
    monkeypatch.delenv("DB_PATH", raising=False)
    monkeypatch.setenv("RAILWAY_VOLUME_MOUNT_PATH", "/data")
    assert load_settings(tmp_path / "none.env").db_path == Path("/data") / "bot.db"
    monkeypatch.setenv("DB_PATH", "/x/my.db")
    assert load_settings(tmp_path / "none.env").db_path == Path("/x/my.db")
