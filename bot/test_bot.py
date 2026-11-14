"""python3 bot/test_bot.py — Telegram-сыз, жалған API-мен тексеру."""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import bot as botmod  # noqa: E402

ADMIN, BUYER, CHANNEL = 1, 500, "-100123"


class FakeApi:
    def __init__(self):
        self.calls, self.fail = [], set()

    def call(self, method, **params):
        self.calls.append((method, params))
        if method in self.fail:
            raise botmod.ApiError(f"{method}: failed")
        if method == "createChatInviteLink":
            return {"invite_link": "https://t.me/+invite"}
        return {}

    def sent(self, chat_id):
        return [p for m, p in self.calls if m == "sendMessage" and p["chat_id"] == chat_id]

    def methods(self):
        return [m for m, _ in self.calls]


def message(user_id, text=None, **extra):
    msg = {"message_id": 7, "chat": {"id": user_id, "type": "private"},
           "from": {"id": user_id, "first_name": "Айша", "username": "aisha"}}
    if text is not None:
        msg["text"] = text
    msg.update(extra)
    return {"message": msg}


def callback(user_id, data):
    return {"callback_query": {"id": "c1", "data": data, "from": {"id": user_id, "first_name": "Админ"},
                               "message": {"message_id": 9, "chat": {"id": user_id}, "caption": "Жаңа чек"}}}


class BotTest(unittest.TestCase):
    def setUp(self):
        cfg = botmod.Config({"BOT_TOKEN": "t", "ADMIN_IDS": str(ADMIN), "CHANNEL_ID": CHANNEL, "PRICE": "9900",
                             "PRODUCT_NAME": "Курс", "KASPI_PHONE": "+7 700", "PROMOS": "START:7900",
                             "DB_PATH": ":memory:"})
        self.api = FakeApi()
        self.orders = botmod.Orders(cfg.db_path)
        self.bot = botmod.Bot(cfg, self.api, self.orders)

    def status(self):
        return self.orders.get(BUYER)["status"]

    def to_review(self):
        self.bot.handle(message(BUYER, "/start buy"))
        self.bot.handle(callback(BUYER, "pay"))
        self.bot.handle(message(BUYER, photo=[{"file_id": "f"}]))

    def test_full_purchase(self):
        self.bot.handle(message(BUYER, "/start buy"))
        self.assertIn("9 900 ₸", self.api.sent(BUYER)[0]["text"])
        self.bot.handle(callback(BUYER, "pay"))
        self.assertIn("+7 700", self.api.sent(BUYER)[1]["text"])
        self.assertEqual(self.status(), "awaiting")

        self.bot.handle(message(BUYER, photo=[{"file_id": "f"}]))
        copy = [p for m, p in self.api.calls if m == "copyMessage"][0]
        self.assertEqual(copy["chat_id"], ADMIN)
        self.assertIn("@aisha", copy["caption"])
        self.assertEqual(self.status(), "review")

        self.bot.handle(callback(ADMIN, f"ok:{BUYER}"))
        self.assertEqual(self.status(), "paid")
        invite = [p for m, p in self.api.calls if m == "createChatInviteLink"][0]
        self.assertEqual((invite["chat_id"], invite["member_limit"]), (CHANNEL, 1))
        button = self.api.sent(BUYER)[-1]["reply_markup"]["inline_keyboard"][0][0]
        self.assertEqual(button["url"], "https://t.me/+invite")

    def test_promo(self):
        self.bot.handle(message(BUYER, "/start promo_start"))
        self.assertEqual(self.orders.get(BUYER)["price"], 7900)
        self.assertIn("7 900 ₸", self.api.sent(BUYER)[0]["reply_markup"]["inline_keyboard"][0][0]["text"])
        self.bot.handle(message(BUYER, "/start"))  # қайта кіргенде жеңілдік сақталады
        self.assertEqual(self.orders.get(BUYER)["price"], 7900)

    def test_unknown_promo_keeps_price(self):
        self.bot.handle(message(BUYER, "/start promo_NOPE"))
        self.assertEqual(self.orders.get(BUYER)["price"], 9900)
        self.assertIn("табылмады", self.api.sent(BUYER)[0]["text"])

    def test_receipt_before_pay_is_not_forwarded(self):
        self.bot.handle(message(BUYER, document={"file_id": "f"}))
        self.assertNotIn("copyMessage", self.api.methods())

    def test_stranger_cannot_approve(self):
        self.to_review()
        self.bot.handle(callback(BUYER, f"ok:{BUYER}"))
        self.assertEqual(self.status(), "review")
        self.assertNotIn("createChatInviteLink", self.api.methods())

    def test_reject_lets_buyer_resend(self):
        self.to_review()
        self.bot.handle(callback(ADMIN, f"no:{BUYER}"))
        self.assertEqual(self.status(), "awaiting")
        self.bot.handle(message(BUYER, photo=[{"file_id": "f2"}]))
        self.assertEqual(self.status(), "review")

    def test_double_approve_sends_one_link(self):
        self.to_review()
        self.bot.handle(callback(ADMIN, f"ok:{BUYER}"))
        self.bot.handle(callback(ADMIN, f"ok:{BUYER}"))
        self.assertEqual(self.api.methods().count("createChatInviteLink"), 1)

    def test_invite_failure_keeps_order_in_review(self):
        self.to_review()
        self.api.fail.add("createChatInviteLink")
        self.bot.handle(callback(ADMIN, f"ok:{BUYER}"))
        self.assertEqual(self.status(), "review")
        answer = [p for m, p in self.api.calls if m == "answerCallbackQuery"][-1]
        self.assertTrue(answer["show_alert"])

    def test_undelivered_receipt_can_be_resent(self):
        self.bot.handle(message(BUYER, "/start"))
        self.bot.handle(callback(BUYER, "pay"))
        self.api.fail.add("copyMessage")
        self.bot.handle(message(BUYER, photo=[{"file_id": "f"}]))
        self.assertEqual(self.status(), "awaiting")

    def test_paid_buyer_gets_fresh_link_on_start(self):
        self.to_review()
        self.bot.handle(callback(ADMIN, f"ok:{BUYER}"))
        self.bot.handle(message(BUYER, "/start buy"))
        self.assertEqual(self.api.methods().count("createChatInviteLink"), 2)
        self.assertEqual(self.status(), "paid")

    def test_channel_id_is_reported_to_admin(self):
        self.bot.handle({"my_chat_member": {"chat": {"id": -100777, "type": "channel", "title": "Курс"},
                                            "new_chat_member": {"status": "administrator"}}})
        self.assertIn("CHANNEL_ID=-100777", self.api.sent(ADMIN)[0]["text"])


if __name__ == "__main__":
    unittest.main()
