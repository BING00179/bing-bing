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
  // 대한성서공회 웹사이트(개역개정) 책 약어 — BOOKS 와 같은 순서.
  // gen·jhn·1jn·ezk 는 실제 주소로 확인(2026-11-11 검색), 나머지는 같은 규칙(USFM 소문자)으로 짐작.
  var GAE_CODES = ('gen exo lev num deu jos jdg rut 1sa 2sa 1ki 2ki 1ch 2ch ezr neh est job psa pro ' +
    'ecc sng isa jer lam ezk dan hos jol amo oba jon mic nam hab zep hag zec mal mat mrk luk jhn act ' +
    'rom 1co 2co gal eph php col 1th 2th 1ti 2ti tit phm heb jas 1pe 2pe 1jn 2jn 3jn jud rev').split(' ');
  var FIRST_START = '2027-01-01'; // 1기 시작일
  // 화면 주소 (GitHub Pages, 공개). 시트 쪽 주소는 링크 뒤 ?s= 로만 다닙니다.
  var APP_BASE = 'https://bing00179.github.io/bing-bing/bible/';
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

  // ── 회차별 읽기표 ─────────────────────────────────
  // 시작일을 넣으면 그날 창세기 1장부터 주일 5장·그 밖 3장으로 끝까지 나눈 읽기표를 만듦.
  function makePlan(START) {
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

    // records: [[이름, 날짜, '완료'|'취소'], ...] 기록 순서대로. 마지막 줄이 그날 상태.
    // kind: '읽기'(기본) 또는 '필사'. 기록 동작: 읽기 = 완료/취소, 필사 = 필사완료/필사취소
    function doneSet(records, name, kind) {
      var pre = kind === '필사' ? '필사' : '';
      var last = {};
      records.forEach(function (r) {
        if (r[0] !== name) return;
        if (r[2] === pre + '완료' || r[2] === pre + '취소') last[r[1]] = r[2];
      });
      var s = new Set();
      Object.keys(last).forEach(function (d) {
        if (last[d] === pre + '완료' && PLAN[d]) s.add(d);
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

    function icsFor(appUrl, hour) {
      var H = alarmHour(hour) || DEFAULT_ALARM_HOUR;
      var L = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//bible-reading//KO', 'CALSCALE:GREGORIAN',
        'METHOD:PUBLISH', 'X-WR-CALNAME:' + icsEscape('함께 읽는 성경')];
      Object.keys(PLAN).sort().forEach(function (d) {
        var label = portionLabel(PLAN[d]);
        var desc = '오늘 읽을 곳: ' + label + '\n읽고 나서 [읽기 완료] 누르기: ' + appUrl;
        L.push('BEGIN:VEVENT',
          'UID:bible-' + d.replace(/-/g, '') + '@bible-reading',
          'DTSTAMP:' + stampUTC(START, 0, 0),
          'DTSTART:' + stampUTC(d, H, 0),
          'DTEND:' + stampUTC(d, H, 15),
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
    return { START: START, END: END, DAY_COUNT: DAY_COUNT, portionFor: portionFor, doneSet: doneSet,
      progress: progress, missedDays: missedDays, lastReadLabel: lastReadLabel, icsFor: icsFor };
  }
  var cache = {};
  function planFor(start) { return cache[start] || (cache[start] = makePlan(start)); }
  var first = planFor(FIRST_START);

  // 회차 목록: [{n: 1, start: '2027-01-01'}, …] (시작일 순). 시트에 없으면 1기만.
  function termsFrom(rows) {
    var list = (rows || []).filter(function (r) { return /^\d{4}-\d{2}-\d{2}$/.test(r[1]); })
      .map(function (r) { return { n: +r[0], start: r[1] }; });
    if (!list.length) list = [{ n: 1, start: FIRST_START }];
    list.sort(function (a, b) { return a.start < b.start ? -1 : 1; });
    return list;
  }
  // 오늘 기준 지금 회차(cur: 시작한 것 중 마지막, 없으면 다음 것)와 아직 시작 전인 다음 회차(next)
  function termsNow(terms, today) {
    var cur = null, next = null;
    terms.forEach(function (t) { if (t.start <= today) cur = t; else if (!next) next = t; });
    return { cur: cur || next, next: cur ? next : null };
  }
  // 그 회차·그 팀 참여자 (등록 순서). joins: [[이름, 회차, 팀, 동작], …] 기록 순서대로, 마지막 줄이 지금 상태.
  //   팀이 비면 '읽기', 동작이 비면 '참여' (예전 줄 호환).
  //   1기 읽기 팀만 예외: 등록한 사람 전부가 기본, '나감' 을 누른 사람만 빠짐.
  function participants(term, members, joins, team) {
    team = team || '읽기';
    var last = {};
    (joins || []).forEach(function (j) {
      if (+j[1] !== term.n || (j[2] || '읽기') !== team) return;
      last[j[0]] = j[3] || '참여';
    });
    var byDefault = term.n === 1 && team === '읽기';
    return members.filter(function (m) { return last[m] ? last[m] === '참여' : byDefault; });
  }
  var TEAMS = ['읽기', '필사'];

  function chapterIndex(book, ch) {
    for (var i = 0; i < TOTAL; i++) {
      if (BOOKS[CHAPTERS[i][0]][0] === book && CHAPTERS[i][1] === ch) return i;
    }
    return -1;
  }

  // 그날 분량의 장 목록: [{book: 1~66, name: '창세기', chapter: 1, gae: '개역개정 링크'}, …]
  function chaptersOf(p) {
    var out = [];
    if (!p) return out;
    for (var i = p.from; i <= p.to; i++) {
      var c = CHAPTERS[i];
      out.push({ book: c[0] + 1, name: BOOKS[c[0]][0], chapter: c[1],
        gae: 'https://www.bskorea.or.kr/bible/korbibReadpage.php?version=GAE&book=' + GAE_CODES[c[0]] + '&chap=' + c[1] });
    }
    return out;
  }

  function portionLabel(p) {
    if (!p) return '';
    var a = CHAPTERS[p.from], b = CHAPTERS[p.to];
    var an = BOOKS[a[0]][0], bn = BOOKS[b[0]][0];
    if (a[0] !== b[0]) return an + ' ' + a[1] + '장 ~ ' + bn + ' ' + b[1] + '장';
    if (a[1] === b[1]) return an + ' ' + a[1] + '장';
    return an + ' ' + a[1] + '~' + b[1] + '장';
  }

  function validName(s) {
    if (typeof s !== 'string') return null;
    var t = s.replace(/\s+/g, ' ').trim();
    if (t.length < 1 || t.length > 20) return null;
    return t;
  }

  // ── 달력 알림 파일(.ics) ─────────────────────────────────────
  // 날마다 고른 시각(한국)부터 15분 일정 + 시작 시각에 울리는 알림.
  // 시간은 UTC 로 적어 시간대 정보 없이도 어느 휴대폰에서나 같은 순간에 울림.
  // 알림 시각은 각자 고름: 5시~22시 정시 (구글 예약 실행이 프로젝트당 20개까지라 18개). 기본 6시.
  var ALARM_HOURS = [];
  for (var hh = 5; hh <= 22; hh++) ALARM_HOURS.push(hh);
  var DEFAULT_ALARM_HOUR = 6;
  function alarmHour(v) {
    var n = typeof v === 'number' ? v : /^\d{1,2}$/.test(String(v)) ? +v : NaN;
    return ALARM_HOURS.indexOf(n) >= 0 ? n : null;
  }
  function hourLabel(h) {
    if (h < 12) return '오전 ' + h + '시';
    if (h === 12) return '낮 12시';
    if (h < 19) return '오후 ' + (h - 12) + '시';
    if (h < 21) return '저녁 ' + (h - 12) + '시';
    return '밤 ' + (h - 12) + '시';
  }

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

  return {
    icsFor: first.icsFor, icsEscape: icsEscape, ALARM_HOURS: ALARM_HOURS, DEFAULT_ALARM_HOUR: DEFAULT_ALARM_HOUR,
    alarmHour: alarmHour, hourLabel: hourLabel,
    APP_BASE: APP_BASE, BOOKS: BOOKS, TOTAL: TOTAL, FIRST_START: FIRST_START,
    makePlan: planFor, termsFrom: termsFrom, termsNow: termsNow, participants: participants, TEAMS: TEAMS,
    // 1기 읽기표 (예전 이름 그대로 — 시험·호환용)
    START: first.START, END: first.END, DAY_COUNT: first.DAY_COUNT, portionFor: first.portionFor,
    doneSet: first.doneSet, progress: first.progress, missedDays: first.missedDays, lastReadLabel: first.lastReadLabel,
    addDays: addDays, weekday: weekday, chapterIndex: chapterIndex,
    portionLabel: portionLabel, chaptersOf: chaptersOf, GAE_CODES: GAE_CODES, validName: validName
  };
})();

if (typeof module !== 'undefined') module.exports = Core;
