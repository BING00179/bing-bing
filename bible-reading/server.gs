// 성경통독 — 앱스 스크립트 서버. build.js 가 이 파일 앞에 core.js 를 붙여
// dist/Code.gs 를 만듭니다. 시트 주소나 배포 주소는 여기 적지 않습니다(공개 저장소).
//
// 시트 두 장 (없으면 처음 열 때 만듦)
//   회원   이름 | 등록 시각
//   기록   시각 | 이름 | 날짜 | 동작(완료/취소)   ← 지우지 않고 덧쌓기만

var TZ = 'Asia/Seoul';

function doGet() {
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
  return { today: today_(), members: names, records: recs };
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
