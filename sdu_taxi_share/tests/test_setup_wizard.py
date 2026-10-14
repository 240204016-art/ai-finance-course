from setup_wizard import build_env, run_wizard

TOKEN = "123456789:AAH4kqZx_abcdefghijklmnopqrstuvwxyz12"


def answers(*values):
    it = iter(values)
    return lambda prompt: next(it)


def test_wizard_without_email(tmp_path):
    env = tmp_path / ".env"
    # неверный токен и ID сначала отклоняются
    assert run_wizard(env, ask=answers("bad", TOKEN, "abc", "555", ""))
    text = env.read_text(encoding="utf-8")
    assert f"BOT_TOKEN={TOKEN}" in text and "ADMIN_IDS=555" in text and "DEV_MODE=true" in text


def test_wizard_with_gmail(tmp_path):
    env = tmp_path / ".env"
    run_wizard(env, ask=answers(TOKEN, "555", "bot@gmail.com", "abcd efgh ijkl mnop"))
    text = env.read_text(encoding="utf-8")
    assert "SMTP_HOST=smtp.gmail.com" in text and "SMTP_PASSWORD=abcdefghijklmnop" in text
    assert "DEV_MODE=false" in text


def test_env_is_loadable(tmp_path, monkeypatch):
    from config import load_settings
    for key in ("BOT_TOKEN", "ADMIN_IDS", "DEV_MODE", "SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD"):
        monkeypatch.delenv(key, raising=False)
    env = tmp_path / ".env"
    env.write_text(build_env(TOKEN, "555", "bot@gmail.com", "pw12345678"), encoding="utf-8")
    s = load_settings(env)
    assert s.bot_token == TOKEN and s.admin_ids == {555} and s.email_configured and not s.dev_mode
