/**
 * Биология ҰБТ тесті — нәтижелерді жинайтын Google Apps Script.
 *
 * ОРНАТУ (бір рет, шамамен 5 минут)
 * ----------------------------------
 * 1. sheets.new — жаңа Google кестесін ашыңыз.
 * 2. Кеңейтімдер (Extensions) → Apps Script.
 * 3. Редактордағы бар кодты ТҮГЕЛ өшіріп (Ctrl+A → Delete), осы файлды қойыңыз.
 *    Кодты `function myFunction() { ... }` ішіне САЛМАҢЫЗ — Apps Script
 *    doPost пен doGet-ті тек сыртқы деңгейден іздейді.
 * 4. Төмендегі SECRET_KEY мәнін өзіңіздің құпия сөзіңізге ауыстырыңыз.
 *    Оны тек сіз білесіз — дашбордқа кіру үшін қажет.
 *    SHEET_ID өрісіне кестенің мекенжайындағы ID-ді қойыңыз.
 * 5. Deploy → New deployment → түрі: Web app.
 *      Execute as:      Me
 *      Who has access:  Anyone            ← міндетті түрде осылай
 * 6. Deploy → рұқсат сұрайды: Authorize access → аккаунт → «Google hasn't
 *    verified this app» бетінде Advanced → Go to ... (unsafe) → Allow.
 *
 *    ТЕКСЕРУ: жарияланған мекенжайдың соңына ?key=ҚҰПИЯ-СӨЗІҢІЗ қосып,
 *    браузерде ашыңыз. {"ok":true,"rows":[]} көрінсе — бәрі дұрыс.
 *    Кіру беті шықса — «Who has access» «Anyone» емес.
 * 7. Шыққан мекенжайды (.../exec деп бітеді) көшіріп,
 *    репозиторийдегі config.json ішіндегі "submitUrl" өрісіне қойыңыз,
 *    сосын `python3 build.py` жүргізіп, өзгерісті пушқа жіберіңіз.
 *
 * Кодты кейін өзгертсеңіз, Deploy → Manage deployments → өңдеу (қарындаш)
 * → Version: New version → Deploy деп қайта жариялаңыз.
 */

var SECRET_KEY = 'ӨЗІҢІЗДІҢ-ҚҰПИЯ-СӨЗІҢІЗ';
var SHEET_NAME = 'Нәтижелер';

/**
 * Кестенің ID-і. Кестенің мекенжайынан алынады:
 *   docs.google.com/spreadsheets/d/ОСЫ_ЖЕР/edit
 * Скрипт кестенің өз ішінен (Extensions → Apps Script) ашылса, бос
 * қалдыруға болады. Бірақ жазып қойған дұрыс — сонда скрипт бөлек
 * жасалса да кестені табады.
 */
var SHEET_ID = '';

var HEADERS = [
  'Уақыты', 'Аты-жөні', 'Сынып/топ', 'Тест', 'Нұсқа коды',
  'Балл', 'Макс', 'Пайыз', 'Уақыты (сек)', 'Режим', 'Араластыру',
  'Белгілер', 'Жауаптар', 'ID'
];

function sheet_() {
  var ss = SHEET_ID
    ? SpreadsheetApp.openById(SHEET_ID)
    : SpreadsheetApp.getActiveSpreadsheet();
  if (!ss) {
    throw new Error('Кесте табылмады. SHEET_ID жазыңыз немесе скриптті ' +
                    'кестенің ішінен (Extensions → Apps Script) ашыңыз.');
  }
  var sh = ss.getSheetByName(SHEET_NAME);
  if (!sh) {
    sh = ss.insertSheet(SHEET_NAME);
  }
  if (sh.getLastRow() === 0) {
    sh.appendRow(HEADERS);
    sh.getRange(1, 1, 1, HEADERS.length).setFontWeight('bold');
    sh.setFrozenRows(1);
  }
  return sh;
}

function json_(obj) {
  return ContentService
    .createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}

/** Тест бетінен келетін нәтиже. */
function doPost(e) {
  try {
    var r = JSON.parse(e.postData.contents);
    if (!r || !r.name) {
      return json_({ ok: false, error: 'аты-жөні жоқ' });
    }
    var id = Utilities.getUuid();
    sheet_().appendRow([
      new Date(),
      String(r.name).slice(0, 120),
      String(r.group || '').slice(0, 60),
      String(r.testTitle || '').slice(0, 60),
      String(r.test || '').slice(0, 40),
      Number(r.score) || 0,
      Number(r.max) || 0,
      Number(r.pct) || 0,
      Number(r.seconds) || 0,
      String(r.mode || ''),
      r.shuffled ? 'иә' : 'жоқ',
      String(r.marks || '').slice(0, 300),
      String(r.picks || '').slice(0, 2000),
      id
    ]);
    return json_({ ok: true, id: id });
  } catch (err) {
    return json_({ ok: false, error: String(err) });
  }
}

/** Дашборд үшін деректер. */
function doGet(e) {
  var key = e && e.parameter ? e.parameter.key : '';
  if (key !== SECRET_KEY) {
    return json_({ ok: false, error: 'құпия сөз дұрыс емес' });
  }
  var sh = sheet_();
  var last = sh.getLastRow();
  if (last < 2) {
    return json_({ ok: true, rows: [] });
  }
  var values = sh.getRange(2, 1, last - 1, HEADERS.length).getValues();
  var rows = values.map(function (v) {
    return {
      at: v[0] instanceof Date ? v[0].toISOString() : String(v[0]),
      name: String(v[1]),
      group: String(v[2]),
      testTitle: String(v[3]),
      test: String(v[4]),
      score: Number(v[5]),
      max: Number(v[6]),
      pct: Number(v[7]),
      seconds: Number(v[8]),
      mode: String(v[9]),
      shuffled: String(v[10]) === 'иә',
      marks: String(v[11]),
      picks: String(v[12]),
      id: String(v[13])
    };
  });
  return json_({ ok: true, rows: rows });
}
