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
