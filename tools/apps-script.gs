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
 *    Advanced → Go to ... (unsafe) → Allow. Сынақ хат келсе — бәрі дұрыс.
 * 6. Мекенжайды config.json ішіндегі "submitUrl" өрісіне қойыңыз.
 *
 * Кодты кейін өзгертсеңіз: Deploy → Manage deployments → ✏️ →
 * Version: New version → Deploy. Сонда мекенжай өзгермейді.
 *
 * ЕСКЕРТУ: жаңа рұқсат керек болса (мысалы хат жіберу қосылғанда),
 * алдымен `setup` функциясын Run арқылы бір рет іске қосыңыз — әйтпесе
 * жарияланған қосымша ескі рұқсатпен жұмыс істеп, қате береді.
 *
 * ТЕКСЕРУ: мекенжайдың соңына ?key=ҚҰПИЯ-СӨЗ қосып браузерде ашыңыз.
 * {"ok":true,"rows":[]} көрінсе — бәрі дұрыс.
 *
 * ПАРАҚТАР (өздері жасалады)
 * --------------------------
 *   Нәтижелер — тапсырылған жұмыстар
 *   Кодтар    — email растау кодтары мен сеанс токендері
 *   Рұқсат    — МІНДЕТТІ ЕМЕС. Бір бағанға email тізімін жазсаңыз, тек
 *               сол адамдар тест тапсыра алады. Бос болса — кез келген
 *               email жарайды (бірақ расталуы керек).
 */

var SECRET_KEY = 'ӨЗІҢІЗДІҢ-ҚҰПИЯ-СӨЗІҢІЗ';

/** Кестенің мекенжайынан: docs.google.com/spreadsheets/d/ОСЫ_ЖЕР/edit */
var SHEET_ID = '';

var SHEET_NAME  = 'Нәтижелер';
var CODES_NAME  = 'Кодтар';
var ALLOW_NAME  = 'Рұқсат';

var CODE_TTL_MIN  = 15;    /* растау коды қанша минут жарамды */
var TOKEN_TTL_HRS = 12;    /* кіргеннен кейін қанша сағат сұралмайды */
var RESEND_SEC    = 60;    /* кодты қайта сұрауға дейінгі үзіліс */

var HEADERS = [
  'Уақыты', 'Email', 'Тегі', 'Есімі', 'Сынып/топ', 'Тест', 'Нұсқа коды', 'Әрекет',
  'Балл', 'Макс', 'Пайыз', 'Уақыты (сек)', 'Режим', 'Араластыру',
  'Белгілер', 'Жауаптар', 'ID'
];
var CODE_HEADERS = ['Email', 'Код', 'Жіберілген', 'Код жарамды дейін',
                    'Токен', 'Токен жарамды дейін', 'Тегі', 'Есімі', 'Сынып/топ'];

/**
 * БІР РЕТ ІСКЕ ҚОСЫҢЫЗ: жоғарыдағы тізімнен `setup` таңдап, ▶ Run басыңыз.
 *
 * Не істейді:
 *   - Google-ден қажетті рұқсаттарды сұрайды (хат жіберу де кіреді —
 *     жаңа кодта бұл рұқсат бұрын болмаған, сондықтан міндетті қадам)
 *   - парақтарды жасайды
 *   - өзіңізге сынақ хат жібереді
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
  migrate_(tab_(CODES_NAME, CODE_HEADERS), CODE_HEADERS, CODES_NAME);
  Logger.log('Парақтар дайын: ' + SHEET_NAME + ', ' + CODES_NAME);

  MailApp.sendEmail({
    to: me,
    subject: 'Биология тесті — скрипт дұрыс орнатылды',
    body: 'Бұл — сынақ хат. Осы хатты алсаңыз, кодтар оқушыларға да жетеді.\n\n' +
          'Қалған тәулік шегі: ' + MailApp.getRemainingDailyQuota() + ' хат.'
  });
  Logger.log('Сынақ хат жіберілді: ' + me);
  Logger.log('Тәулік шегі: ' + MailApp.getRemainingDailyQuota());
  Logger.log('БӘРІ ДАЙЫН. Енді Deploy → Manage deployments → ✏️ → New version → Deploy.');
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

function valid_(email) { return /^[^@\s]+@[^@\s.]+\.[^@\s]+$/.test(email); }

/** Рұқсат парағы бос болса — бәріне ашық. */
function allowed_(email) {
  var ss = book_();
  var sh = ss.getSheetByName(ALLOW_NAME);
  if (!sh || sh.getLastRow() === 0) { return true; }
  var vals = sh.getDataRange().getValues();
  for (var i = 0; i < vals.length; i++) {
    for (var j = 0; j < vals[i].length; j++) {
      if (norm_(vals[i][j]) === email) { return true; }
    }
  }
  return false;
}

/** Кодтар парағынан email жолын табады. */
function codeRow_(email) {
  var sh = tab_(CODES_NAME, CODE_HEADERS);
  var last = sh.getLastRow();
  if (last < 2) { return { sheet: sh, row: 0, data: null }; }
  var vals = sh.getRange(2, 1, last - 1, CODE_HEADERS.length).getValues();
  for (var i = 0; i < vals.length; i++) {
    if (norm_(vals[i][0]) === email) {
      return { sheet: sh, row: i + 2, data: vals[i] };
    }
  }
  return { sheet: sh, row: 0, data: null };
}

/* ---------- 1. код жіберу ---------- */

function sendCode_(email) {
  if (!valid_(email)) { return json_({ ok: false, error: 'Email дұрыс жазылмаған.' }); }
  if (!allowed_(email)) {
    return json_({ ok: false, error: 'Бұл email тізімде жоқ. Мұғаліммен хабарласыңыз.' });
  }

  var lock = LockService.getScriptLock();
  try { lock.waitLock(10000); } catch (e) {
    return json_({ ok: false, error: 'Сервер бос емес, бірер секундтан кейін қайталаңыз.' });
  }
  try {
    var hit = codeRow_(email);
    var now = new Date();

    if (hit.row && hit.data[2] instanceof Date &&
        now - hit.data[2] < RESEND_SEC * 1000) {
      var wait = Math.ceil((RESEND_SEC * 1000 - (now - hit.data[2])) / 1000);
      return json_({ ok: false, error: 'Жаңа кодты ' + wait + ' секундтан кейін сұраңыз.' });
    }

    var code = String(Math.floor(100000 + Math.random() * 900000));
    var until = new Date(now.getTime() + CODE_TTL_MIN * 60000);
    var last  = hit.data ? hit.data[6] : '';
    var first = hit.data ? hit.data[7] : '';
    var group = hit.data ? hit.data[8] : '';

    if (hit.row) {
      hit.sheet.getRange(hit.row, 1, 1, CODE_HEADERS.length)
        .setValues([[email, code, now, until, '', '', last, first, group]]);
    } else {
      hit.sheet.appendRow([email, code, now, until, '', '', '', '', '']);
    }

    MailApp.sendEmail({
      to: email,
      subject: 'Биология тесті — растау коды: ' + code,
      body: 'Сәлеметсіз бе!\n\n' +
            'Тестке кіру коды: ' + code + '\n\n' +
            'Код ' + CODE_TTL_MIN + ' минут жарамды. Бұл кодты ешкімге бермеңіз — ' +
            'нәтиже сіздің атыңызбен жазылады.\n\n' +
            'Егер тестке кірмек болмасаңыз, бұл хатты елемеңіз.'
    });

    return json_({ ok: true, sent: true, ttlMin: CODE_TTL_MIN });
  } finally {
    lock.releaseLock();
  }
}

/* ---------- 2. кодты растау ---------- */

function verifyCode_(email, code) {
  var hit = codeRow_(email);
  if (!hit.row) { return json_({ ok: false, error: 'Алдымен кодты сұраңыз.' }); }
  if (String(hit.data[1]) !== String(code).trim()) {
    return json_({ ok: false, error: 'Код дұрыс емес.' });
  }
  if (!(hit.data[3] instanceof Date) || new Date() > hit.data[3]) {
    return json_({ ok: false, error: 'Кодтың мерзімі өтті. Жаңасын сұраңыз.' });
  }

  var token = Utilities.getUuid();
  var until = new Date(Date.now() + TOKEN_TTL_HRS * 3600000);
  hit.sheet.getRange(hit.row, 2, 1, 5)
    .setValues([['', hit.data[2], hit.data[3], token, until]]);

  return json_({
    ok: true, token: token, email: email,
    last: hit.data[6] || '', first: hit.data[7] || '', group: hit.data[8] || '',
    hours: TOKEN_TTL_HRS
  });
}

/** Токен жарамды ма — иә болса email-ді қайтарады. */
function checkToken_(email, token) {
  if (!token) { return null; }
  var hit = codeRow_(email);
  if (!hit.row || String(hit.data[4]) !== String(token)) { return null; }
  if (!(hit.data[5] instanceof Date) || new Date() > hit.data[5]) { return null; }
  return hit;
}

/* ---------- 3. нәтижені қабылдау ---------- */

function doPost(e) {
  try {
    var r = JSON.parse(e.postData.contents);
    var email = norm_(r.email);
    var hit = checkToken_(email, r.token);
    if (!hit) {
      return json_({ ok: false, error: 'Сеанс мерзімі өтті. Email арқылы қайта кіріңіз.',
                     needLogin: true });
    }
    var last  = String(r.last  || '').trim().slice(0, 60);
    var first = String(r.first || '').trim().slice(0, 60);
    var group = String(r.group || '').trim().slice(0, 60);
    if (!last || !first || !group) {
      return json_({ ok: false, error: 'Тегі, есімі және сыныбы толтырылуы керек.' });
    }

    /* кейінгі кіруде қайта сұрамау үшін сақтап қоямыз */
    hit.sheet.getRange(hit.row, 7, 1, 3).setValues([[last, first, group]]);

    var sh = tab_(SHEET_NAME, HEADERS);
    var attempt = 1;
    var lastRow = sh.getLastRow();          /* `last` — тегі, шатастырмау керек */
    if (lastRow > 1) {
      var prev = sh.getRange(2, 2, lastRow - 1, 6).getValues();   /* Email..Нұсқа коды */
      for (var i = 0; i < prev.length; i++) {
        if (norm_(prev[i][0]) === email && String(prev[i][5]) === String(r.test)) {
          attempt++;
        }
      }
    }

    var id = Utilities.getUuid();
    sh.appendRow([
      new Date(), email, last, first, group,
      String(r.testTitle || '').slice(0, 60),
      String(r.test || '').slice(0, 40),
      attempt,
      Number(r.score) || 0, Number(r.max) || 0, Number(r.pct) || 0,
      Number(r.seconds) || 0,
      String(r.mode || ''), r.shuffled ? 'иә' : 'жоқ',
      String(r.marks || '').slice(0, 300),
      String(r.picks || '').slice(0, 2000),
      id
    ]);
    return json_({ ok: true, id: id, attempt: attempt });
  } catch (err) {
    return json_({ ok: false, error: String(err) });
  }
}

/* ---------- 4. дашборд ---------- */

function doGet(e) {
  var p = (e && e.parameter) ? e.parameter : {};

  if (p.action === 'sendCode') { return sendCode_(norm_(p.email)); }
  if (p.action === 'verify')   { return verifyCode_(norm_(p.email), p.code); }
  if (p.action === 'session') {
    var hit = checkToken_(norm_(p.email), p.token);
    return hit
      ? json_({ ok: true, email: norm_(p.email), last: hit.data[6] || '',
                first: hit.data[7] || '', group: hit.data[8] || '' })
      : json_({ ok: false, error: 'Сеанс мерзімі өтті.', needLogin: true });
  }

  if (p.key !== SECRET_KEY) { return json_({ ok: false, error: 'құпия сөз дұрыс емес' }); }

  var sh = tab_(SHEET_NAME, HEADERS);
  var lastRow = sh.getLastRow();
  if (lastRow < 2) { return json_({ ok: true, rows: [] }); }
  var values = sh.getRange(2, 1, lastRow - 1, HEADERS.length).getValues();
  var rows = values.map(function (v) {
    return {
      at: v[0] instanceof Date ? v[0].toISOString() : String(v[0]),
      email: String(v[1]), last: String(v[2]), first: String(v[3]),
      name: (String(v[2]) + ' ' + String(v[3])).trim(),
      group: String(v[4]),
      testTitle: String(v[5]), test: String(v[6]), attempt: Number(v[7]) || 1,
      score: Number(v[8]), max: Number(v[9]), pct: Number(v[10]),
      seconds: Number(v[11]), mode: String(v[12]), shuffled: String(v[13]) === 'иә',
      marks: String(v[14]), picks: String(v[15]), id: String(v[16])
    };
  });
  return json_({ ok: true, rows: rows });
}
