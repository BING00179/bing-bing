// 자동 생성 파일 — bible-reading/build.js. 고칠 때는 core.js·webpush.js·server.gs 를 고치세요.

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


// 웹 푸시 서명(VAPID, ES256) — 앱스 스크립트에는 타원곡선 서명 기능이 없어서
// 순수 자바스크립트로 씁니다. node 시험이 표준 암호 모듈로 결과를 검증합니다
// (test/webpush.test.js). 알림 내용은 보내지 않으므로(빈 푸시) 암호화는 필요 없고,
// 휴대폰의 sw.js 가 그날 분량을 스스로 계산해 보여줍니다.
var WebPush = (function () {
  // 큰 정수(BigInt). 앱스 스크립트 편집기는 0n 같은 표기를 저장할 때 못 읽으므로
  // (2026-11-11 'Unexpected token ILLEGAL') 전부 BigInt() 호출로 만듭니다.
  var I0 = BigInt(0), I1 = BigInt(1), I2 = BigInt(2), I3 = BigInt(3), I4 = BigInt(4), I8 = BigInt(8), IFF = BigInt(255);

  // ── SHA-256 ──
  var K = [
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
    0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
    0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
    0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2
  ];
  function sha256(bytes) {
    var H = [0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19];
    var len = bytes.length, total = ((len + 9 + 63) >> 6) << 6;
    var m = new Array(total).fill(0);
    for (var i = 0; i < len; i++) m[i] = bytes[i] & 0xff;
    m[len] = 0x80;
    var bits = len * 8;
    for (i = 0; i < 8; i++) m[total - 1 - i] = Math.floor(bits / Math.pow(2, 8 * i)) & 0xff;
    var w = new Array(64);
    for (var off = 0; off < total; off += 64) {
      for (i = 0; i < 16; i++) w[i] = (m[off + 4 * i] << 24) | (m[off + 4 * i + 1] << 16) | (m[off + 4 * i + 2] << 8) | m[off + 4 * i + 3];
      for (i = 16; i < 64; i++) {
        var a = w[i - 15], b = w[i - 2];
        var s0 = ((a >>> 7) | (a << 25)) ^ ((a >>> 18) | (a << 14)) ^ (a >>> 3);
        var s1 = ((b >>> 17) | (b << 15)) ^ ((b >>> 19) | (b << 13)) ^ (b >>> 10);
        w[i] = (w[i - 16] + s0 + w[i - 7] + s1) | 0;
      }
      var A = H[0], B = H[1], C = H[2], D = H[3], E = H[4], F = H[5], G = H[6], Hh = H[7];
      for (i = 0; i < 64; i++) {
        var S1 = ((E >>> 6) | (E << 26)) ^ ((E >>> 11) | (E << 21)) ^ ((E >>> 25) | (E << 7));
        var ch = (E & F) ^ (~E & G);
        var t1 = (Hh + S1 + ch + K[i] + w[i]) | 0;
        var S0 = ((A >>> 2) | (A << 30)) ^ ((A >>> 13) | (A << 19)) ^ ((A >>> 22) | (A << 10));
        var mj = (A & B) ^ (A & C) ^ (B & C);
        var t2 = (S0 + mj) | 0;
        Hh = G; G = F; F = E; E = (D + t1) | 0; D = C; C = B; B = A; A = (t1 + t2) | 0;
      }
      H[0] = (H[0] + A) | 0; H[1] = (H[1] + B) | 0; H[2] = (H[2] + C) | 0; H[3] = (H[3] + D) | 0;
      H[4] = (H[4] + E) | 0; H[5] = (H[5] + F) | 0; H[6] = (H[6] + G) | 0; H[7] = (H[7] + Hh) | 0;
    }
    var out = [];
    H.forEach(function (h) { out.push((h >>> 24) & 0xff, (h >>> 16) & 0xff, (h >>> 8) & 0xff, h & 0xff); });
    return out;
  }
  function hmac(key, msg) {
    if (key.length > 64) key = sha256(key);
    var k = key.slice(); while (k.length < 64) k.push(0);
    var ip = k.map(function (x) { return x ^ 0x36; }), op = k.map(function (x) { return x ^ 0x5c; });
    return sha256(op.concat(sha256(ip.concat(msg))));
  }

  // ── 바이트·글자 ──
  function utf8(s) {
    var out = [], str = unescape(encodeURIComponent(s));
    for (var i = 0; i < str.length; i++) out.push(str.charCodeAt(i));
    return out;
  }
  var B64 = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_';
  function b64u(bytes) {
    var s = '', i;
    for (i = 0; i + 2 < bytes.length; i += 3) {
      var n = (bytes[i] << 16) | (bytes[i + 1] << 8) | bytes[i + 2];
      s += B64[n >> 18] + B64[(n >> 12) & 63] + B64[(n >> 6) & 63] + B64[n & 63];
    }
    if (bytes.length - i === 1) { n = bytes[i] << 16; s += B64[n >> 18] + B64[(n >> 12) & 63]; }
    else if (bytes.length - i === 2) { n = (bytes[i] << 16) | (bytes[i + 1] << 8); s += B64[n >> 18] + B64[(n >> 12) & 63] + B64[(n >> 6) & 63]; }
    return s;
  }
  function unb64u(s) {
    var out = [], buf = 0, bits = 0;
    for (var i = 0; i < s.length; i++) {
      var v = B64.indexOf(s[i]); if (v < 0) throw new Error('base64url 아님');
      buf = (buf << 6) | v; bits += 6;
      if (bits >= 8) { bits -= 8; out.push((buf >> bits) & 0xff); }
    }
    return out;
  }
  function toInt(bytes) { var n = I0; bytes.forEach(function (b) { n = (n << I8) | BigInt(b); }); return n; }
  function toBytes(n, len) { var out = new Array(len); for (var i = len - 1; i >= 0; i--) { out[i] = Number(n & IFF); n >>= I8; } return out; }

  // ── P-256 ──
  var P = BigInt('0xffffffff00000001000000000000000000000000ffffffffffffffffffffffff');
  var N = BigInt('0xffffffff00000000ffffffffffffffffbce6faada7179e84f3b9cac2fc632551');
  var G = [BigInt('0x6b17d1f2e12c4247f8bce6e563a440f277037d812deb33a0f4a13945d898c296'),
           BigInt('0x4fe342e2fe1a7f9b8ee7eb4a7c0f9e162bce33576b315ececbb6406837bf51f5')];
  function mod(a, m) { var r = a % m; return r < I0 ? r + m : r; }
  function inv(a, m) {
    var t = I0, nt = I1, r = m, nr = mod(a, m);
    while (nr !== I0) { var q = r / nr; var x = t - q * nt; t = nt; nt = x; x = r - q * nr; r = nr; nr = x; }
    return mod(t, m);
  }
  // 야코비안 좌표 (역수 계산을 마지막 한 번으로)
  function dbl(p) {
    if (!p) return null;
    var X = p[0], Y = p[1], Z = p[2];
    if (Y === I0) return null;
    var YY = mod(Y * Y, P), S = mod(I4 * X * YY, P), ZZ = mod(Z * Z, P);
    var M = mod(I3 * (X - ZZ) * (X + ZZ), P); // a = -3
    var X3 = mod(M * M - I2 * S, P);
    return [X3, mod(M * (S - X3) - I8 * YY * YY, P), mod(I2 * Y * Z, P)];
  }
  function add(p, q) {
    if (!p) return q; if (!q) return p;
    var Z1Z1 = mod(p[2] * p[2], P), Z2Z2 = mod(q[2] * q[2], P);
    var U1 = mod(p[0] * Z2Z2, P), U2 = mod(q[0] * Z1Z1, P);
    var S1 = mod(p[1] * q[2] * Z2Z2, P), S2 = mod(q[1] * p[2] * Z1Z1, P);
    if (U1 === U2) return S1 === S2 ? dbl(p) : null;
    var H = mod(U2 - U1, P), R = mod(S2 - S1, P), HH = mod(H * H, P), HHH = mod(H * HH, P), V = mod(U1 * HH, P);
    var X3 = mod(R * R - HHH - I2 * V, P);
    return [X3, mod(R * (V - X3) - S1 * HHH, P), mod(p[2] * q[2] * H, P)];
  }
  function mul(k) {
    var R = null, Q = [G[0], G[1], I1];
    while (k > I0) { if (k & I1) R = add(R, Q); Q = dbl(Q); k >>= I1; }
    var zi = inv(R[2], P), zi2 = mod(zi * zi, P);
    return [mod(R[0] * zi2, P), mod(R[1] * zi2 * zi, P)];
  }

  function keysFromPrivate(privB64) {
    var d = toInt(unb64u(privB64));
    if (d <= I0 || d >= N) throw new Error('개인키 범위 밖');
    var Q = mul(d);
    return { privateKey: b64u(toBytes(d, 32)), publicKey: b64u([4].concat(toBytes(Q[0], 32), toBytes(Q[1], 32))) };
  }
  // random: 호출할 때마다 다른 글자를 주는 함수 (앱스 스크립트: Utilities.getUuid)
  function newKeys(random) {
    for (;;) {
      var seed = sha256(utf8(random() + random() + random() + random()));
      var d = toInt(seed);
      if (d > I0 && d < N) return keysFromPrivate(b64u(seed));
    }
  }

  // RFC 6979 — 난수 없이 서명용 k 를 정함 (앱스 스크립트에 안전한 난수가 없어서)
  function signES256(privB64, msg) {
    var x = unb64u(privB64), d = toInt(x), h1 = sha256(msg);
    var e = toInt(h1), hb = toBytes(mod(e, N), 32);
    var V = new Array(32).fill(1), Kk = new Array(32).fill(0);
    Kk = hmac(Kk, V.concat([0], x, hb)); V = hmac(Kk, V);
    Kk = hmac(Kk, V.concat([1], x, hb)); V = hmac(Kk, V);
    for (;;) {
      V = hmac(Kk, V);
      var k = toInt(V);
      if (k > I0 && k < N) {
        var r = mod(mul(k)[0], N);
        if (r !== I0) {
          var s = mod(inv(k, N) * (e + r * d), N);
          if (s !== I0) return toBytes(r, 32).concat(toBytes(s, 32));
        }
      }
      Kk = hmac(Kk, V.concat([0])); V = hmac(Kk, V);
    }
  }

  function vapidHeader(endpoint, keys, subject, nowSec) {
    var aud = endpoint.match(/^https:\/\/[^\/]+/)[0];
    var head = b64u(utf8(JSON.stringify({ typ: 'JWT', alg: 'ES256' })));
    var body = b64u(utf8(JSON.stringify({ aud: aud, exp: nowSec + 12 * 3600, sub: subject })));
    var sig = b64u(signES256(keys.privateKey, utf8(head + '.' + body)));
    return 'vapid t=' + head + '.' + body + '.' + sig + ', k=' + keys.publicKey;
  }

  // 휴대폰 회사들의 알림 서버만 받습니다. 아무 주소나 받으면 우리 서버가
  // 남의 주소로 요청을 보내는 데 쓰일 수 있습니다.
  var HOSTS = [/^fcm\.googleapis\.com$/, /^web\.push\.apple\.com$/, /^updates\.push\.services\.mozilla\.com$/,
    /^[a-z0-9-]+\.notify\.windows\.com$/];
  function allowedEndpoint(u) {
    if (typeof u !== 'string' || u.length > 1000) return false;
    var m = u.match(/^https:\/\/([^\/:?#]+)\//);
    return !!m && HOSTS.some(function (h) { return h.test(m[1]); });
  }

  return { sha256: sha256, hmac: hmac, utf8: utf8, b64u: b64u, keysFromPrivate: keysFromPrivate,
    newKeys: newKeys, signES256: signES256, vapidHeader: vapidHeader, allowedEndpoint: allowedEndpoint };
})();


// 성경통독 — 앱스 스크립트 서버(기록·알림 담당). 화면은 GitHub Pages 에 있습니다.
// build.js 가 core.js·webpush.js 를 앞에 붙여 dist/Code.gs 를 만듭니다.
// 시트 주소·배포 주소·알림 개인키는 저장소에 적지 않습니다(공개 저장소).
//   개인키는 setupPush() 가 만들어 '스크립트 속성'에만 둡니다.
//
// 시트 (없으면 처음 쓸 때 만듦) — 전부 지우지 않고 덧쌓기만. 맨 끝 '모임' 칸: 빈칸 = 처음 모임(기본)
//   회원   이름 | 등록 시각 | 모임
//   기록   시각 | 이름 | 날짜 | 동작(완료/취소/필사완료/필사취소) | 모임
//   회차   회차 | 시작일 | 만든 시각 | 모임
//   참여   시각 | 이름 | 회차 | 팀 | 동작 | 모임
//   알림   시각 | 이름 | 알림 주소 | 동작(등록/해제/만료) | 알림 시간 | 모임
//   모임   코드 | 이름 | 만든 시각      ← 회장님이 메뉴 '새 모임 만들기' 로 만듦. 링크 끝 &g=코드
//
// 여러 여전도회가 한 시트를 씀. 앱은 자기 모임 줄만 읽고 쓰므로 서로 안 보임 (시트 주인은 다 봄).

var TZ = 'Asia/Seoul';

// ── 모임 ── 이번 요청이 어느 모임 것인지 (앱스 스크립트는 요청마다 따로 돌아서 전역 변수로 충분)
var G = '';
function groups_() {
  return rows_(groupsSheet_(), 3).filter(function (r) { return r[0]; }).map(function (r) { return { code: r[0], name: r[1] }; });
}
function setGroup_(g) {
  g = String(g || '').trim();
  if (g && !groups_().some(function (x) { return x.code === g; })) throw new Error('모르는 모임입니다. 받은 링크를 다시 확인해 주세요.');
  G = g;
}
function groupName_() {
  var hit = groups_().filter(function (x) { return x.code === G; })[0];
  return hit ? hit.name : (PropertiesService.getScriptProperties().getProperty('GROUP0_NAME') || '');
}

// ── 문 ─────────────────────────────────────────────
function doGet(e) {
  var p = (e && e.parameter) || {};
  try { setGroup_(p.g); } catch (err) { return json_(function () { throw err; }); }
  if (p.cal) {
    // 매일 아침 6시 알림이 들어 있는 달력 파일
    return ContentService.createTextOutput(Core.makePlan(openTerm_().start).icsFor(appLink_(), p.h))
      .setMimeType(ContentService.MimeType.ICAL)
      .downloadAsFile('bible-2027.ics');
  }
  return json_(function () { return getState(); });
}

// 화면은 text/plain 으로 {"fn": "...", "args": [...]} 를 보냅니다 (CORS 사전 요청을 피함).
function doPost(e) {
  return json_(function () {
    var req = JSON.parse(e.postData.contents);
    setGroup_(req.g);
    var fns = { register: register, join: join, mark: mark, subscribe: subscribe, unsubscribe: unsubscribe };
    if (!fns[req.fn]) throw new Error('모르는 요청입니다.');
    return fns[req.fn].apply(null, req.args || []);
  });
}

function json_(f) {
  var out;
  try { out = { ok: true, data: f() }; }
  catch (err) { out = { ok: false, error: String(err && err.message || err) }; }
  return ContentService.createTextOutput(JSON.stringify(out)).setMimeType(ContentService.MimeType.JSON);
}

// ── 시트 ───────────────────────────────────────────
function sheet_(name, header) {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sh = ss.getSheetByName(name);
  if (!sh) {
    sh = ss.insertSheet(name);
    sh.getRange(1, 1, 1, header.length).setValues([header]).setFontWeight('bold');
    sh.setFrozenRows(1);
  }
  return sh;
}
// 모임 칸 제목이 없으면(예전 시트) 채움 — 비어 있을 때만
function withCol_(sh, col, title) {
  if (!sh.getRange(1, col, 1, 1).getDisplayValues()[0][0]) sh.getRange(1, col, 1, 1).setValues([[title]]);
  return sh;
}
function members_() { return withCol_(sheet_('회원', ['이름', '등록 시각', '모임']), 3, '모임'); }
function records_() { return withCol_(sheet_('기록', ['시각', '이름', '날짜', '동작', '모임']), 5, '모임'); }
function termsSheet_() { return withCol_(sheet_('회차', ['회차', '시작일', '만든 시각', '모임']), 4, '모임'); }
function groupsSheet_() { return sheet_('모임', ['코드', '이름', '만든 시각']); }
// 이번 모임 줄만 (모임 칸 위치 gcol, 앞 cols 칸만 돌려줌)
function rowsG_(sh, cols, gcol) {
  var n = sh.getLastRow() - 1;
  if (n < 1) return [];
  return sh.getRange(2, 1, n, gcol).getDisplayValues()
    .filter(function (r) { return (r[gcol - 1] || '') === G; })
    .map(function (r) { return r.slice(0, cols); });
}
function joins_() {
  var sh = withCol_(sheet_('참여', ['시각', '이름', '회차', '팀', '동작', '모임']), 6, '모임');
  // 팀을 넣기 전에 만든 시트에는 넷째·다섯째 칸 제목이 없음 (빈 칸 = 읽기·참여)
  // 비어 있을 때만 채움 (회장님이 제목 글자를 고쳐도 되돌리지 않음)
  if (!sh.getRange(1, 4, 1, 1).getDisplayValues()[0][0]) sh.getRange(1, 4, 1, 2).setValues([['팀', '동작']]);
  return sh;
}

// ── 회차 ── 시트 '회차' 가 비어 있으면 1기(2027-01-01)만
function terms_() { return Core.termsFrom(rowsG_(termsSheet_(), 2, 4)); }
function joinRows_() { return rowsG_(joins_(), 5, 6).map(function (r) { return [r[1], r[2], r[3], r[4]]; }); }
// 그 날짜가 들어 있는 회차의 읽기표 (없으면 null)
function planOf_(date) {
  var hit = null;
  terms_().forEach(function (t) { var p = Core.makePlan(t.start); if (p.portionFor(date)) hit = p; });
  return hit;
}
// 새로 등록·참여할 회차: 시작 전인 다음 회차가 있으면 그것, 없으면 지금 회차
function openTerm_() { var tn = Core.termsNow(terms_(), today_()); return tn.next || tn.cur; }
function pushes_() {
  var sh = withCol_(sheet_('알림', ['시각', '이름', '알림 주소', '동작', '알림 시간', '모임']), 6, '모임');
  // 시각 고르기 전에 만든 시트에는 다섯째 칸 제목이 없음
  if (!sh.getRange(1, 5, 1, 1).getDisplayValues()[0][0]) sh.getRange(1, 5, 1, 1).setValues([['알림 시간']]);
  return sh;
}
function now_() { return Utilities.formatDate(new Date(), TZ, 'yyyy-MM-dd HH:mm:ss'); }
function today_() { return Utilities.formatDate(new Date(), TZ, 'yyyy-MM-dd'); }

function rows_(sh, cols) {
  var n = sh.getLastRow() - 1;
  if (n < 1) return [];
  return sh.getRange(2, 1, n, cols).getDisplayValues();
}
function append_(sh, row) {
  var r = sh.getRange(sh.getLastRow() + 1, 1, 1, row.length);
  r.setNumberFormat('@'); // 날짜가 날짜형으로 바뀌지 않게 글자로
  r.setValues([row]);
}
function locked_(f) {
  var lock = LockService.getScriptLock();
  lock.waitLock(10000);
  try { return f(); } finally { lock.releaseLock(); }
}
function memberNames_() { return rowsG_(members_(), 1, 3).map(function (r) { return r[0]; }).filter(String); }

// 이 배포의 주소 조각(…/macros/s/<여기>/exec) → 화면 주소 뒤에 붙임
function deploymentId_() {
  var m = String(ScriptApp.getService().getUrl()).match(/\/s\/([A-Za-z0-9_-]+)\//);
  return m ? m[1] : '';
}
function appLink_(g) { g = g === undefined ? G : g; return Core.APP_BASE + '?s=' + deploymentId_() + (g ? '&g=' + g : ''); }

// ── 화면이 부르는 것 ────────────────────────────────
function getState() {
  var recs = rowsG_(records_(), 4, 5).map(function (r) { return [r[1], r[2], r[3]]; });
  var pub = PropertiesService.getScriptProperties().getProperty('VAPID_PUBLIC') || '';
  return { today: today_(), members: memberNames_(), records: recs, vapidKey: pub,
    terms: terms_(), joins: joinRows_(), group: G, groupName: groupName_() };
}

function register(name) {
  var n = Core.validName(name);
  if (!n) throw new Error('이름은 1~20자로 적어 주세요.');
  locked_(function () {
    if (memberNames_().indexOf(n) < 0) append_(members_(), [n, now_(), G]);
    joinTerm_(n, openTerm_()); // 새로 온 사람은 지금 열려 있는 회차에 바로 참여
  });
  var s = getState();
  s.name = n;
  return s;
}

// 회차 참여 (2기부터. 1기는 등록한 사람 전부). 이미 참여했으면 그대로.
// 그 회차의 읽기·필사 팀에 들어가거나(on) 나감. 이미 그 상태면 아무것도 안 씀.
function joinTerm_(name, term, team, on) {
  if (!term) return;
  team = team || '읽기'; on = on !== false;
  var now = Core.participants(term, [name], joinRows_(), team).length > 0;
  if (now !== on) append_(joins_(), [now_(), name, String(term.n), team, on ? '참여' : '나감', G]);
}
function join(name, team, on) {
  team = team || '읽기';
  if (Core.TEAMS.indexOf(team) < 0) throw new Error('모르는 팀입니다.');
  locked_(function () {
    if (memberNames_().indexOf(name) < 0) throw new Error('등록되지 않은 이름입니다.');
    joinTerm_(name, openTerm_(), team, on);
  });
  return getState();
}

function mark(name, date, done, kind) {
  if (kind && kind !== '필사' && kind !== '읽기') throw new Error('모르는 기록입니다.');
  var pre = kind === '필사' ? '필사' : '';
  if (!planOf_(date)) throw new Error('읽기표에 없는 날짜입니다.');
  if (date > today_()) throw new Error('아직 오지 않은 날은 체크할 수 없어요.');
  locked_(function () {
    if (memberNames_().indexOf(name) < 0) throw new Error('등록되지 않은 이름입니다.');
    append_(records_(), [now_(), name, date, pre + (done ? '완료' : '취소'), G]);
  });
  return getState();
}

function subscribe(name, endpoint, hour) {
  if (!WebPush.allowedEndpoint(endpoint)) throw new Error('이 휴대폰의 알림 주소를 받을 수 없어요.');
  var h = hour === undefined || hour === null || hour === '' ? Core.DEFAULT_ALARM_HOUR : Core.alarmHour(hour);
  if (h === null) throw new Error('알림 시간은 5시~22시 정시로 골라 주세요.');
  locked_(function () {
    if (memberNames_().indexOf(name) < 0) throw new Error('등록되지 않은 이름입니다.');
    append_(pushes_(), [now_(), name, endpoint, '등록', String(h), G]);
  });
  return getState();
}

function unsubscribe(endpoint) {
  if (!WebPush.allowedEndpoint(endpoint)) throw new Error('이 휴대폰의 알림 주소를 받을 수 없어요.');
  locked_(function () { append_(pushes_(), [now_(), '', endpoint, '해제', '', G]); });
  return getState();
}

// 알림 주소별 마지막 줄이 '등록' 인 것 → [{url, hour}]
function subscriptions_() {
  var last = {};
  rowsG_(pushes_(), 5, 6).forEach(function (r) { last[r[2]] = r; });
  return Object.keys(last).filter(function (u) { return last[u][3] === '등록'; }).map(function (u) {
    return { url: u, name: last[u][1], hour: Core.alarmHour(last[u][4]) || Core.DEFAULT_ALARM_HOUR };
  });
}
function activeEndpoints_() { return subscriptions_().map(function (x) { return x.url; }); }

// ── 아침 알림 ───────────────────────────────────────
// 회장님이 편집기에서 한 번 실행: ▶ setupPush
function setupPush() {
  var props = PropertiesService.getScriptProperties();
  if (!props.getProperty('VAPID_PRIVATE')) {
    var keys = WebPush.newKeys(function () { return Utilities.getUuid(); });
    props.setProperties({ VAPID_PRIVATE: keys.privateKey, VAPID_PUBLIC: keys.publicKey });
  }
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === 'sendMorning') ScriptApp.deleteTrigger(t);
  });
  // 각자 고른 시각에 보내도록 5시~22시 정시마다 하나씩 (프로젝트당 20개 제한 안)
  Core.ALARM_HOURS.forEach(function (h) {
    ScriptApp.newTrigger('sendMorning').timeBased().atHour(h).nearMinute(0).everyDays(1).inTimezone(TZ).create();
  });
  Logger.log('알림 준비 끝. 5시~22시 정시마다 sendMorning 이 돌며 그 시각을 고른 휴대폰에 보냅니다. 알림 받는 휴대폰(모든 모임): ' + allGroups_().reduce(function (n, g) { G = g; return n + activeEndpoints_().length; }, 0) + '대');
  G = '';
}

// 정시마다 트리거가 부릅니다(그 시각을 고른 휴대폰에만). 빈 알림을 보내면 휴대폰이 그날 분량을 계산해 띄웁니다.
function sendMorning() {
  var sent = 0;
  allGroups_().forEach(function (g) { G = g; sent += sendMorningGroup_(); });
  G = '';
  return sent;
}
function allGroups_() { return [''].concat(groups_().map(function (x) { return x.code; })); }
function sendMorningGroup_() {
  var today = today_(), tn = Core.termsNow(terms_(), today);
  if (!tn.cur || !Core.makePlan(tn.cur.start).portionFor(today)) return 0; // 시작 전·끝난 뒤·회차 사이 쉬는 날
  // 지금 회차 참여자에게만
  var who = {};
  Core.TEAMS.forEach(function (team) {
    Core.participants(tn.cur, memberNames_(), joinRows_(), team).forEach(function (m) { who[m] = true; });
  });
  // 트리거는 정시 앞뒤 15분쯤에 돌므로 가장 가까운 정시로 봄 (6:50 → 7시)
  var hm = Utilities.formatDate(new Date(), TZ, 'HH:mm').split(':');
  var hourNow = Math.round((+hm[0] * 60 + +hm[1]) / 60) % 24;
  return push_(subscriptions_().filter(function (x) { return x.hour === hourNow && who[x.name]; }).map(function (x) { return x.url; }));
}

// 시험용 — 회장님이 편집기에서 ▶ testPush. 날짜·시각과 상관없이 알림을 켠 모든 휴대폰에 지금 한 번 보냄.
// (화면에서는 부를 수 없음: doPost 목록에 없음)
function testPush() {
  var urls = [];
  allGroups_().forEach(function (g) { G = g; urls = urls.concat(activeEndpoints_()); });
  G = '';
  Logger.log('알림 켠 휴대폰 ' + urls.length + '대에 시험 알림을 보냅니다.');
  if (!urls.length) Logger.log('알림을 켠 휴대폰이 없습니다. 앱에서 [알림 켜기] 를 먼저 눌러 주세요.');
  return push_(urls);
}

function push_(urls) {
  var props = PropertiesService.getScriptProperties();
  var priv = props.getProperty('VAPID_PRIVATE');
  if (!priv) throw new Error('setupPush 를 먼저 실행해 주세요.');
  var keys = { privateKey: priv, publicKey: props.getProperty('VAPID_PUBLIC') };
  if (!urls.length) return 0;
  var nowSec = Math.floor(Date.now() / 1000);
  var reqs = urls.map(function (u) {
    return {
      url: u, method: 'post', muteHttpExceptions: true,
      headers: { Authorization: WebPush.vapidHeader(u, keys, Core.APP_BASE, nowSec), TTL: '43200', Urgency: 'high' }
    };
  });
  var res = UrlFetchApp.fetchAll(reqs), sent = 0, gone = [];
  res.forEach(function (r, i) {
    var c = r.getResponseCode();
    if (c >= 200 && c < 300) sent++;
    else if (c === 404 || c === 410) gone.push(urls[i]); // 앱을 지웠거나 알림을 끈 휴대폰
    else Logger.log('알림 실패 ' + c + ' ' + urls[i].slice(0, 40) + '… ' + r.getContentText().slice(0, 200));
  });
  if (gone.length) locked_(function () { gone.forEach(function (u) { append_(pushes_(), [now_(), '', u, '만료', '', G]); }); });
  Logger.log('보냄 ' + sent + ' / ' + urls.length + ', 만료 ' + gone.length);
  return sent;
}

// ── 관리자: 회원 완전 삭제 ─────────────────────────
// 시트를 열면 위쪽에 '📖 성경통독' 메뉴가 생깁니다. 시트를 편집할 수 있는 사람(회장님)에게만 보이고,
// 화면(링크)에서는 부를 수 없습니다(doPost 목록에 없음). 회원·기록·알림에서 그 사람 줄을 전부 지웁니다.
function onOpen() {
  SpreadsheetApp.getUi().createMenu('📖 성경통독')
    .addItem('새 모임 만들기… (관리자)', 'newGroupMenu')
    .addItem('모임 링크 보기', 'groupLinksMenu')
    .addSeparator()
    .addItem('새 회차 시작…', 'newTermMenu')
    .addItem('회원 완전 삭제… (관리자)', 'deleteMemberMenu')
    .addToUi();
}

// 모임이 둘 이상이면 어느 모임인지 번호로 고름. 고르면 G 가 정해지고 true.
function pickGroup_(ui, title) {
  var gs = groups_();
  if (!gs.length) { G = ''; return true; }
  var list = [{ code: '', name: (PropertiesService.getScriptProperties().getProperty('GROUP0_NAME') || '처음 모임') }].concat(gs);
  var r = ui.prompt(title + ' — 모임 고르기', list.map(function (x, i) { return (i + 1) + '. ' + x.name; }).join('\n') + '\n\n번호를 적어 주세요.', ui.ButtonSet.OK_CANCEL);
  if (r.getSelectedButton() !== ui.Button.OK) return false;
  var i = parseInt(String(r.getResponseText()).trim(), 10) - 1;
  if (!(i >= 0 && i < list.length)) { ui.alert('번호가 맞지 않습니다.'); return false; }
  G = list[i].code;
  return true;
}

// ── 관리자: 새 모임 ── 이름만 넣으면 그 모임 전용 링크. 처음 모임 이름도 그때 한 번 정함.
function newGroupMenu() {
  var ui = SpreadsheetApp.getUi();
  if (!isOwner_()) { ui.alert('새 모임은 관리자(시트 주인)만 만들 수 있습니다.'); return; }
  var props = PropertiesService.getScriptProperties();
  if (!props.getProperty('GROUP0_NAME')) {
    var r0 = ui.prompt('처음 모임 이름', '지금 쓰고 있는 모임의 이름을 적어 주세요 (예: 1여전도회). 앱 맨 위에 보입니다.', ui.ButtonSet.OK_CANCEL);
    if (r0.getSelectedButton() !== ui.Button.OK) return;
    var n0 = Core.validName(r0.getResponseText());
    if (!n0) { ui.alert('이름은 1~20자로 적어 주세요.'); return; }
    props.setProperties({ GROUP0_NAME: n0 });
  }
  var r = ui.prompt('새 모임 만들기', '새 모임 이름을 적어 주세요 (예: 3여전도회).', ui.ButtonSet.OK_CANCEL);
  if (r.getSelectedButton() !== ui.Button.OK) return;
  var name = Core.validName(r.getResponseText());
  if (!name) { ui.alert('이름은 1~20자로 적어 주세요.'); return; }
  if (groups_().some(function (x) { return x.name === name; }) || props.getProperty('GROUP0_NAME') === name) { ui.alert('이미 있는 모임 이름입니다: ' + name); return; }
  var code = newGroupCode_();
  locked_(function () { append_(groupsSheet_(), [code, name, now_()]); });
  ui.alert('「' + name + '」 모임 링크', '이 링크를 그 모임 단톡방에 보내 주세요.\n\n' + appLink_(code), ui.ButtonSet.OK);
}
function newGroupCode_() {
  var have = {};
  groups_().forEach(function (x) { have[x.code] = true; });
  for (;;) {
    var c = Utilities.getUuid().replace(/[^a-z0-9]/g, '').slice(0, 6);
    if (c.length === 6 && !have[c]) return c;
  }
}
function groupLinksMenu() {
  var ui = SpreadsheetApp.getUi();
  var name0 = PropertiesService.getScriptProperties().getProperty('GROUP0_NAME') || '처음 모임';
  var lines = [name0 + '\n' + appLink_('')].concat(groups_().map(function (x) { return x.name + '\n' + appLink_(x.code); }));
  ui.alert('모임 링크', lines.join('\n\n'), ui.ButtonSet.OK);
}

// 관리자 = 시트 주인. 리더(편집자로 공유받은 사람)는 회차만 열 수 있고 완전 삭제는 못 함.
function isOwner_() {
  try {
    var owner = SpreadsheetApp.getActiveSpreadsheet().getOwner();
    return !!owner && owner.getEmail() === Session.getEffectiveUser().getEmail();
  } catch (e) { return false; }
}

function deleteMemberMenu() {
  var ui = SpreadsheetApp.getUi();
  if (!isOwner_()) { ui.alert('회원 완전 삭제는 관리자(시트 주인)만 할 수 있습니다.'); return; }
  if (!pickGroup_(ui, '회원 완전 삭제')) return;
  var r = ui.prompt('회원 완전 삭제', '지울 이름을 정확히 적어 주세요.', ui.ButtonSet.OK_CANCEL);
  if (r.getSelectedButton() !== ui.Button.OK) return;
  var name = Core.validName(r.getResponseText());
  if (!name || memberNames_().indexOf(name) < 0) { ui.alert('회원 명단에 없는 이름입니다: ' + r.getResponseText()); return; }
  var c = countMember_(name);
  var ok = ui.alert('회원 완전 삭제',
    '「' + name + '」 의 회원 정보, 읽은 기록 ' + c.records + '줄, 알림 ' + c.pushes + '줄을 지웁니다.\n되돌릴 수 없습니다. 지울까요?',
    ui.ButtonSet.YES_NO);
  if (ok !== ui.Button.YES) return;
  var d = deleteMember_(name);
  ui.alert('삭제 완료: ' + name + ' (회원 ' + d.members + '줄, 기록 ' + d.records + '줄, 알림 ' + d.pushes + '줄)');
}

// 그 사람이 등록한 휴대폰 알림 주소 — 이름이 비어 있는 해제·만료 줄도 같이 지우려고
function memberEndpoints_(name) {
  var eps = {};
  rowsG_(pushes_(), 4, 6).forEach(function (r) { if (r[1] === name) eps[r[2]] = true; });
  return eps;
}
function countMember_(name) {
  var eps = memberEndpoints_(name);
  return {
    records: rowsG_(records_(), 4, 5).filter(function (r) { return r[1] === name; }).length,
    pushes: rowsG_(pushes_(), 4, 6).filter(function (r) { return r[1] === name || eps[r[2]]; }).length
  };
}
// 이번 모임 줄 가운데 조건에 맞는 줄을 아래에서부터 지움 (위에서 지우면 줄 번호가 밀림)
function deleteRowsWhere_(sh, gcol, test) {
  var n = sh.getLastRow() - 1, cnt = 0;
  if (n < 1) return 0;
  var rows = sh.getRange(2, 1, n, gcol).getDisplayValues();
  for (var i = rows.length - 1; i >= 0; i--) {
    if ((rows[i][gcol - 1] || '') === G && test(rows[i])) { sh.deleteRow(i + 2); cnt++; }
  }
  return cnt;
}
function deleteMember_(name) {
  return locked_(function () {
    var eps = memberEndpoints_(name);
    return {
      pushes: deleteRowsWhere_(pushes_(), 6, function (r) { return r[1] === name || eps[r[2]]; }),
      records: deleteRowsWhere_(records_(), 5, function (r) { return r[1] === name; }),
      joins: deleteRowsWhere_(joins_(), 6, function (r) { return r[1] === name; }),
      members: deleteRowsWhere_(members_(), 3, function (r) { return r[0] === name; })
    };
  });
}

// ── 리더·관리자: 새 회차 시작 ─────────────────────
// 한 바퀴(약 1년)가 끝나면 리더가 다음 회차 시작일을 정함. 그날 창세기 1장부터 새 읽기표.
// 아직 시작 전인 회차가 있으면 그 날짜를 고침(새로 만들지 않음).
function newTermMenu() {
  var ui = SpreadsheetApp.getUi();
  if (!pickGroup_(ui, '새 회차 시작')) return;
  var terms = terms_(), last = terms[terms.length - 1], today = today_();
  var editing = last.start > today && last.n > 1;
  var n = editing ? last.n : last.n + 1;
  var r = ui.prompt(n + '기 시작일', (editing ? n + '기 시작일(' + last.start + ')을 고칩니다.\n' : '') +
    '시작 날짜를 2028-01-01 처럼 적어 주세요. 그날 창세기 1장부터 시작합니다.', ui.ButtonSet.OK_CANCEL);
  if (r.getSelectedButton() !== ui.Button.OK) return;
  var d = String(r.getResponseText()).trim();
  var err = newTermError_(d, terms, editing, today);
  if (err) { ui.alert(err); return; }
  var p = Core.makePlan(d);
  var ok = ui.alert(n + '기 시작', n + '기: ' + d + ' ~ ' + p.END + ' (' + p.DAY_COUNT + '일)\n' +
    '회원들은 앱에서 「' + n + '기 참여」 를 누르면 함께 읽기에 들어옵니다. 시작할까요?', ui.ButtonSet.YES_NO);
  if (ok !== ui.Button.YES) return;
  setTerm_(n, d, editing);
  ui.alert(n + '기 준비 완료: ' + d + ' 시작');
}
function newTermError_(d, terms, editing, today) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(d) || Core.addDays(d, 0) !== d) return '날짜 모양이 아닙니다: ' + d + ' (예: 2028-01-01)';
  if (d < today) return '오늘보다 앞선 날짜로는 시작할 수 없습니다.';
  var prev = terms[terms.length - (editing ? 2 : 1)];
  if (prev && d <= Core.makePlan(prev.start).END) return prev.n + '기가 ' + Core.makePlan(prev.start).END + ' 에 끝납니다. 그 뒤 날짜로 정해 주세요.';
  return '';
}
function setTerm_(n, d, editing) {
  locked_(function () {
    var sh = termsSheet_();
    if (!rowsG_(sh, 2, 4).length) append_(sh, ['1', Core.FIRST_START, now_(), G]); // 1기를 시트에 먼저 적어 둠
    if (editing) deleteRowsWhere_(sh, 4, function (r) { return +r[0] === n; });
    append_(sh, [String(n), d, now_(), G]);
  });
}
