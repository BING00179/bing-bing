// 자동 생성 파일 — bible-reading/build.js. 고칠 때는 core.js·server.gs 를 고치세요.

// 성경통독 — 순수 로직. 화면·앱스 스크립트 서버·시험이 같은 파일을 씁니다.
// 날짜는 전부 'YYYY-MM-DD' 문자열(한국 날짜)로 다루고, 계산은 UTC 로 해서
// 휴대폰 시간대와 상관없이 같은 답이 나오게 합니다.
var Core = (function () {
  // [이름, 장 수] — 개역개정 66권. 합계 1,189장 (시험이 지킴)
  var BOOKS = [
    ['창세기', 50], ['출애굽기', 40], ['레위기', 27], ['민수기', 36], ['신명기', 34],
    ['여호수아', 24], ['사사기', 21], ['룻기', 4], ['사무엘상', 31], ['사무엘하', 24],
    ['열왕기상', 22], ['열왕기하', 25], ['역대상', 29], ['역대하', 36], ['에스라', 10],
    ['느헤미야', 13], ['에스더', 10], ['욥기', 42], ['시편', 150], ['잠언', 31],
    ['전도서', 12], ['아가', 8], ['이사야', 66], ['예레미야', 52], ['예레미야애가', 5],
    ['에스겔', 48], ['다니엘', 12], ['호세아', 14], ['요엘', 3], ['아모스', 9],
    ['오바댜', 1], ['요나', 4], ['미가', 7], ['나훔', 3], ['하박국', 3],
    ['스바냐', 3], ['학개', 2], ['스가랴', 14], ['말라기', 4],
    ['마태복음', 28], ['마가복음', 16], ['누가복음', 24], ['요한복음', 21], ['사도행전', 28],
    ['로마서', 16], ['고린도전서', 16], ['고린도후서', 13], ['갈라디아서', 6], ['에베소서', 6],
    ['빌립보서', 4], ['골로새서', 4], ['데살로니가전서', 5], ['데살로니가후서', 3], ['디모데전서', 6],
    ['디모데후서', 4], ['디도서', 3], ['빌레몬서', 1], ['히브리서', 13], ['야고보서', 5],
    ['베드로전서', 5], ['베드로후서', 3], ['요한1서', 5], ['요한2서', 1], ['요한3서', 1],
    ['유다서', 1], ['요한계시록', 22]
  ];
  var START = '2027-01-01';
  var SUNDAY_CHAPTERS = 5;
  var OTHER_CHAPTERS = 3; // 평일·토요일·공휴일

  // 전체 장 번호(0~1188) → [권 번호, 장]
  var CHAPTERS = [];
  BOOKS.forEach(function (b, bi) {
    for (var c = 1; c <= b[1]; c++) CHAPTERS.push([bi, c]);
  });
  var TOTAL = CHAPTERS.length;

  function toUTC(d) { return Date.UTC(+d.slice(0, 4), +d.slice(5, 7) - 1, +d.slice(8, 10)); }
  function fromUTC(ms) { return new Date(ms).toISOString().slice(0, 10); }
  function addDays(d, n) { return fromUTC(toUTC(d) + n * 86400000); }
  function weekday(d) { return new Date(toUTC(d)).getUTCDay(); } // 0 = 주일

  // 날마다 [시작 장, 끝 장] 을 미리 계산
  var PLAN = {};
  var END = START;
  (function () {
    var at = 0, d = START;
    while (at < TOTAL) {
      var n = weekday(d) === 0 ? SUNDAY_CHAPTERS : OTHER_CHAPTERS;
      var to = Math.min(at + n, TOTAL) - 1;
      PLAN[d] = { from: at, to: to };
      END = d;
      at = to + 1;
      d = addDays(d, 1);
    }
  })();
  var DAY_COUNT = Object.keys(PLAN).length;

  function portionFor(d) { return PLAN[d] || null; }

  function chapterIndex(book, ch) {
    for (var i = 0; i < TOTAL; i++) {
      if (BOOKS[CHAPTERS[i][0]][0] === book && CHAPTERS[i][1] === ch) return i;
    }
    return -1;
  }

  function portionLabel(p) {
    if (!p) return '';
    var a = CHAPTERS[p.from], b = CHAPTERS[p.to];
    var an = BOOKS[a[0]][0], bn = BOOKS[b[0]][0];
    if (a[0] !== b[0]) return an + ' ' + a[1] + '장 ~ ' + bn + ' ' + b[1] + '장';
    if (a[1] === b[1]) return an + ' ' + a[1] + '장';
    return an + ' ' + a[1] + '~' + b[1] + '장';
  }

  // records: [[이름, 날짜, '완료'|'취소'], ...] 기록 순서대로. 마지막 줄이 그날 상태.
  function doneSet(records, name) {
    var last = {};
    records.forEach(function (r) {
      if (r[0] === name) last[r[1]] = r[2];
    });
    var s = new Set();
    Object.keys(last).forEach(function (d) {
      if (last[d] === '완료' && PLAN[d]) s.add(d);
    });
    return s;
  }

  function progress(dates) {
    var ch = 0;
    dates.forEach(function (d) {
      var p = PLAN[d];
      if (p) ch += p.to - p.from + 1;
    });
    return { chapters: ch, percent: Math.floor(ch * 1000 / TOTAL) / 10 };
  }

  // 시작일부터 어제까지(끝날을 넘지 않게) 중 완료 안 한 날 수. 오늘은 세지 않음.
  function missedDays(dates, today) {
    var last = addDays(today, -1);
    if (last > END) last = END;
    var n = 0;
    for (var d = START; d <= last; d = addDays(d, 1)) {
      if (!dates.has(d)) n++;
    }
    return n;
  }

  function lastReadLabel(dates) {
    var latest = '';
    dates.forEach(function (d) { if (d > latest) latest = d; });
    if (!latest) return '';
    var c = CHAPTERS[PLAN[latest].to];
    return BOOKS[c[0]][0] + ' ' + c[1] + '장까지';
  }

  function validName(s) {
    if (typeof s !== 'string') return null;
    var t = s.replace(/\s+/g, ' ').trim();
    if (t.length < 1 || t.length > 20) return null;
    return t;
  }

  // ── 달력 알림 파일(.ics) ─────────────────────────────────────
  // 날마다 한국 시각 06:00~06:15 일정 + 시작 시각에 울리는 알림.
  // 시간은 UTC 로 적어 시간대 정보 없이도 어느 휴대폰에서나 같은 순간에 울림.
  var ALARM_HOUR_KST = 6;

  function icsEscape(s) {
    return String(s).replace(/\\/g, '\\\\').replace(/;/g, '\\;').replace(/,/g, '\\,').replace(/\n/g, '\\n');
  }
  function utf8Len(ch) {
    var c = ch.codePointAt(0);
    return c < 0x80 ? 1 : c < 0x800 ? 2 : c < 0x10000 ? 3 : 4;
  }
  // 한 줄 75바이트 넘으면 접기 (글자 중간에서 자르지 않음)
  function fold(line) {
    var out = '', len = 0;
    Array.from(line).forEach(function (ch) {
      var n = utf8Len(ch);
      if (len + n > 75) { out += '\r\n '; len = 1; }
      out += ch; len += n;
    });
    return out;
  }
  function stampUTC(d, hour, minute) {
    var ms = toUTC(d) + ((hour - 9) * 60 + minute) * 60000; // KST = UTC+9
    return new Date(ms).toISOString().replace(/[-:]/g, '').slice(0, 15) + 'Z';
  }

  function icsFor(appUrl) {
    var L = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//bible-reading//KO', 'CALSCALE:GREGORIAN',
      'METHOD:PUBLISH', 'X-WR-CALNAME:' + icsEscape('함께 읽는 성경')];
    Object.keys(PLAN).sort().forEach(function (d) {
      var label = portionLabel(PLAN[d]);
      var desc = '오늘 읽을 곳: ' + label + '\n읽고 나서 [읽기 완료] 누르기: ' + appUrl;
      L.push('BEGIN:VEVENT',
        'UID:bible-' + d.replace(/-/g, '') + '@bible-reading',
        'DTSTAMP:' + stampUTC(START, 0, 0),
        'DTSTART:' + stampUTC(d, ALARM_HOUR_KST, 0),
        'DTEND:' + stampUTC(d, ALARM_HOUR_KST, 15),
        'SUMMARY:' + icsEscape('📖 ' + label),
        'DESCRIPTION:' + icsEscape(desc),
        'URL:' + appUrl,
        'BEGIN:VALARM', 'ACTION:DISPLAY', 'TRIGGER:PT0M',
        'DESCRIPTION:' + icsEscape('📖 ' + label),
        'END:VALARM', 'END:VEVENT');
    });
    L.push('END:VCALENDAR');
    return L.map(fold).join('\r\n') + '\r\n';
  }

  return {
    icsFor: icsFor, icsEscape: icsEscape,
    BOOKS: BOOKS, TOTAL: TOTAL, START: START, END: END, DAY_COUNT: DAY_COUNT,
    addDays: addDays, weekday: weekday, portionFor: portionFor, chapterIndex: chapterIndex,
    portionLabel: portionLabel, doneSet: doneSet, progress: progress,
    missedDays: missedDays, lastReadLabel: lastReadLabel, validName: validName
  };
})();


// 성경통독 — 앱스 스크립트 서버. build.js 가 이 파일 앞에 core.js 를 붙여
// dist/Code.gs 를 만듭니다. 시트 주소나 배포 주소는 여기 적지 않습니다(공개 저장소).
//
// 시트 두 장 (없으면 처음 열 때 만듦)
//   회원   이름 | 등록 시각
//   기록   시각 | 이름 | 날짜 | 동작(완료/취소)   ← 지우지 않고 덧쌓기만

var TZ = 'Asia/Seoul';

function doGet(e) {
  // ?cal=1 → 매일 아침 6시 알림이 들어 있는 달력 파일(.ics)
  if (e && e.parameter && e.parameter.cal) {
    return ContentService.createTextOutput(Core.icsFor(appUrl_()))
      .setMimeType(ContentService.MimeType.ICAL)
      .downloadAsFile('bible-2027.ics');
  }
  return HtmlService.createHtmlOutputFromFile('Index')
    .setTitle('함께 읽는 성경')
    .addMetaTag('viewport', 'width=device-width, initial-scale=1');
}

function sheet_(name, header) {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sh = ss.getSheetByName(name);
  if (!sh) {
    sh = ss.insertSheet(name);
    sh.getRange(1, 1, 1, header.length).setValues([header]).setFontWeight('bold');
    sh.setFrozenRows(1);
    // 날짜가 시트에서 날짜형으로 바뀌지 않게 전부 글자로
    sh.getRange('A:D').setNumberFormat('@');
  }
  return sh;
}
function members_() { return sheet_('회원', ['이름', '등록 시각']); }
function records_() { return sheet_('기록', ['시각', '이름', '날짜', '동작']); }
function appUrl_() { return ScriptApp.getService().getUrl(); }
function now_() { return Utilities.formatDate(new Date(), TZ, 'yyyy-MM-dd HH:mm:ss'); }
function today_() { return Utilities.formatDate(new Date(), TZ, 'yyyy-MM-dd'); }

function rows_(sh, cols) {
  var n = sh.getLastRow() - 1;
  if (n < 1) return [];
  return sh.getRange(2, 1, n, cols).getDisplayValues();
}

function append_(sh, row) {
  var r = sh.getRange(sh.getLastRow() + 1, 1, 1, row.length);
  r.setNumberFormat('@');
  r.setValues([row]);
}

// 화면이 처음 열릴 때와 버튼을 누른 뒤 부릅니다.
function getState() {
  var names = rows_(members_(), 1).map(function (r) { return r[0]; }).filter(String);
  var recs = rows_(records_(), 4).map(function (r) { return [r[1], r[2], r[3]]; });
  return { today: today_(), members: names, records: recs, appUrl: appUrl_() };
}

function register(name) {
  var n = Core.validName(name);
  if (!n) throw new Error('이름은 1~20자로 적어 주세요.');
  var lock = LockService.getScriptLock();
  lock.waitLock(10000);
  try {
    var exists = rows_(members_(), 1).some(function (r) { return r[0] === n; });
    if (!exists) append_(members_(), [n, now_()]);
  } finally {
    lock.releaseLock();
  }
  var s = getState();
  s.name = n;
  return s;
}

function mark(name, date, done) {
  var today = today_();
  if (!Core.portionFor(date)) throw new Error('읽기표에 없는 날짜입니다.');
  if (date > today) throw new Error('아직 오지 않은 날은 체크할 수 없어요.');
  var lock = LockService.getScriptLock();
  lock.waitLock(10000);
  try {
    var known = rows_(members_(), 1).some(function (r) { return r[0] === name; });
    if (!known) throw new Error('등록되지 않은 이름입니다.');
    append_(records_(), [now_(), name, date, done ? '완료' : '취소']);
  } finally {
    lock.releaseLock();
  }
  return getState();
}
