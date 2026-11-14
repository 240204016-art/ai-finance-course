/**
 * Сату боты — Google Apps Script нұсқасы (тегін, тәулік бойы жұмыс істейді).
 * Kaspi төлемі чек арқылы расталады, содан соң бот жабық Telegram-арнаға
 * бір реттік сілтеме береді. Тапсырыстар осы Google кестеге жазылады.
 *
 * Орнату нұсқаулығы: README.md (осы папкада).
 */

// ====== БАПТАУЛАР: тек осы бөлімді толтырыңыз ======
var CONFIG = {
  BOT_TOKEN: "",                 // @BotFather берген токен
  ADMIN_IDS: [],                 // чек растайтын адамдардың ID-і, мысалы [123456789]
  CHANNEL_ID: "",                // жабық арна ID-і, мысалы "-1001234567890" (бот өзі жібереді)

  PRODUCT_NAME: "Курс атауы",
  PRICE: 9900,                   // ₸, лендингтегі бағамен бірдей болсын

  KASPI_PHONE: "+7 700 000 00 00",
  KASPI_NAME: "Аты Т.",
  KASPI_PAY_URL: "",             // Kaspi Pay сілтемесі болса (міндетті емес)

  OFERTA_URL: "https://240204016-art.github.io/ai-finance-course/landing/oferta.html",
  SUPPORT: "",                   // сұрақтарға жауап беретін аккаунт, @ белгісінсіз (міндетті емес)
  PROMOS: {},                    // промокодтар: { "START": 7900, "DOS": 8900 }

  WEBAPP_URL: "",                // Deploy жасағанда шыққан .../exec сілтемесі
  SECRET: ""                     // кез келген ұзын құпия сөз (латын әріптері мен цифрлар), бөтен сұраныстардан қорғайды
};
// ====================================================

var SHEET_NAME = "Тапсырыстар";
var COLUMNS = ["user_id", "username", "name", "price", "promo", "status", "updated"];

/** 1-рет қолмен іске қосылады: Telegram-ға хабарларды осы скриптке жіберуді айтады. */
function setWebhook() {
  var missing = ["BOT_TOKEN", "WEBAPP_URL", "SECRET"].filter(function (k) { return !CONFIG[k]; });
  if (!CONFIG.ADMIN_IDS.length) missing.push("ADMIN_IDS");
  if (missing.length) throw new Error("CONFIG толық емес: " + missing.join(", "));
  getSheet();
  api("setWebhook", {
    url: CONFIG.WEBAPP_URL + "?key=" + encodeURIComponent(CONFIG.SECRET),
    allowed_updates: ["message", "callback_query", "my_chat_member"],
    drop_pending_updates: true
  });
  console.log("Дайын. Бот: @" + api("getMe", {}).username);
}

/** Тексеру үшін: соңғы қате болса, журналға шығарады. */
function checkWebhook() {
  console.log(JSON.stringify(api("getWebhookInfo", {}), null, 2));
}

function doPost(e) {
  try {
    if (!CONFIG.SECRET || e.parameter.key !== CONFIG.SECRET) return done();
    var update = JSON.parse(e.postData.contents);
    var cache = CacheService.getScriptCache(), seen = "u" + update.update_id;
    if (cache.get(seen)) return done();          // Telegram бір хабарды қайталап жіберсе, екі рет өңдемейміз
    cache.put(seen, "1", 21600);
    var lock = LockService.getScriptLock();
    lock.waitLock(25000);
    try { handle(update); } finally { lock.releaseLock(); }
  } catch (err) {
    console.error(err && err.stack || err);
  }
  return done();
}

// ContentService жауабы Telegram түсінбейтін 302-мен қайтады, сондықтан HtmlService қолданылады.
function done() { return HtmlService.createHtmlOutput("ok"); }

function api(method, params) {
  var res = UrlFetchApp.fetch("https://api.telegram.org/bot" + CONFIG.BOT_TOKEN + "/" + method, {
    method: "post", contentType: "application/json", payload: JSON.stringify(params), muteHttpExceptions: true
  });
  var body = JSON.parse(res.getContentText());
  if (!body.ok) throw new Error(method + ": " + body.description);
  return body.result;
}

function send(chatId, text, markup) {
  var p = { chat_id: chatId, text: text, disable_web_page_preview: true };
  if (markup) p.reply_markup = markup;
  return api("sendMessage", p);
}

function kb(rows) { return { inline_keyboard: rows }; }
function money(n) { return String(n).replace(/\B(?=(\d{3})+$)/g, " ") + " ₸"; }
function isAdmin(id) { return CONFIG.ADMIN_IDS.map(String).indexOf(String(id)) !== -1; }
function supportLine() { return CONFIG.SUPPORT ? "\n\nСұрақ болса: @" + CONFIG.SUPPORT : ""; }

// ---------- тапсырыстар (Google кесте) ----------
// status: new → awaiting → review → paid

function getSheet() {
  var ss = SpreadsheetApp.getActiveSpreadsheet(), sh = ss.getSheetByName(SHEET_NAME);
  if (!sh) { sh = ss.insertSheet(SHEET_NAME); sh.appendRow(COLUMNS); sh.setFrozenRows(1); }
  return sh;
}

function getOrder(userId) {
  var rows = getSheet().getDataRange().getValues();
  for (var i = 1; i < rows.length; i++) {
    if (String(rows[i][0]) === String(userId)) {
      var o = { row: i + 1 };
      COLUMNS.forEach(function (c, j) { o[c] = rows[i][j]; });
      return o;
    }
  }
  return null;
}

function saveOrder(userId, fields, user) {
  var o = getOrder(userId) || { user_id: userId, username: "", name: "", price: CONFIG.PRICE, promo: "", status: "new" };
  for (var k in fields) o[k] = fields[k];
  if (user) {
    o.username = user.username || "";
    o.name = [user.first_name, user.last_name].filter(Boolean).join(" ");
  }
  o.updated = new Date();
  var values = COLUMNS.map(function (c) { return c === "user_id" ? String(o[c]) : o[c]; });
  if (o.row) getSheet().getRange(o.row, 1, 1, COLUMNS.length).setValues([values]);
  else getSheet().appendRow(values);
}

// ---------- кіріс ----------

function handle(update) {
  if (update.message) onMessage(update.message);
  else if (update.callback_query) onCallback(update.callback_query);
  else if (update.my_chat_member) onMembership(update.my_chat_member);
}

function onMessage(msg) {
  if (msg.chat.type !== "private" || !msg.from) return;
  var user = msg.from, text = msg.text || "";
  if (text.indexOf("/start") === 0) start(user, text.slice(6).trim());
  else if (text.indexOf("/id") === 0) send(user.id, "Сіздің ID: " + user.id);
  else if (text.indexOf("/stats") === 0 && isAdmin(user.id)) stats(user.id);
  else if (msg.photo || msg.document) receipt(user, msg);
  else send(user.id, "Сатып алу үшін /start басыңыз. Төлеп қойсаңыз, чекті (скриншот не PDF) осы чатқа жіберіңіз." + supportLine());
}

// ---------- сатып алушы ----------

var IN_REVIEW = "Чегіңіз тексеріліп жатыр. Расталған соң сілтеме осы чатқа келеді.";

function start(user, payload) {
  var order = getOrder(user.id);
  if (order && order.status === "paid") return grant(user.id, true);
  if (order && order.status === "review") return send(user.id, IN_REVIEW);

  var price = CONFIG.PRICE, promo = "", extra = "";
  if (payload.indexOf("promo_") === 0) {
    var code = payload.slice(6).toUpperCase();
    if (CONFIG.PROMOS.hasOwnProperty(code)) {
      price = CONFIG.PROMOS[code]; promo = code;
      extra = "\n\nПромокод " + code + " қолданылды: " + money(CONFIG.PRICE) + " → " + money(price) + ".";
    } else {
      extra = "\n\nПромокод " + code + " табылмады, баға өзгерген жоқ.";
    }
  } else if (order && order.promo && CONFIG.PROMOS.hasOwnProperty(order.promo)) {
    price = CONFIG.PROMOS[order.promo]; promo = order.promo;   // бұрын қолданылған промокод сақталады
  }
  saveOrder(user.id, { price: price, promo: promo, status: "new" }, user);

  var rows = [[{ text: "Офертамен келісемін, төлеу · " + money(price), callback_data: "pay" }]];
  if (CONFIG.OFERTA_URL) rows.push([{ text: "Офертаны оқу", url: CONFIG.OFERTA_URL }]);
  send(user.id,
    "Сәлем! Сіз «" + CONFIG.PRODUCT_NAME + "» пакетін таңдадыңыз: " + money(price) + "." + extra + "\n\n" +
    "Төлем Kaspi арқылы. Төлегеннен кейін жабық арнаға кіру сілтемесі осы чатқа келеді.\n\n" +
    "Төлем батырмасын басу арқылы жария оферта шарттарын қабылдайсыз.", kb(rows));
}

function pay(user) {
  var order = getOrder(user.id);
  if (!order) return start(user, "");
  if (order.status === "paid") return grant(user.id, true);
  if (order.status === "review") return send(user.id, IN_REVIEW);
  saveOrder(user.id, { status: "awaiting" });

  var lines = ["«" + CONFIG.PRODUCT_NAME + "»: " + money(order.price), ""];
  if (CONFIG.KASPI_PHONE) {
    lines.push("Kaspi аударым: " + CONFIG.KASPI_PHONE);
    if (CONFIG.KASPI_NAME) lines.push("Алушы: " + CONFIG.KASPI_NAME);
    lines.push("");
  }
  if (CONFIG.KASPI_PAY_URL) lines.push("Төмендегі батырма арқылы да төлеуге болады.", "");
  lines.push("Дәл " + money(order.price) + " аударып, чекті (скриншот не PDF) осы чатқа жіберіңіз. Тексерілген соң арнаға сілтеме келеді.");
  send(user.id, lines.join("\n"), CONFIG.KASPI_PAY_URL ? kb([[{ text: "Kaspi-де төлеу", url: CONFIG.KASPI_PAY_URL }]]) : null);
}

function receipt(user, msg) {
  var order = getOrder(user.id);
  if (!order || order.status === "new") return send(user.id, "Алдымен /start басып, төлем деректерін алыңыз.");
  if (order.status === "paid") return grant(user.id, true);
  if (order.status === "review") return send(user.id, "Чегіңіз тексеріліп жатыр, сәл күте тұрыңыз.");

  saveOrder(user.id, { status: "review" }, user);
  var name = [user.first_name, user.last_name].filter(Boolean).join(" ");
  var caption = "Жаңа чек\n" + name + (user.username ? " (@" + user.username + ")" : "") + "\nID: " + user.id +
    "\nСома: " + money(order.price) + (order.promo ? "\nПромокод: " + order.promo : "");
  var markup = kb([[{ text: "✅ Растау", callback_data: "ok:" + user.id }, { text: "❌ Қабылдамау", callback_data: "no:" + user.id }]]);
  var delivered = 0;
  CONFIG.ADMIN_IDS.forEach(function (admin) {
    try {
      api("copyMessage", { chat_id: admin, from_chat_id: msg.chat.id, message_id: msg.message_id, caption: caption, reply_markup: markup });
      delivered++;
    } catch (err) { console.error("Чек " + admin + " әкімшісіне жетпеді: " + err.message); }
  });
  if (!delivered) {   // ешбір әкімшіге жетпесе, чекті қайта жіберуге мүмкіндік қалады
    saveOrder(user.id, { status: "awaiting" });
    return send(user.id, "Чекті қабылдау кезінде қате шықты. Сәл кейінірек қайта жіберіңіз." + supportLine());
  }
  send(user.id, "Чек қабылданды ✅ Тексерілген соң арнаға сілтеме осы чатқа келеді.");
}

/** Арнаға бір адамға ғана жарайтын сілтеме жасап, сатып алушыға жібереді. */
function grant(userId, again) {
  var link = api("createChatInviteLink", { chat_id: CONFIG.CHANNEL_ID, member_limit: 1, name: "user " + userId }).invite_link;
  var text = again ? "Сіз бұл пакетті сатып алғансыз. Міне, арнаға жаңа сілтеме:"
                   : "Төлем расталды 🎉 «" + CONFIG.PRODUCT_NAME + "» арнасына қош келдіңіз!";
  send(userId, text + "\n\nСілтеме бір рет қана жарайды, оны ешкімге бермеңіз.", kb([[{ text: "Арнаға кіру", url: link }]]));
}

// ---------- әкімші ----------

function onCallback(cq) {
  var data = cq.data || "", answer = { text: "", alert: false };
  try {
    if (data === "pay") pay(cq.from);
    else if (/^(ok|no):\d+$/.test(data)) answer = decide(cq, data.slice(0, 2) === "ok", data.slice(3));
  } catch (err) {
    console.error(err && err.stack || err);
    answer = { text: "Қате: " + err.message, alert: true };
  }
  api("answerCallbackQuery", { callback_query_id: cq.id, text: answer.text.slice(0, 200), show_alert: answer.alert });
}

function decide(cq, approve, buyerId) {
  if (!isAdmin(cq.from.id)) return { text: "Бұл батырма тек әкімшіге арналған.", alert: true };
  var order = getOrder(buyerId);
  if (!order || order.status !== "review") {
    var verdict = order && order.status === "paid" ? "расталған" : order && order.status === "awaiting" ? "қабылданбаған" : "шешілген";
    closeAdminMessage(cq, "Бұрын " + verdict);
    return { text: "Бұл чек бұрын " + verdict + ".", alert: true };
  }
  if (approve) {
    if (!CONFIG.CHANNEL_ID) return { text: "CHANNEL_ID бапталмаған — CONFIG ішіне жазыңыз.", alert: true };
    grant(buyerId, false);   // сілтеме жасалмаса (бот арна әкімшісі емес), статус өзгермейді
    saveOrder(buyerId, { status: "paid" });
    closeAdminMessage(cq, "✅ Расталды");
    return { text: "Расталды, сілтеме жіберілді.", alert: false };
  }
  saveOrder(buyerId, { status: "awaiting" });
  closeAdminMessage(cq, "❌ Қабылданбады");
  send(buyerId, "Төлем расталмады 😕 Сома мен алушыны тексеріп, дұрыс чекті осы чатқа қайта жіберіңіз." + supportLine());
  return { text: "Қабылданбады, сатып алушыға хабарланды.", alert: false };
}

function closeAdminMessage(cq, verdict) {
  if (!cq.message) return;
  try {
    api("editMessageCaption", { chat_id: cq.message.chat.id, message_id: cq.message.message_id,
      caption: (cq.message.caption || "") + "\n\n" + verdict + " · " + (cq.from.first_name || "") });
  } catch (err) { console.warn("Әкімші хабары жаңартылмады: " + err.message); }
}

function stats(chatId) {
  var rows = getSheet().getDataRange().getValues().slice(1), n = {}, revenue = 0;
  rows.forEach(function (r) { n[r[5]] = (n[r[5]] || 0) + 1; if (r[5] === "paid") revenue += Number(r[3]) || 0; });
  send(chatId, "Төленген: " + (n.paid || 0) + "\nТексеруде: " + (n.review || 0) + "\nЧек күтілуде: " + (n.awaiting || 0) +
    "\nТек /start басқан: " + (n["new"] || 0) + "\n\nТүсім: " + money(revenue));
}

/** Бот арнаға әкімші болып қосылғанда арна ID-ін әкімшілерге жібереді — CHANNEL_ID үшін. */
function onMembership(m) {
  if (m.new_chat_member.status !== "administrator" || m.chat.type === "private") return;
  CONFIG.ADMIN_IDS.forEach(function (admin) {
    try { send(admin, "Бот «" + (m.chat.title || "") + "» чатына әкімші болып қосылды.\nCHANNEL_ID: " + m.chat.id); }
    catch (err) { console.warn("Әкімшіге хабар жетпеді: " + err.message); }
  });
}
