// 성경통독 — 앱스 스크립트 서버(기록·알림 담당). 화면은 GitHub Pages 에 있습니다.
// build.js 가 core.js·webpush.js 를 앞에 붙여 dist/Code.gs 를 만듭니다.
// 시트 주소·배포 주소·알림 개인키는 저장소에 적지 않습니다(공개 저장소).
//   개인키는 setupPush() 가 만들어 '스크립트 속성'에만 둡니다.
//
// 시트 세 장 (없으면 처음 쓸 때 만듦) — 전부 지우지 않고 덧쌓기만
//   회원   이름 | 등록 시각
//   기록   시각 | 이름 | 날짜 | 동작(완료/취소)
//   알림   시각 | 이름 | 알림 주소 | 동작(등록/해제/만료)

var TZ = 'Asia/Seoul';

// ── 문 ─────────────────────────────────────────────
function doGet(e) {
  var p = (e && e.parameter) || {};
  if (p.cal) {
    // 매일 아침 6시 알림이 들어 있는 달력 파일
    return ContentService.createTextOutput(Core.icsFor(appLink_(), p.h))
      .setMimeType(ContentService.MimeType.ICAL)
      .downloadAsFile('bible-2027.ics');
  }
  return json_(function () { return getState(); });
}

// 화면은 text/plain 으로 {"fn": "...", "args": [...]} 를 보냅니다 (CORS 사전 요청을 피함).
function doPost(e) {
  return json_(function () {
    var req = JSON.parse(e.postData.contents);
    var fns = { register: register, mark: mark, subscribe: subscribe, unsubscribe: unsubscribe };
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
function members_() { return sheet_('회원', ['이름', '등록 시각']); }
function records_() { return sheet_('기록', ['시각', '이름', '날짜', '동작']); }
function pushes_() {
  var sh = sheet_('알림', ['시각', '이름', '알림 주소', '동작', '알림 시각']);
  // 시각 고르기 전에 만든 시트에는 다섯째 칸 제목이 없음
  if (sh.getRange(1, 5, 1, 1).getDisplayValues()[0][0] !== '알림 시각') sh.getRange(1, 5, 1, 1).setValues([['알림 시각']]);
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
function memberNames_() { return rows_(members_(), 1).map(function (r) { return r[0]; }).filter(String); }

// 이 배포의 주소 조각(…/macros/s/<여기>/exec) → 화면 주소 뒤에 붙임
function deploymentId_() {
  var m = String(ScriptApp.getService().getUrl()).match(/\/s\/([A-Za-z0-9_-]+)\//);
  return m ? m[1] : '';
}
function appLink_() { return Core.APP_BASE + '?s=' + deploymentId_(); }

// ── 화면이 부르는 것 ────────────────────────────────
function getState() {
  var recs = rows_(records_(), 4).map(function (r) { return [r[1], r[2], r[3]]; });
  var pub = PropertiesService.getScriptProperties().getProperty('VAPID_PUBLIC') || '';
  return { today: today_(), members: memberNames_(), records: recs, vapidKey: pub };
}

function register(name) {
  var n = Core.validName(name);
  if (!n) throw new Error('이름은 1~20자로 적어 주세요.');
  locked_(function () {
    if (memberNames_().indexOf(n) < 0) append_(members_(), [n, now_()]);
  });
  var s = getState();
  s.name = n;
  return s;
}

function mark(name, date, done) {
  if (!Core.portionFor(date)) throw new Error('읽기표에 없는 날짜입니다.');
  if (date > today_()) throw new Error('아직 오지 않은 날은 체크할 수 없어요.');
  locked_(function () {
    if (memberNames_().indexOf(name) < 0) throw new Error('등록되지 않은 이름입니다.');
    append_(records_(), [now_(), name, date, done ? '완료' : '취소']);
  });
  return getState();
}

function subscribe(name, endpoint, hour) {
  if (!WebPush.allowedEndpoint(endpoint)) throw new Error('이 휴대폰의 알림 주소를 받을 수 없어요.');
  var h = hour === undefined || hour === null || hour === '' ? Core.DEFAULT_ALARM_HOUR : Core.alarmHour(hour);
  if (h === null) throw new Error('알림 시각은 5시~22시 정시로 골라 주세요.');
  locked_(function () {
    if (memberNames_().indexOf(name) < 0) throw new Error('등록되지 않은 이름입니다.');
    append_(pushes_(), [now_(), name, endpoint, '등록', String(h)]);
  });
  return getState();
}

function unsubscribe(endpoint) {
  if (!WebPush.allowedEndpoint(endpoint)) throw new Error('이 휴대폰의 알림 주소를 받을 수 없어요.');
  locked_(function () { append_(pushes_(), [now_(), '', endpoint, '해제']); });
  return getState();
}

// 알림 주소별 마지막 줄이 '등록' 인 것 → [{url, hour}]
function subscriptions_() {
  var last = {};
  rows_(pushes_(), 5).forEach(function (r) { last[r[2]] = r; });
  return Object.keys(last).filter(function (u) { return last[u][3] === '등록'; }).map(function (u) {
    return { url: u, hour: Core.alarmHour(last[u][4]) || Core.DEFAULT_ALARM_HOUR };
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
  Logger.log('알림 준비 끝. 5시~22시 정시마다 sendMorning 이 돌며 그 시각을 고른 휴대폰에 보냅니다. 알림 받는 휴대폰: ' + activeEndpoints_().length + '대');
}

// 정시마다 트리거가 부릅니다(그 시각을 고른 휴대폰에만). 빈 알림을 보내면 휴대폰이 그날 분량을 계산해 띄웁니다.
function sendMorning() {
  if (!Core.portionFor(today_())) return 0; // 시작 전·끝난 뒤
  var props = PropertiesService.getScriptProperties();
  var priv = props.getProperty('VAPID_PRIVATE');
  if (!priv) throw new Error('setupPush 를 먼저 실행해 주세요.');
  var keys = { privateKey: priv, publicKey: props.getProperty('VAPID_PUBLIC') };
  // 트리거는 정시 앞뒤 15분쯤에 돌므로 가장 가까운 정시로 봄 (6:50 → 7시)
  var hm = Utilities.formatDate(new Date(), TZ, 'HH:mm').split(':');
  var hourNow = Math.round((+hm[0] * 60 + +hm[1]) / 60) % 24;
  var urls = subscriptions_().filter(function (x) { return x.hour === hourNow; }).map(function (x) { return x.url; });
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
  if (gone.length) locked_(function () { gone.forEach(function (u) { append_(pushes_(), [now_(), '', u, '만료']); }); });
  Logger.log('보냄 ' + sent + ' / ' + urls.length + ', 만료 ' + gone.length);
  return sent;
}
