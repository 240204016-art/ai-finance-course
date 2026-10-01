/**
 * Биология ҰБТ тесті — нәтижелерді жинайтын Google Apps Script.
 *
 * ОРНАТУ
 * ------
 * 1. Кестені ашып, Extensions → Apps Script.
 * 2. Редактордағы бар кодты ТҮГЕЛ өшіріп (Ctrl+A → Delete), осыны қойыңыз.
 *    Кодты `function myFunction() { ... }` ішіне САЛМАҢЫЗ — Apps Script
 *    doGet пен doPost-ты тек сыртқы деңгейден іздейді.
 * 3. SECRET_KEY мен SHEET_ID мәндерін толтырыңыз.
 * 4. Deploy → New deployment → Web app.
 *      Execute as:      Me
 *      Who has access:  Anyone            ← міндетті түрде осылай
 * 5. Жоғарыдағы тізімнен `setup` таңдап, ▶ Run басыңыз. Рұқсат сұрайды:
 *    Authorize access → аккаунт → «Google hasn't verified this app» бетінде
 *    Advanced → Go to ... (unsafe) → Allow.
 * 6. Мекенжайды config.json ішіндегі "submitUrl" өрісіне қойыңыз.
 *
 * Кодты кейін өзгертсеңіз: Deploy → Manage deployments → ✏️ →
 * Version: New version → Deploy. Сонда мекенжай өзгермейді.
 *
 * ТЕКСЕРУ: мекенжайдың соңына ?key=ҚҰПИЯ-СӨЗ қосып браузерде ашыңыз.
 * {"ok":true,"rows":[]} көрінсе — бәрі дұрыс.
 *
 * ҚАЛАЙ ЖҰМЫС ІСТЕЙДІ (кіру)
 * --------------------------
 * Растау коды ЖОҚ. Оқушы email-ін, тегін, есімін, сыныбын жазып
 * «кіруді сұрайды» — сұраныс «Кіру» парағына «күтуде» деп түседі.
 * Сіз дашбордтағы «Кіру сұраныстары» бөлімінен «Рұқсат» түймесін
 * басасыз, оқушының беті мұны өзі байқап, тест ашылады.
 *
 * Рұқсат сұраған ҚҰРЫЛҒЫҒА беріледі. Оқушы сілтемесін достарына
 * таратса, олардың браузері жаңа сұраныс жасайды да, сізден рұқсат
 * күтеді — сіз көріп тұрасыз.
 *
 * ПАРАҚТАР (өздері жасалады)
 * --------------------------
 *   Нәтижелер — тапсырылған жұмыстар
 *   Кіру      — кіру сұраныстары мен сеанс токендері
 *   Рұқсат    — МІНДЕТТІ ЕМЕС. Бір бағанға email тізімін жазсаңыз,
 *               сол адамдар сұраныс жасаған бойда АВТОМАТТЫ рұқсат
 *               алады (сіз түймені баспайсыз). Бос болса — бәрі
 *               сіздің рұқсатыңызды күтеді.
 */

var SECRET_KEY = 'ӨЗІҢІЗДІҢ-ҚҰПИЯ-СӨЗІҢІЗ';

/** Кестенің мекенжайынан: docs.google.com/spreadsheets/d/ОСЫ_ЖЕР/edit */
var SHEET_ID = '';

/**
 * МІНДЕТТІ ЕМЕС. Мұнда email жазсаңыз, әр жаңа кіру сұранысы туралы
 * сол адреске хабарлама келеді. Бос қалдырсаңыз — хат жіберілмейді,
 * сұраныстарды тек дашбордтан көресіз.
 */
var NOTIFY_EMAIL = '';

var SHEET_NAME  = 'Нәтижелер';
var ACCESS_NAME = 'Кіру';
var ALLOW_NAME  = 'Рұқсат';

var TOKEN_TTL_HRS = 12;    /* рұқсат берілген соң қанша сағат жарамды */

var HEADERS = [
  'Уақыты', 'Email', 'Тегі', 'Есімі', 'Сынып/топ', 'Тест', 'Нұсқа коды', 'Әрекет',
  'Балл', 'Макс', 'Пайыз', 'Уақыты (сек)', 'Режим', 'Араластыру',
  'Белгілер', 'Жауаптар', 'ID'
];
/* Мерзімдер сан (ms) болып сақталады — себебі ms_() түсіндірмесінде. */
var ACC_HEADERS = ['Email', 'Тегі', 'Есімі', 'Сынып/топ', 'Сұралған',
                   'Күйі', 'Құрылғы', 'Токен', 'Токен жарамды дейін', 'Шешім'];

var A_EMAIL = 0, A_LAST = 1, A_FIRST = 2, A_GROUP = 3, A_ASKED = 4,
    A_STATE = 5, A_DEV = 6, A_TOKEN = 7, A_UNTIL = 8, A_DECIDED = 9;

var ST_WAIT = 'күтуде';
var ST_OK   = 'рұқсат';
var ST_NO   = 'бас тартылды';

/**
 * БІР РЕТ ІСКЕ ҚОСЫҢЫЗ: жоғарыдағы тізімнен `setup` таңдап, ▶ Run басыңыз.
 *
 * Не істейді:
 *   - Google-ден қажетті рұқсаттарды сұрайды
 *   - парақтарды жасайды
 *   - Execution log ішінде бәрі дұрыс па, соны жазады
 */
function setup() {
  var me = Session.getEffectiveUser().getEmail();
  Logger.log('Аккаунт: ' + me);

  if (!SECRET_KEY || SECRET_KEY.indexOf('ӨЗІҢІЗДІҢ') === 0) {
    throw new Error('SECRET_KEY толтырылмаған.');
  }
  Logger.log('SECRET_KEY: жазылған');

  var ss = book_();
  Logger.log('Кесте: ' + ss.getName());

  migrate_(tab_(SHEET_NAME, HEADERS), HEADERS, SHEET_NAME);
  migrate_(tab_(ACCESS_NAME, ACC_HEADERS), ACC_HEADERS, ACCESS_NAME);
  Logger.log('Парақтар дайын: ' + SHEET_NAME + ', ' + ACCESS_NAME);

  if (NOTIFY_EMAIL) {
    MailApp.sendEmail({
      to: NOTIFY_EMAIL,
      subject: 'Биология тесті — скрипт дұрыс орнатылды',
      body: 'Бұл — сынақ хат. Енді әр кіру сұранысы туралы осы адреске хабар келеді.'
    });
    Logger.log('Сынақ хат жіберілді: ' + NOTIFY_EMAIL);
  } else {
    Logger.log('NOTIFY_EMAIL бос — хат жіберілмейді, сұраныстар тек дашбордта көрінеді.');
  }
  Logger.log('БӘРІ ДАЙЫН. Енді Deploy → Manage deployments → ✏️ → New version → Deploy.');
}

/**
 * Парақтың бағандарын АТАУЫ бойынша табады.
 *
 * Бағандардың реті уақыт өте өзгерді («Аты-жөні» орнына «Тегі» мен
 * «Есімі» келді, «Email» мен «Әрекет» қосылды). Нөмір бойынша оқысақ,
 * ескі жазбалар жылжып кетеді — аты email бағанына, сыныбы тегі
 * бағанына түседі. Сондықтан бәрі атау арқылы табылады.
 */
function colMap_(sh) {
  var lastCol = sh.getLastColumn();
  if (sh.getLastRow() === 0 || lastCol === 0) { return { names: [], index: {} }; }
  var names = sh.getRange(1, 1, 1, lastCol).getValues()[0].map(function (v) {
    return String(v).trim();
  });
  var index = {};
  names.forEach(function (n, i) { if (n) { index[n] = i; } });
  return { names: names, index: index };
}

/** Бағандар өзгерсе, бос парақтың тақырыптарын жаңартады. */
function migrate_(sh, headers, name) {
  var last = sh.getLastRow();
  if (last > 1) {
    var have = sh.getRange(1, 1, 1, sh.getLastColumn()).getValues()[0].join('|');
    if (have !== headers.join('|')) {
      Logger.log('НАЗАР: «' + name + '» парағында ескі бағандар мен дерек бар. ' +
                 'Ескісін сақтап, парақтың атын өзгертіп, жаңасын жасатыңыз.');
    }
    return;
  }
  sh.getRange(1, 1, 1, Math.max(headers.length, sh.getLastColumn() || 1)).clearContent();
  sh.getRange(1, 1, 1, headers.length).setValues([headers]).setFontWeight('bold');
  Logger.log('«' + name + '» бағандары жаңартылды.');
}

/* ---------- көмекші ---------- */

function book_() {
  var ss = SHEET_ID ? SpreadsheetApp.openById(SHEET_ID)
                    : SpreadsheetApp.getActiveSpreadsheet();
  if (!ss) {
    throw new Error('Кесте табылмады. SHEET_ID жазыңыз немесе скриптті ' +
                    'кестенің ішінен (Extensions → Apps Script) ашыңыз.');
  }
  return ss;
}

function tab_(name, headers) {
  var ss = book_();
  var sh = ss.getSheetByName(name);
  if (!sh) { sh = ss.insertSheet(name); }
  if (sh.getLastRow() === 0 && headers) {
    sh.appendRow(headers);
    sh.getRange(1, 1, 1, headers.length).setFontWeight('bold');
    sh.setFrozenRows(1);
  }
  return sh;
}

function json_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}

function norm_(email) { return String(email || '').trim().toLowerCase(); }

function trim_(v, n) { return String(v || '').trim().slice(0, n || 60); }

/**
 * Уақытты санға айналдырады.
 *
 * Уақытты кестеге Date етіп жазсақ, Apps Script оны кестенің уақыт
 * белдеуімен сақтайды да, кері оқығанда жоба белдеуімен түсіндіреді.
 * Екеуі әртүрлі болса, мән сағаттарға жылжып, мерзім бірден «өтіп»
 * қалады. Сондықтан мерзімдер таза сан (ms) болып жазылады —
 * белдеуге тәуелсіз. Ескі жазбалардағы Date те оқылады.
 */
function ms_(v) {
  if (v instanceof Date) { return v.getTime(); }
  var n = Number(v);
  return isNaN(n) ? 0 : n;
}

function valid_(email) { return /^[^@\s]+@[^@\s.]+\.[^@\s]+$/.test(email); }

/**
 * «Рұқсат» парағы — АВТОМАТТЫ рұқсат тізімі.
 *
 * Бұрын бұл парақ «кіруге болатындар» тізімі еді. Енді кіруді мұғалім
 * бекітетіндіктен, бұл тізім — «бекітуді күтпей-ақ өте берсін»
 * дегендер. Бос болса (әдеттегі жағдай) — бәрі рұқсат күтеді.
 */
function autoOk_(email) {
  var ss = book_();
  var sh = ss.getSheetByName(ALLOW_NAME);
  if (!sh || sh.getLastRow() === 0) { return false; }
  var vals = sh.getDataRange().getValues();
  for (var i = 0; i < vals.length; i++) {
    for (var j = 0; j < vals[i].length; j++) {
      if (norm_(vals[i][j]) === email) { return true; }
    }
  }
  return false;
}

/** Кіру парағынан email жолын табады. */
function accRow_(email) {
  var sh = tab_(ACCESS_NAME, ACC_HEADERS);
  var last = sh.getLastRow();
  if (last < 2) { return { sheet: sh, row: 0, data: null }; }
  var vals = sh.getRange(2, 1, last - 1, ACC_HEADERS.length).getValues();
  for (var i = 0; i < vals.length; i++) {
    if (norm_(vals[i][A_EMAIL]) === email) {
      return { sheet: sh, row: i + 2, data: vals[i] };
    }
  }
  return { sheet: sh, row: 0, data: null };
}

function accWrite_(hit, data) {
  if (hit.row) {
    hit.sheet.getRange(hit.row, 1, 1, ACC_HEADERS.length).setValues([data]);
  } else {
    hit.sheet.appendRow(data);
    hit.row = hit.sheet.getLastRow();
  }
  hit.data = data;
  return hit;
}

/** Жолдағы рұқсат әлі жарамды ма. */
function live_(d) {
  return !!(d && String(d[A_STATE]) === ST_OK && d[A_TOKEN] &&
            ms_(d[A_UNTIL]) > Date.now());
}

/* ---------- 1. кіруді сұрау ---------- */

function request_(p) {
  var email = norm_(p.email);
  var last  = trim_(p.last);
  var first = trim_(p.first);
  var group = trim_(p.group);
  var dev   = trim_(p.device, 80);

  if (!valid_(email)) { return json_({ ok: false, error: 'Email дұрыс жазылмаған.' }); }
  if (last.length < 2 || first.length < 2 || !group) {
    return json_({ ok: false, error: 'Тегі, есімі және сыныбы толтырылуы керек.' });
  }
  if (!dev) { return json_({ ok: false, error: 'Құрылғы анықталмады. Бетті жаңартыңыз.' }); }

  var lock = LockService.getScriptLock();
  try { lock.waitLock(10000); } catch (e) {
    return json_({ ok: false, error: 'Сервер бос емес, бірер секундтан кейін қайталаңыз.' });
  }

  var out, notify = false;
  try {
    var hit = accRow_(email);
    var now = Date.now();

    /* Сол құрылғыдан қайта келсе әрі рұқсаты жарамды болса — бірден кіргіземіз. */
    if (hit.row && live_(hit.data) && String(hit.data[A_DEV]) === dev) {
      accWrite_(hit, [email, last, first, group, hit.data[A_ASKED],
                      ST_OK, dev, hit.data[A_TOKEN], hit.data[A_UNTIL],
                      hit.data[A_DECIDED]]);
      out = { ok: true, status: ST_OK, token: String(hit.data[A_TOKEN]),
              email: email, last: last, first: first, group: group,
              hours: TOKEN_TTL_HRS };
    } else {
      var auto = autoOk_(email);
      var token = auto ? Utilities.getUuid() : '';
      var until = auto ? now + TOKEN_TTL_HRS * 3600000 : '';
      accWrite_(hit, [email, last, first, group, now,
                      auto ? ST_OK : ST_WAIT, dev, token, until,
                      auto ? now : '']);
      out = auto
        ? { ok: true, status: ST_OK, token: token, email: email,
            last: last, first: first, group: group, hours: TOKEN_TTL_HRS }
        : { ok: true, status: ST_WAIT, email: email };
      notify = !auto;
    }
  } finally {
    lock.releaseLock();
  }

  /* Хат жіберу бірнеше секунд алады — құлып босағаннан кейін ғана. */
  if (notify && NOTIFY_EMAIL) {
    try {
      MailApp.sendEmail({
        to: NOTIFY_EMAIL,
        subject: 'Тестке кіру сұранысы: ' + last + ' ' + first,
        body: last + ' ' + first + ' (' + group + ', ' + email + ') тестке кіргісі келеді.\n\n' +
              'Дашбордтағы «Кіру сұраныстары» бөлімінен рұқсат беріңіз.'
      });
    } catch (e) { /* хат кетпесе де сұраныс жазылып қойды */ }
  }

  return json_(out);
}

/* ---------- 2. рұқсатты күту ---------- */

function poll_(p) {
  var email = norm_(p.email);
  var dev   = trim_(p.device, 80);
  var hit = accRow_(email);
  if (!hit.row) { return json_({ ok: true, status: 'жоқ' }); }

  var d = hit.data;
  if (String(d[A_DEV]) !== dev) {
    /* Сұраныс басқа құрылғыдан жаңартылған: бұрынғы бет енді жарамайды. */
    return json_({ ok: true, status: 'басқа' });
  }
  if (String(d[A_STATE]) === ST_NO) { return json_({ ok: true, status: ST_NO }); }
  if (live_(d)) {
    return json_({ ok: true, status: ST_OK, token: String(d[A_TOKEN]), email: email,
                   last: String(d[A_LAST]), first: String(d[A_FIRST]),
                   group: String(d[A_GROUP]), hours: TOKEN_TTL_HRS });
  }
  if (String(d[A_STATE]) === ST_OK) {
    /* рұқсат берілген, бірақ мерзімі өткен */
    return json_({ ok: true, status: 'өтті' });
  }
  return json_({ ok: true, status: ST_WAIT });
}

/** Токен жарамды ма — иә болса Кіру парағындағы жолды қайтарады. */
function checkToken_(email, token) {
  if (!token) { return null; }
  var hit = accRow_(email);
  if (!hit.row || !live_(hit.data)) { return null; }
  if (String(hit.data[A_TOKEN]) !== String(token)) { return null; }
  return hit;
}

/* ---------- 3. мұғалімнің шешімі ---------- */

function accessList_() {
  var sh = tab_(ACCESS_NAME, ACC_HEADERS);
  var last = sh.getLastRow();
  if (last < 2) { return json_({ ok: true, list: [] }); }
  var vals = sh.getRange(2, 1, last - 1, ACC_HEADERS.length).getValues();
  var now = Date.now();
  var list = vals.map(function (d) {
    var state = String(d[A_STATE]) || ST_WAIT;
    if (state === ST_OK && !(d[A_TOKEN] && ms_(d[A_UNTIL]) > now)) { state = 'өтті'; }
    return {
      email: String(d[A_EMAIL]), last: String(d[A_LAST]), first: String(d[A_FIRST]),
      group: String(d[A_GROUP]), asked: ms_(d[A_ASKED]), state: state,
      decided: ms_(d[A_DECIDED]), until: ms_(d[A_UNTIL])
    };
  }).filter(function (x) { return !!x.email; });
  list.sort(function (a, b) { return b.asked - a.asked; });
  return json_({ ok: true, list: list });
}

function decide_(email, ok) {
  email = norm_(email);
  if (!email) { return json_({ ok: false, error: 'Email көрсетілмеген.' }); }
  var lock = LockService.getScriptLock();
  try { lock.waitLock(10000); } catch (e) {
    return json_({ ok: false, error: 'Сервер бос емес, қайталаңыз.' });
  }
  try {
    var hit = accRow_(email);
    if (!hit.row) { return json_({ ok: false, error: 'Мұндай сұраныс жоқ.' }); }
    var now = Date.now();
    var d = hit.data.slice();
    d[A_STATE]   = ok ? ST_OK : ST_NO;
    d[A_TOKEN]   = ok ? Utilities.getUuid() : '';
    d[A_UNTIL]   = ok ? now + TOKEN_TTL_HRS * 3600000 : '';
    d[A_DECIDED] = now;
    accWrite_(hit, d);
    return json_({ ok: true, email: email, state: d[A_STATE] });
  } finally {
    lock.releaseLock();
  }
}

/** Күтудегілердің бәріне бірден рұқсат — сабақ басында ыңғайлы. */
function approveAll_() {
  var lock = LockService.getScriptLock();
  try { lock.waitLock(20000); } catch (e) {
    return json_({ ok: false, error: 'Сервер бос емес, қайталаңыз.' });
  }
  try {
    var sh = tab_(ACCESS_NAME, ACC_HEADERS);
    var last = sh.getLastRow();
    if (last < 2) { return json_({ ok: true, count: 0 }); }
    var rng = sh.getRange(2, 1, last - 1, ACC_HEADERS.length);
    var vals = rng.getValues();
    var now = Date.now(), n = 0;
    for (var i = 0; i < vals.length; i++) {
      if (String(vals[i][A_STATE]) === ST_WAIT && vals[i][A_EMAIL]) {
        vals[i][A_STATE]   = ST_OK;
        vals[i][A_TOKEN]   = Utilities.getUuid();
        vals[i][A_UNTIL]   = now + TOKEN_TTL_HRS * 3600000;
        vals[i][A_DECIDED] = now;
        n++;
      }
    }
    if (n) { rng.setValues(vals); }
    return json_({ ok: true, count: n });
  } finally {
    lock.releaseLock();
  }
}

/* ---------- 4. нәтижені қабылдау ---------- */

function doPost(e) {
  try {
    var r = JSON.parse(e.postData.contents);
    var email = norm_(r.email);
    var hit = checkToken_(email, r.token);
    if (!hit) {
      return json_({ ok: false, error: 'Сеанс мерзімі өтті. Қайта кіру сұраңыз.',
                     needLogin: true });
    }
    /* Аты-жөнін оқушының жіберген дерегінен емес, мұғалім бекіткен
       жолдан аламыз — бекітілген соң басқа атпен тапсыра алмайды. */
    var last  = trim_(hit.data[A_LAST]);
    var first = trim_(hit.data[A_FIRST]);
    var group = trim_(hit.data[A_GROUP]);
    if (!last || !first || !group) {
      return json_({ ok: false, error: 'Тегі, есімі және сыныбы толтырылуы керек.' });
    }

    var sh = tab_(SHEET_NAME, HEADERS);
    var map = colMap_(sh);
    var lastRow = sh.getLastRow();          /* `last` — тегі, шатастырмау керек */

    /* Осы оқушының осы нұсқаны нешінші рет тапсырғаны. */
    var attempt = 1;
    var iEmail = map.index['Email'], iCode = map.index['Нұсқа коды'];
    if (lastRow > 1 && iEmail !== undefined && iCode !== undefined) {
      var prev = sh.getRange(2, 1, lastRow - 1, map.names.length).getValues();
      for (var i = 0; i < prev.length; i++) {
        if (norm_(prev[i][iEmail]) === email && String(prev[i][iCode]) === String(r.test)) {
          attempt++;
        }
      }
    }

    var id = Utilities.getUuid();
    var vals = {};
    vals['Уақыты']        = new Date();
    vals['Email']         = email;
    vals['Тегі']          = last;
    vals['Есімі']         = first;
    vals['Аты-жөні']      = (last + ' ' + first).trim();   /* ескі бағандағы парақ үшін */
    vals['Сынып/топ']     = group;
    vals['Тест']          = String(r.testTitle || '').slice(0, 60);
    vals['Нұсқа коды']    = String(r.test || '').slice(0, 40);
    vals['Әрекет']        = attempt;
    vals['Балл']          = Number(r.score) || 0;
    vals['Макс']          = Number(r.max) || 0;
    vals['Пайыз']         = Number(r.pct) || 0;
    vals['Уақыты (сек)']  = Number(r.seconds) || 0;
    vals['Режим']         = String(r.mode || '');
    vals['Араластыру']    = r.shuffled ? 'иә' : 'жоқ';
    vals['Белгілер']      = String(r.marks || '').slice(0, 300);
    vals['Жауаптар']      = String(r.picks || '').slice(0, 2000);
    vals['ID']            = id;

    sh.appendRow(map.names.map(function (n) {
      return vals[n] !== undefined ? vals[n] : '';
    }));
    return json_({ ok: true, id: id, attempt: attempt });
  } catch (err) {
    return json_({ ok: false, error: String(err) });
  }
}

/* ---------- 5. дашборд ---------- */

function doGet(e) {
  /* Қате ұсталмаса, Apps Script JSON емес HTML қате беті қайтарады да,
     бет «сервер күтпеген жауап қайтарды» деп қана айта алады. */
  try {
    return route_((e && e.parameter) ? e.parameter : {});
  } catch (err) {
    return json_({ ok: false,
                   error: 'Скрипт қатесі: ' + (err && err.message ? err.message : err) });
  }
}

function route_(p) {
  /* оқушыға ашық әрекеттер */
  if (p.action === 'request') { return request_(p); }
  if (p.action === 'poll')    { return poll_(p); }
  if (p.action === 'session') {
    var hit = checkToken_(norm_(p.email), p.token);
    return hit
      ? json_({ ok: true, email: norm_(p.email), last: String(hit.data[A_LAST]),
                first: String(hit.data[A_FIRST]), group: String(hit.data[A_GROUP]) })
      : json_({ ok: false, error: 'Сеанс мерзімі өтті.', needLogin: true });
  }

  /* бұдан әрі — тек мұғалім */
  if (p.key !== SECRET_KEY) { return json_({ ok: false, error: 'құпия сөз дұрыс емес' }); }

  if (p.action === 'access')     { return accessList_(); }
  if (p.action === 'approve')    { return decide_(p.email, true); }
  if (p.action === 'deny')       { return decide_(p.email, false); }
  if (p.action === 'approveAll') { return approveAll_(); }

  var sh = tab_(SHEET_NAME, HEADERS);
  var lastRow = sh.getLastRow();
  if (lastRow < 2) { return json_({ ok: true, rows: [] }); }
  var map = colMap_(sh);
  var values = sh.getRange(2, 1, lastRow - 1, map.names.length).getValues();

  function get(v, name) {
    var i = map.index[name];
    return i === undefined ? '' : v[i];
  }
  function num(v, name) {
    var n = Number(get(v, name));
    return isNaN(n) ? 0 : n;
  }

  var rows = values.map(function (v) {
    var lastN  = String(get(v, 'Тегі'));
    var firstN = String(get(v, 'Есімі'));
    var full   = (lastN + ' ' + firstN).trim();
    if (!full) {                       /* ескі парақта бір ғана «Аты-жөні» бағаны */
      full = String(get(v, 'Аты-жөні')).trim();
      var sp = full.indexOf(' ');
      lastN  = sp > 0 ? full.slice(0, sp) : full;
      firstN = sp > 0 ? full.slice(sp + 1) : '';
    }
    var at = get(v, 'Уақыты');
    return {
      at: at instanceof Date ? at.toISOString() : String(at),
      email: String(get(v, 'Email')),
      last: lastN, first: firstN, name: full,
      group: String(get(v, 'Сынып/топ')),
      testTitle: String(get(v, 'Тест')),
      test: String(get(v, 'Нұсқа коды')),
      attempt: num(v, 'Әрекет') || 1,
      score: num(v, 'Балл'), max: num(v, 'Макс'), pct: num(v, 'Пайыз'),
      seconds: num(v, 'Уақыты (сек)'),
      mode: String(get(v, 'Режим')),
      shuffled: String(get(v, 'Араластыру')) === 'иә',
      marks: String(get(v, 'Белгілер')),
      picks: String(get(v, 'Жауаптар')),
      id: String(get(v, 'ID'))
    };
  });
  return json_({ ok: true, rows: rows });
}
