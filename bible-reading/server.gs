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
