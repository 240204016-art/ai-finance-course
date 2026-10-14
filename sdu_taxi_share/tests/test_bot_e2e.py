"""Сквозной сценарий через Dispatcher без обращения к Telegram (фейковая сессия)."""
from datetime import datetime, timedelta, timezone

import pytest
from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import AnswerCallbackQuery, EditMessageText, SendMessage
from aiogram.types import CallbackQuery, Chat, Message, Update, User

from config import Settings
from db.database import connect
from db.repo import Repo
from keyboards.callbacks import GroupCb, NewTripCb, PayCb, RateCb, RegCb
from main import build_dispatcher
from services import email_codes, scheduler, timeutil
from services.timeutil import departure_at, today_and_tomorrow
from texts import t

ADMIN_TG = 999


class FakeSession(BaseSession):
    def __init__(self):
        super().__init__()
        self.sent: list = []

    async def make_request(self, bot, method, timeout=None):
        self.sent.append(method)
        if isinstance(method, (SendMessage, EditMessageText)):
            return Message(message_id=len(self.sent), date=datetime.now(timezone.utc),
                           chat=Chat(id=method.chat_id or 1, type="private"), text=method.text)
        return True

    async def stream_content(self, *args, **kwargs):  # pragma: no cover
        raise NotImplementedError

    async def close(self):
        pass

    def texts_to(self, chat_id):
        return [m.text for m in self.sent if isinstance(m, SendMessage) and m.chat_id == chat_id]

    def last_markup_to(self, chat_id):
        for m in reversed(self.sent):
            if isinstance(m, SendMessage) and m.chat_id == chat_id and m.reply_markup is not None:
                return m.reply_markup
        return None


class Harness:
    def __init__(self, repo, settings):
        self.session = FakeSession()
        self.bot = Bot("42:TEST", session=self.session)
        self.repo = repo
        self.settings = settings
        self.dp = build_dispatcher(repo, settings)
        self.update_id = 0

    def _user(self, tg_id):
        return User(id=tg_id, is_bot=False, first_name=f"U{tg_id}", username=f"user{tg_id}")

    async def text(self, tg_id, text):
        self.update_id += 1
        msg = Message(message_id=self.update_id, date=datetime.now(timezone.utc),
                      chat=Chat(id=tg_id, type="private"), from_user=self._user(tg_id), text=text)
        await self.dp.feed_update(self.bot, Update(update_id=self.update_id, message=msg))

    async def click(self, tg_id, data):
        self.update_id += 1
        msg = Message(message_id=self.update_id, date=datetime.now(timezone.utc),
                      chat=Chat(id=tg_id, type="private"), text="...")
        cb = CallbackQuery(id=str(self.update_id), from_user=self._user(tg_id), chat_instance="x",
                           data=data.pack() if hasattr(data, "pack") else data, message=msg)
        await self.dp.feed_update(self.bot, Update(update_id=self.update_id, callback_query=cb))

    def alerts(self):
        return [m.text for m in self.session.sent if isinstance(m, AnswerCallbackQuery) and m.text]

    def edits(self):
        return [m.text for m in self.session.sent if isinstance(m, EditMessageText)]


@pytest.fixture
async def h(monkeypatch):
    monkeypatch.setattr(email_codes, "generate_code", lambda: "123456")
    conn = await connect(":memory:")
    settings = Settings(bot_token="42:TEST", admin_ids=frozenset({ADMIN_TG}), dev_mode=True,
                        code_secret="s")
    harness = Harness(Repo(conn), settings)
    yield harness
    await conn.close()
    # Роутеры — модульные синглтоны; отвязываем их, чтобы следующий тест собрал новый Dispatcher
    for router in harness.dp.sub_routers:
        router._parent_router = None


async def register(h, tg_id, name, gender_action):
    await h.text(tg_id, "/start")
    await h.text(tg_id, name)
    await h.text(tg_id, "bad@gmail.com")
    assert t("email_invalid", domain="sdu.edu.kz") in h.session.texts_to(tg_id)
    await h.text(tg_id, f"{name.lower()}@sdu.edu.kz")
    await h.text(tg_id, "000000")
    assert t("code_wrong", left=4) in h.session.texts_to(tg_id)
    await h.text(tg_id, "123456")
    await h.click(tg_id, RegCb(action=gender_action))
    assert t("registered", name=name) in h.session.texts_to(tg_id)


async def add_trip(h, tg_id, date, time, women=None):
    await h.text(tg_id, t("btn_add_trip"))
    await h.click(tg_id, NewTripCb(step="dir", value="to_sdu"))
    await h.click(tg_id, NewTripCb(step="dist", value="almaly"))
    await h.click(tg_id, NewTripCb(step="date", value=date))
    await h.click(tg_id, NewTripCb(step="hour", value=time[:2]))
    await h.click(tg_id, NewTripCb(step="min", value=time.replace(":", "")))
    if women is not None:
        await h.click(tg_id, NewTripCb(step="wo", value=women))


async def test_full_scenario(h, monkeypatch):
    _, tomorrow = today_and_tomorrow()
    await register(h, 1, "Aruzhan", "gender_f")
    await register(h, 2, "Dias", "gender_m")
    await register(h, 3, "Bota", "gender_skip")

    # Незарегистрированный пользователь
    await h.text(50, t("btn_add_trip"))
    assert t("need_register") in h.session.texts_to(50)

    await add_trip(h, 1, tomorrow, "08:00", women="0")
    assert any("серік табылмады" in e for e in h.edits())
    await add_trip(h, 2, tomorrow, "08:15")
    formed = [x for x in h.session.texts_to(1) if t("group_formed_title") in x]
    assert formed and "Dias" in formed[0] and "@user2" in formed[0] and "@sdu.edu.kz" not in formed[0]
    assert any(t("group_formed_title") in x for x in h.session.texts_to(2))

    # Повторная поездка в тот же день и направлении запрещена
    await add_trip(h, 2, tomorrow, "09:00")
    assert t("trip_duplicate") in h.edits()

    # Третий участник скрыл username
    await h.text(3, t("btn_profile"))
    await h.click(3, "pf:toggle_username")
    await add_trip(h, 3, tomorrow, "07:45")
    updated = [x for x in h.session.texts_to(1) if t("group_updated_title") in x][-1]
    assert "Bota" in updated and "@user3" not in updated

    repo = h.repo
    group = (await repo.candidate_groups("to_sdu", "almaly", tomorrow))[0]
    assert group["status"] == "formed"

    # Напоминание за 15 минут и ответ «Нет» от Bota (поздняя отмена → штраф)
    dep = departure_at(tomorrow, group["time"])
    await scheduler.process_trips(h.bot, repo, dep - timedelta(minutes=10))
    assert any(t("remind_confirm", time="08:00", district="Алмалы ауданы") == x
               for x in h.session.texts_to(3))
    trip3 = (await repo.active_trips_of_user(3))[0]
    monkeypatch.setattr(timeutil, "now_local", lambda: dep - timedelta(minutes=10))
    await h.click(3, f"tr:go_no:{trip3['id']}")
    bota = await repo.get_user(3)
    assert bota["rating_count"] == 1 and bota["rating_sum"] == 1
    assert any("Bota" in x and "шықты" in x for x in h.session.texts_to(1))

    # После поездки организатор вводит сумму
    await scheduler.process_groups(h.bot, repo, dep + timedelta(minutes=61))
    assert any("ақысын енгізіңіз" in x for x in h.session.texts_to(1))
    await h.click(1, GroupCb(action="price", group_id=group["id"]))
    await h.text(1, "abc")
    await h.text(1, "4 001 ₸")
    dias_texts = h.session.texts_to(2)
    assert any("2000 ₸" in x and "Kaspi" in x for x in dias_texts)
    assert any("2001 ₸" in x for x in h.session.texts_to(1))

    payment = (await repo.unpaid_payments_of_user(2))[0]
    await h.click(2, PayCb(action="paid", payment_id=payment["id"]))
    await h.click(2, PayCb(action="confirm", payment_id=payment["id"]))  # не организатор
    assert t("not_organizer") in h.alerts()
    await h.click(1, PayCb(action="confirm", payment_id=payment["id"]))
    assert (await repo.get_payment(payment["id"]))["status"] == "confirmed"

    # Оценки и жалоба
    await h.click(2, RateCb(group_id=group["id"], to_user=1, score=5))
    await h.click(2, RateCb(group_id=group["id"], to_user=1, score=1))
    assert t("rate_already") in h.alerts()
    await h.click(3, RateCb(group_id=group["id"], to_user=1, score=1))  # Bota вышла — нельзя
    await h.click(1, RateCb(group_id=group["id"], to_user=2, score=0))
    await h.text(1, "Кешікті")
    assert any("шағым" in x.lower() for x in h.session.texts_to(ADMIN_TG))
    assert (await repo.get_user(1))["rating_count"] == 1

    # Профиль и статистика
    await h.text(1, "/profile")
    assert any("5.0 (1 баға)" in x and "Сапарлар саны: 1" in x for x in h.session.texts_to(1))
    await h.text(2, "/stats")
    assert t("admin_only") in h.session.texts_to(2)
    await h.text(ADMIN_TG, "/stats")
    stats = h.session.texts_to(ADMIN_TG)[-1]
    assert "Тіркелді: 3" in stats and "Топ жиналды: 3" in stats and "Сапар өтті: 2" in stats
    await h.text(ADMIN_TG, "/complaints")
    assert "Кешікті" in h.session.texts_to(ADMIN_TG)[-1]


async def test_debt_blocks_new_trip_and_admin_is_notified(h):
    _, tomorrow = today_and_tomorrow()
    await register(h, 1, "Aruzhan", "gender_f")
    await register(h, 2, "Dias", "gender_m")
    await add_trip(h, 1, tomorrow, "08:00", women="0")
    await add_trip(h, 2, tomorrow, "08:00")
    group = (await h.repo.candidate_groups("to_sdu", "almaly", tomorrow))[0]
    await h.click(1, GroupCb(action="price", group_id=group["id"]))
    await h.text(1, "3000")
    # Делаем платёж «старым»
    await h.repo.conn.execute("UPDATE payments SET created_at = '2000-01-01T00:00:00+00:00'")
    await h.repo.conn.commit()
    await scheduler.process_payments(h.bot, h.repo, h.settings)
    assert any("мерзімі өтті" in x for x in h.session.texts_to(ADMIN_TG))
    await h.text(2, t("btn_add_trip"))
    assert t("trip_debt_block", hours=24) in h.session.texts_to(2)


async def test_lonely_trip_extend_and_women_only(h):
    _, tomorrow = today_and_tomorrow()
    await register(h, 1, "Aruzhan", "gender_f")
    await register(h, 2, "Dias", "gender_m")
    await register(h, 3, "Aigerim", "gender_f")
    await add_trip(h, 1, tomorrow, "08:30", women="1")
    await add_trip(h, 2, tomorrow, "08:30")  # мужчина не попадает в группу «только девушки»
    assert not any(t("group_formed_title") in x for x in h.session.texts_to(2))
    await add_trip(h, 3, tomorrow, "08:00", women="0")  # ±15 мин — не совпадает

    dep = departure_at(tomorrow, "08:00")
    await scheduler.process_trips(h.bot, h.repo, dep - timedelta(minutes=25))
    assert any("серік табылмады" in x for x in h.session.texts_to(3))
    markup = h.session.last_markup_to(3)
    assert markup is not None
    await h.click(3, markup.inline_keyboard[0][0].callback_data)
    formed = [x for x in h.session.texts_to(1) if t("group_formed_title") in x]
    assert formed and "Aigerim" in formed[0]


async def test_delete_me(h):
    await register(h, 1, "Aruzhan", "gender_f")
    await h.text(1, "/delete_me")
    await h.click(1, "pf:delete_yes")
    assert await h.repo.get_user_by_tg(1) is None
    await h.text(1, "/profile")
    assert t("need_register") in h.session.texts_to(1)


async def test_ban(h):
    await register(h, 1, "Aruzhan", "gender_f")
    user = await h.repo.get_user_by_tg(1)
    await h.text(ADMIN_TG, f"/ban {user['id']}")
    await h.text(1, "/profile")
    assert t("banned") in h.session.texts_to(1)
    await h.text(ADMIN_TG, f"/unban {user['id']}")
    await h.text(1, "/profile")
    assert any("Aruzhan" in x for x in h.session.texts_to(1)[-1:])
