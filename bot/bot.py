#!/usr/bin/env python3
"""Сату боты: Kaspi төлемі (чекті қолмен растау) → жабық Telegram-арнаға бір реттік сілтеме.

    python3 bot.py

Сыртқы кітапхана қажет емес (Python 3.9+). Баптаулар .env файлынан не орта
айнымалыларынан оқылады — .env.example мен README.md қараңыз.

Жұмыс реті:
  1. Сатып алушы лендингтен келеді: /start buy немесе /start promo_КОД.
  2. «Офертамен келісемін, төлеу» → бот Kaspi деректерін береді.
  3. Сатып алушы чекті (фото не PDF) жібереді → бот оны әкімшіге
     «Растау / Қабылдамау» батырмаларымен жолдайды.
  4. Растау → сатып алушыға арнаға кіретін бір реттік сілтеме келеді.
"""
import json
import logging
import os
import pathlib
import sqlite3
import time
import urllib.error
import urllib.request

log = logging.getLogger("bot")
HERE = pathlib.Path(__file__).parent


def load_env(path):
    """KEY=VALUE жолдарын os.environ ішіне қосады (бұрыннан бар мәндерді өзгертпейді)."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def money(n):
    return f"{n:,}".replace(",", " ") + " ₸"


class Config:
    def __init__(self, env):
        self.token = env.get("BOT_TOKEN", "")
        self.admins = [int(x) for x in env.get("ADMIN_IDS", "").replace(" ", "").split(",") if x]
        self.channel = env.get("CHANNEL_ID", "").strip()
        self.product = env.get("PRODUCT_NAME", "Курс")
        self.price = int(env.get("PRICE", "9900"))
        self.kaspi_phone = env.get("KASPI_PHONE", "")
        self.kaspi_name = env.get("KASPI_NAME", "")
        self.kaspi_url = env.get("KASPI_PAY_URL", "")
        self.oferta_url = env.get("OFERTA_URL", "")
        self.support = env.get("SUPPORT", "").lstrip("@")
        self.db_path = env.get("DB_PATH", str(HERE / "orders.db"))
        self.promos = {}  # КОД -> баға
        for pair in env.get("PROMOS", "").split(","):
            if ":" in pair:
                code, price = pair.split(":", 1)
                self.promos[code.strip().upper()] = int(price)

    def problems(self):
        out = []
        if not self.token:
            out.append("BOT_TOKEN жоқ")
        if not self.admins:
            out.append("ADMIN_IDS жоқ")
        if not (self.kaspi_phone or self.kaspi_url):
            out.append("KASPI_PHONE не KASPI_PAY_URL керек")
        return out


class ApiError(Exception):
    pass


class Api:
    def __init__(self, token):
        self.base = f"https://api.telegram.org/bot{token}/"

    def call(self, method, **params):
        req = urllib.request.Request(
            self.base + method,
            data=json.dumps(params).encode(),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=params.get("timeout", 0) + 20) as resp:
                body = json.load(resp)
        except urllib.error.HTTPError as e:
            try:
                body = json.load(e)
            except ValueError:
                raise ApiError(f"{method}: HTTP {e.code}") from None
        except OSError as e:  # желі үзілуі, тайм-аут
            raise ApiError(f"{method}: {e}") from None
        if not body.get("ok"):
            raise ApiError(f"{method}: {body.get('description')}")
        return body["result"]


class Orders:
    """Әр сатып алушыға бір жол. status: new → awaiting → review → paid | rejected."""

    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS orders (user_id INTEGER PRIMARY KEY, username TEXT, name TEXT,"
            " price INTEGER, promo TEXT, status TEXT, updated INTEGER)"
        )
        self.db.commit()

    def get(self, user_id):
        return self.db.execute("SELECT * FROM orders WHERE user_id=?", (user_id,)).fetchone()

    def save(self, user, **fields):
        self.db.execute("INSERT OR IGNORE INTO orders (user_id, status) VALUES (?, 'new')", (user["id"],))
        fields.update(
            username=user.get("username", ""),
            name=" ".join(filter(None, [user.get("first_name"), user.get("last_name")])),
        )
        self.set(user["id"], **fields)

    def set(self, user_id, **fields):
        fields["updated"] = int(time.time())
        cols = ", ".join(f"{k}=?" for k in fields)
        self.db.execute(f"UPDATE orders SET {cols} WHERE user_id=?", (*fields.values(), user_id))
        self.db.commit()

    def stats(self):
        rows = self.db.execute("SELECT status, COUNT(*) n, COALESCE(SUM(price),0) s FROM orders GROUP BY status")
        return {r["status"]: (r["n"], r["s"]) for r in rows}


def kb(*rows):
    return {"inline_keyboard": [list(r) for r in rows]}


class Bot:
    def __init__(self, cfg, api, orders):
        self.cfg, self.api, self.orders = cfg, api, orders

    def send(self, chat_id, text, markup=None):
        params = {"chat_id": chat_id, "text": text, "disable_web_page_preview": True}
        if markup:
            params["reply_markup"] = markup
        return self.api.call("sendMessage", **params)

    def support_line(self):
        return f"\n\nСұрақ болса: @{self.cfg.support}" if self.cfg.support else ""

    # ---------- кіріс ----------

    def handle(self, update):
        try:
            if "message" in update:
                self.on_message(update["message"])
            elif "callback_query" in update:
                self.on_callback(update["callback_query"])
            elif "my_chat_member" in update:
                self.on_membership(update["my_chat_member"])
        except ApiError as e:
            log.error("Telegram қатесі: %s", e)

    def on_message(self, msg):
        if msg["chat"]["type"] != "private" or "from" not in msg:
            return
        user, text = msg["from"], msg.get("text", "")
        if text.startswith("/start"):
            self.start(user, text[6:].strip())
        elif text.startswith("/id"):
            self.send(user["id"], f"Сіздің ID: {user['id']}")
        elif text.startswith("/stats") and user["id"] in self.cfg.admins:
            self.stats(user["id"])
        elif "photo" in msg or "document" in msg:
            self.receipt(user, msg)
        else:
            self.send(user["id"], "Сатып алу үшін /start басыңыз. Төлеп қойсаңыз, чекті (скриншот не PDF) осы чатқа жіберіңіз."
                      + self.support_line())

    # ---------- сатып алушы ----------

    def start(self, user, payload):
        order = self.orders.get(user["id"])
        if order and order["status"] == "paid":
            return self.grant(user["id"], again=True)
        if order and order["status"] == "review":
            return self.send(user["id"], "Чегіңіз тексеріліп жатыр. Расталған соң сілтеме осы чатқа келеді.")

        price, promo, extra = self.cfg.price, "", ""
        if payload.startswith("promo_"):
            code = payload[6:].upper()
            if code in self.cfg.promos:
                price, promo = self.cfg.promos[code], code
                extra = f"\n\nПромокод {code} қолданылды: {money(self.cfg.price)} → {money(price)}."
            else:
                extra = f"\n\nПромокод {code} табылмады, баға өзгерген жоқ."
        elif order and order["promo"] in self.cfg.promos:  # бұрын қолданылған промокод сақталады
            price, promo = order["price"], order["promo"]
        self.orders.save(user, price=price, promo=promo, status="new")

        rows = [[{"text": f"Офертамен келісемін, төлеу · {money(price)}", "callback_data": "pay"}]]
        if self.cfg.oferta_url:
            rows.append([{"text": "Офертаны оқу", "url": self.cfg.oferta_url}])
        self.send(
            user["id"],
            f"Сәлем! Сіз «{self.cfg.product}» пакетін таңдадыңыз: {money(price)}.{extra}\n\n"
            "Төлем Kaspi арқылы. Төлегеннен кейін жабық арнаға кіру сілтемесі осы чатқа келеді.\n\n"
            "Төлем батырмасын басу арқылы жария оферта шарттарын қабылдайсыз.",
            kb(*rows),
        )

    def pay(self, user):
        order = self.orders.get(user["id"])
        if not order:
            return self.start(user, "")
        if order["status"] == "paid":
            return self.grant(user["id"], again=True)
        if order["status"] == "review":
            return self.send(user["id"], "Чегіңіз тексеріліп жатыр. Расталған соң сілтеме осы чатқа келеді.")
        self.orders.set(user["id"], status="awaiting")

        lines = [f"«{self.cfg.product}»: {money(order['price'])}", ""]
        if self.cfg.kaspi_phone:
            lines.append(f"Kaspi аударым: {self.cfg.kaspi_phone}")
            if self.cfg.kaspi_name:
                lines.append(f"Алушы: {self.cfg.kaspi_name}")
            lines.append("")
        if self.cfg.kaspi_url:
            lines += ["Төмендегі батырма арқылы да төлеуге болады.", ""]
        lines.append(f"Дәл {money(order['price'])} аударып, чекті (скриншот не PDF) осы чатқа жіберіңіз. "
                     "Тексерілген соң арнаға сілтеме келеді.")
        markup = kb([{"text": "Kaspi-де төлеу", "url": self.cfg.kaspi_url}]) if self.cfg.kaspi_url else None
        self.send(user["id"], "\n".join(lines), markup)

    def receipt(self, user, msg):
        order = self.orders.get(user["id"])
        if not order or order["status"] == "new":
            return self.send(user["id"], "Алдымен /start басып, төлем деректерін алыңыз.")
        if order["status"] == "paid":
            return self.grant(user["id"], again=True)
        if order["status"] == "review":
            return self.send(user["id"], "Чегіңіз тексеріліп жатыр, сәл күте тұрыңыз.")

        self.orders.save(user, status="review")
        order = self.orders.get(user["id"])
        who = order["name"] + (f" (@{order['username']})" if order["username"] else "")
        caption = (f"Жаңа чек\n{who}\nID: {user['id']}\nСома: {money(order['price'])}"
                   + (f"\nПромокод: {order['promo']}" if order["promo"] else ""))
        markup = kb([{"text": "✅ Растау", "callback_data": f"ok:{user['id']}"},
                     {"text": "❌ Қабылдамау", "callback_data": f"no:{user['id']}"}])
        delivered = 0
        for admin in self.cfg.admins:
            try:
                self.api.call("copyMessage", chat_id=admin, from_chat_id=msg["chat"]["id"],
                              message_id=msg["message_id"], caption=caption, reply_markup=markup)
                delivered += 1
            except ApiError as e:
                log.error("Чек %s әкімшісіне жетпеді: %s", admin, e)
        if not delivered:  # ешбір әкімшіге жетпесе, чекті қайта жіберуге мүмкіндік қалады
            self.orders.set(user["id"], status="awaiting")
            return self.send(user["id"], "Чекті қабылдау кезінде қате шықты. Сәл кейінірек қайта жіберіңіз."
                             + self.support_line())
        self.send(user["id"], "Чек қабылданды ✅ Тексерілген соң арнаға сілтеме осы чатқа келеді.")

    def grant(self, user_id, again=False):
        """Арнаға бір адамға ғана жарайтын сілтеме жасап, сатып алушыға жібереді."""
        link = self.api.call("createChatInviteLink", chat_id=self.cfg.channel, member_limit=1,
                             name=f"user {user_id}")["invite_link"]
        text = ("Сіз бұл пакетті сатып алғансыз. Міне, арнаға жаңа сілтеме:" if again
                else f"Төлем расталды 🎉 «{self.cfg.product}» арнасына қош келдіңіз!")
        self.send(user_id, text + "\n\nСілтеме бір рет қана жарайды, оны ешкімге бермеңіз.",
                  kb([{"text": "Арнаға кіру", "url": link}]))

    # ---------- әкімші ----------

    def on_callback(self, cq):
        user, data, note, alert = cq["from"], cq.get("data", ""), "", False
        try:
            if data == "pay":
                self.pay(user)
            elif data[:3] in ("ok:", "no:"):
                note, alert = self.decide(cq, data[:2] == "ok", int(data[3:]))
        except ApiError as e:
            log.error("Callback қатесі: %s", e)
            note, alert = f"Қате: {e}", True
        self.api.call("answerCallbackQuery", callback_query_id=cq["id"], text=note[:200], show_alert=alert)

    def decide(self, cq, approve, buyer_id):
        if cq["from"]["id"] not in self.cfg.admins:
            return "Бұл батырма тек әкімшіге арналған.", True
        order = self.orders.get(buyer_id)
        if not order or order["status"] != "review":
            verdict = {"paid": "расталған", "awaiting": "қабылданбаған"}.get(order and order["status"], "шешілген")
            self.close_admin_message(cq, f"Бұрын {verdict}")
            return f"Бұл чек бұрын {verdict}.", True
        if approve:
            if not self.cfg.channel:
                return "CHANNEL_ID бапталмаған — .env файлын толтырыңыз.", True
            self.grant(buyer_id)  # сілтеме жасалмаса (бот арна әкімшісі емес), статус өзгермейді
            self.orders.set(buyer_id, status="paid")
            self.close_admin_message(cq, "✅ Расталды")
            return "Расталды, сілтеме жіберілді.", False
        self.orders.set(buyer_id, status="awaiting")
        self.close_admin_message(cq, "❌ Қабылданбады")
        self.send(buyer_id, "Төлем расталмады 😕 Сома мен алушыны тексеріп, дұрыс чекті осы чатқа қайта жіберіңіз."
                  + self.support_line())
        return "Қабылданбады, сатып алушыға хабарланды.", False

    def close_admin_message(self, cq, verdict):
        msg = cq.get("message")
        if not msg:
            return
        by = cq["from"].get("first_name", "")
        try:
            self.api.call("editMessageCaption", chat_id=msg["chat"]["id"], message_id=msg["message_id"],
                          caption=f"{msg.get('caption', '')}\n\n{verdict} · {by}")
        except ApiError as e:
            log.warning("Әкімші хабары жаңартылмады: %s", e)

    def stats(self, chat_id):
        s = self.orders.stats()
        names = [("paid", "Төленген"), ("review", "Тексеруде"), ("awaiting", "Чек күтілуде"), ("new", "Тек /start басқан")]
        lines = [f"{label}: {s.get(key, (0, 0))[0]}" for key, label in names]
        lines.append(f"\nТүсім: {money(s.get('paid', (0, 0))[1])}")
        self.send(chat_id, "\n".join(lines))

    def on_membership(self, m):
        """Бот арнаға әкімші болып қосылғанда арна ID-ін әкімшілерге жібереді — CHANNEL_ID үшін."""
        if m["new_chat_member"]["status"] != "administrator" or m["chat"]["type"] == "private":
            return
        for admin in self.cfg.admins:
            try:
                self.send(admin, f"Бот «{m['chat'].get('title', '')}» чатына әкімші болып қосылды.\nCHANNEL_ID={m['chat']['id']}")
            except ApiError as e:
                log.warning("Әкімшіге хабар жетпеді: %s", e)

    # ---------- цикл ----------

    def run(self):
        me = self.api.call("getMe")
        log.info("Бот іске қосылды: @%s", me["username"])
        offset = 0
        while True:
            try:
                updates = self.api.call("getUpdates", offset=offset, timeout=50,
                                        allowed_updates=["message", "callback_query", "my_chat_member"])
            except ApiError as e:
                log.warning("getUpdates: %s", e)
                time.sleep(5)
                continue
            for u in updates:
                offset = u["update_id"] + 1
                try:
                    self.handle(u)
                except Exception:  # бір қате хабар бүкіл ботты тоқтатпауы керек
                    log.exception("Өңделмеген қате")


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    load_env(HERE / ".env")
    cfg = Config(os.environ)
    if cfg.problems():
        raise SystemExit("Баптау толық емес: " + "; ".join(cfg.problems()) + ". .env.example қараңыз.")
    if not cfg.channel:
        log.warning("CHANNEL_ID бос: ботты арнаға әкімші етіп қосыңыз — ID-ді өзі жібереді.")
    Bot(cfg, Api(cfg.token), Orders(cfg.db_path)).run()


if __name__ == "__main__":
    main()
