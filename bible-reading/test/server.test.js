// dist/Code.gs 를 가짜 구글 환경(시트·속성·트리거·UrlFetch)에서 돌려 봅니다.
// 실제 구글에서 돌린 것은 아닙니다 — 우리 코드의 규칙을 확인하는 시험입니다.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const crypto = require('node:crypto');

const CODE = fs.readFileSync(path.join(__dirname, '..', 'dist', 'Code.gs'), 'utf8');
const DEPLOY = 'AKfycbFAKE_deployment_id_for_tests_0123456789';

function makeEnv(todayKST, timeKST) {
  const sheets = {};
  const props = {};
  const triggers = [];
  const who = { email: 'owner@example.com' }; // 지금 메뉴를 누른 사람 (기본: 관리자)
  // 가짜 시트 화면: 메뉴·입력창·확인창
  const ui = {
    menus: [], prompts: [], answers: [], alerts: [],
    Button: { OK: 'OK', CANCEL: 'CANCEL', YES: 'YES', NO: 'NO' },
    ButtonSet: { OK_CANCEL: 'OK_CANCEL', YES_NO: 'YES_NO' },
    createMenu(title) { const m = { title, items: [], addItem(l, f) { m.items.push([l, f]); return m; }, addSeparator() { return m; }, addToUi() { ui.menus.push(m); } }; return m; },
    prompt(t, msg) { ui.prompts.push(msg); const a = ui.answers.shift(); return { getSelectedButton: () => a[0], getResponseText: () => a[1] }; },
    alert(t, msg, btns) { ui.alerts.push(msg || t); if (btns) { const a = ui.answers.shift(); return a[0]; } return 'OK'; },
  };
  const fetched = [];
  let fetchCode = () => 201;
  const clock = new Date(todayKST + 'T' + (timeKST || '07:00') + ':00+09:00');

  function Sheet(name) {
    const rows = [];
    const s = {
      rows,
      getLastRow: () => rows.length,
      setFrozenRows() {},
      deleteRow(r) { rows.splice(r - 1, 1); },
      getRange(r, c, nr, nc) {
        return {
          setValues(v) { v.forEach((row, i) => { const cur = (rows[r - 1 + i] || []).slice(); row.forEach((x, k) => { cur[c - 1 + k] = String(x); }); for (let k = 0; k < cur.length; k++) if (cur[k] === undefined) cur[k] = ''; rows[r - 1 + i] = cur; }); return this; },
          setFontWeight() { return this; },
          setNumberFormat() { return this; },
          getDisplayValues() { return rows.slice(r - 1, r - 1 + nr).map((x) => x.slice(c - 1, c - 1 + nc)); },
        };
      },
    };
    sheets[name] = s;
    return s;
  }
  const g = {
    SpreadsheetApp: {
      getActiveSpreadsheet: () => ({ getSheetByName: (n) => sheets[n] || null, insertSheet: Sheet, getOwner: () => ({ getEmail: () => 'owner@example.com' }) }),
      getUi: () => ui,
    },
    LockService: { getScriptLock: () => ({ waitLock() {}, releaseLock() {} }) },
    Utilities: {
      formatDate(d, tz, fmt) {
        const k = new Date(clock.getTime() + 9 * 3600000).toISOString();
        if (fmt === 'yyyy-MM-dd') return k.slice(0, 10);
        if (fmt === 'HH:mm') return k.slice(11, 16);
        return k.slice(0, 10) + ' ' + k.slice(11, 19);
      },
      getUuid: () => crypto.randomUUID(),
    },
    ContentService: {
      MimeType: { JSON: 'json', ICAL: 'ical' },
      createTextOutput(t) { const o = { text: t, setMimeType(m) { o.mime = m; return o; }, downloadAsFile(f) { o.file = f; return o; } }; return o; },
    },
    PropertiesService: { getScriptProperties: () => ({
      getProperty: (k) => (k in props ? props[k] : null),
      setProperties(o) { Object.assign(props, o); },
    }) },
    ScriptApp: {
      getService: () => ({ getUrl: () => 'https://script.google.com/macros/s/' + DEPLOY + '/exec' }),
      getProjectTriggers: () => triggers.slice(),
      deleteTrigger(t) { triggers.splice(triggers.indexOf(t), 1); },
      newTrigger(fn) {
        const t = { fn, getHandlerFunction: () => fn };
        const b = { timeBased: () => b, atHour(h) { t.hour = h; return b; }, nearMinute(m) { t.minute = m; return b; },
          everyDays(n) { t.every = n; return b; }, inTimezone(z) { t.tz = z; return b; }, create() { triggers.push(t); return t; } };
        return b;
      },
    },
    UrlFetchApp: { fetchAll(reqs) {
      return reqs.map((r) => { fetched.push(r); const c = fetchCode(r.url); return { getResponseCode: () => c, getContentText: () => '' }; });
    } },
    Logger: { log() {} },
    Session: { getEffectiveUser: () => ({ getEmail: () => who.email }) },
  };
  vm.createContext(g);
  vm.runInContext(CODE, g);
  const get = (p) => JSON.parse(g.doGet({ parameter: p || {} }).text);
  const post = (fn, ...args) => JSON.parse(g.doPost({ postData: { contents: JSON.stringify({ fn, args }) } }).text);
  const postG = (grp, fn, ...args) => JSON.parse(g.doPost({ postData: { contents: JSON.stringify({ g: grp, fn, args }) } }).text);
  return { g, sheets, props, triggers, fetched, ui, who, get, post, postG, setFetch: (f) => { fetchCode = f; } };
}

const EP1 = 'https://fcm.googleapis.com/fcm/send/aaa';
const EP2 = 'https://web.push.apple.com/QGbbb';

test('등록 → 완료 → 상태가 시트에서 다시 읽힌다', () => {
  const e = makeEnv('2027-01-05');
  assert.deepEqual(e.get().data.members, []);
  const r = e.post('register', '  김영희 ');
  assert.ok(r.ok);
  assert.equal(r.data.name, '김영희');
  e.post('register', '김영희'); // 같은 이름은 한 번만
  assert.equal(e.sheets['회원'].rows.length, 2);
  const m = e.post('mark', '김영희', '2027-01-05', true);
  assert.ok(m.ok);
  assert.deepEqual(m.data.records, [['김영희', '2027-01-05', '완료']]);
  assert.equal(m.data.today, '2027-01-05');
});

test('미래 날짜·모르는 이름·모르는 요청은 거절하고 시트에 안 쓴다', () => {
  const e = makeEnv('2027-01-05');
  e.post('register', '영희');
  assert.equal(e.post('mark', '영희', '2027-01-06', true).error, '아직 오지 않은 날은 체크할 수 없어요.');
  assert.equal(e.post('mark', '철수', '2027-01-05', true).error, '등록되지 않은 이름입니다.');
  assert.equal(e.post('mark', '영희', '2026-12-31', true).error, '읽기표에 없는 날짜입니다.');
  assert.equal(e.post('setupPush').error, '모르는 요청입니다.', '화면에서 설정 함수를 부를 수 없어야 함');
  assert.equal(e.sheets['기록'].rows.length, 1, '머리줄만 — 거절된 것은 안 씀');
});

test('알림 주소: 알려진 곳만, 해제하면 빠진다', () => {
  const e = makeEnv('2027-01-05');
  e.post('register', '영희');
  assert.ok(!e.post('subscribe', '영희', 'https://evil.example/x').ok);
  assert.ok(e.post('subscribe', '영희', EP1).ok);
  assert.ok(e.post('subscribe', '영희', EP2).ok);
  assert.ok(e.post('unsubscribe', EP1).ok);
  assert.deepEqual([...e.g.activeEndpoints_()], [EP2]);
  assert.equal(e.sheets['알림'].rows.length, 4); // 머리줄 + 등록 2 + 해제 1, 지우지 않음
});

test('setupPush: 키는 속성에만, 트리거는 아침 6시 하나 (두 번 돌려도 하나)', () => {
  const e = makeEnv('2027-01-05');
  assert.equal(e.get().data.vapidKey, '');
  e.g.setupPush();
  const priv = e.props.VAPID_PRIVATE;
  e.g.setupPush();
  assert.equal(e.props.VAPID_PRIVATE, priv, '다시 돌려도 키를 바꾸지 않음 (바꾸면 모든 휴대폰 알림이 끊김)');
  assert.equal(e.triggers.length, 18, '5시~22시 정시마다 하나 (프로젝트당 20개 제한 안)');
  assert.deepEqual(e.triggers.map((t) => t.hour), [5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22]);
  assert.ok(e.triggers.every((t) => t.fn === 'sendMorning' && t.tz === 'Asia/Seoul' && t.minute === 0));
  assert.equal(e.get().data.vapidKey, e.props.VAPID_PUBLIC);
  assert.ok(!JSON.stringify(e.get()).includes(priv), '개인키는 화면으로 안 나감');
});

test('sendMorning: 등록된 휴대폰에만, 검증 가능한 서명으로, 없어진 곳은 만료 기록', () => {
  const e = makeEnv('2027-01-05', '06:00');
  e.g.setupPush();
  e.post('register', '영희');
  e.post('subscribe', '영희', EP1);
  e.post('subscribe', '영희', EP2);
  e.post('subscribe', '영희', 'https://fcm.googleapis.com/fcm/send/off');
  e.post('unsubscribe', 'https://fcm.googleapis.com/fcm/send/off');
  e.setFetch((u) => (u === EP2 ? 410 : 201));
  assert.equal(e.g.sendMorning(), 1);
  assert.deepEqual(e.fetched.map((r) => r.url), [EP1, EP2]);
  const h = e.fetched[0].headers;
  assert.equal(h.TTL, '43200');
  const [, jwt, k] = h.Authorization.match(/^vapid t=([^,]+), k=(.+)$/);
  assert.equal(k, e.props.VAPID_PUBLIC);
  const [hd, pl, sg] = jwt.split('.');
  assert.equal(JSON.parse(Buffer.from(pl, 'base64url')).aud, 'https://fcm.googleapis.com');
  const pub = Buffer.from(k, 'base64url');
  const key = crypto.createPublicKey({ format: 'jwk', key: { kty: 'EC', crv: 'P-256',
    x: pub.subarray(1, 33).toString('base64url'), y: pub.subarray(33).toString('base64url') } });
  assert.ok(crypto.verify('sha256', Buffer.from(hd + '.' + pl), { key, dsaEncoding: 'ieee-p1363' }, Buffer.from(sg, 'base64url')));
  assert.deepEqual([...e.g.activeEndpoints_()], [EP1], '410 받은 곳은 만료');
});

test('sendMorning: 시작 전·끝난 뒤에는 아무것도 안 보냄', () => {
  for (const d of ['2026-12-31', '2027-12-29']) {
    const e = makeEnv(d);
    e.g.setupPush();
    e.post('register', '영희');
    e.post('subscribe', '영희', EP1);
    assert.equal(e.g.sendMorning(), 0);
    assert.equal(e.fetched.length, 0);
  }
});

test('달력 파일 링크는 화면 주소 + 이 배포의 ?s=', () => {
  const e = makeEnv('2027-01-05');
  const o = e.g.doGet({ parameter: { cal: '1' } });
  assert.equal(o.mime, 'ical');
  assert.equal(o.file, 'bible-2027.ics');
  assert.ok(o.text.replace(/\r\n /g, '').includes('URL:https://bing00179.github.io/bing-bing/bible/?s=' + DEPLOY));
});

test('알림 시각: 각자 고른 시각에만 보냄 (트리거가 15분 일찍·늦게 돌아도 가까운 정시로)', () => {
  for (const [time, want] of [['06:50', [EP2]], ['07:14', [EP2]], ['05:46', [EP1]], ['06:10', [EP1]]]) {
    const e = makeEnv('2027-01-05', time);
    e.g.setupPush();
    e.post('register', '영희');
    assert.ok(e.post('subscribe', '영희', EP1).ok, '시각 없으면 6시');
    assert.ok(e.post('subscribe', '영희', EP2, 7).ok);
    e.g.sendMorning();
    assert.deepEqual(e.fetched.map((r) => r.url), want, time);
  }
});

test('알림 시각 바꾸기: 다시 등록하면 새 시각, 잘못된 시각은 거절', () => {
  const e = makeEnv('2027-01-05', '21:05');
  e.g.setupPush();
  e.post('register', '영희');
  e.post('subscribe', '영희', EP1, 6);
  e.post('subscribe', '영희', EP1, 21);
  assert.ok(!e.post('subscribe', '영희', EP2, 3).ok);
  assert.ok(!e.post('subscribe', '영희', EP2, 'x').ok);
  e.g.sendMorning();
  assert.deepEqual(e.fetched.map((r) => r.url), [EP1]);
  assert.equal(e.sheets['알림'].rows[0][4], '알림 시간');
  assert.equal(e.sheets['알림'].rows[2][4], '21');
});

test('달력 파일: ?cal=1&h=21 이면 밤 9시', () => {
  const e = makeEnv('2027-01-05');
  const o = e.g.doGet({ parameter: { cal: '1', h: '21' } });
  assert.ok(o.text.includes('DTSTART:20270101T120000Z'));
  const d = e.g.doGet({ parameter: { cal: '1', h: '99' } });
  assert.ok(d.text.includes('DTSTART:20261231T210000Z'), '이상한 값이면 6시');
});

test('testPush: 시작 전이라도, 시각과 상관없이 알림 켠 모든 휴대폰에 지금 보냄. 화면에서는 못 부름', () => {
  const e = makeEnv('2026-11-11', '14:10');
  e.g.setupPush();
  e.post('register', '영희');
  e.post('subscribe', '영희', EP1, 6);
  e.post('subscribe', '영희', EP2, 21);
  assert.equal(e.g.sendMorning(), 0, '정기 알림은 2027 전에는 안 감');
  assert.equal(e.g.testPush(), 2);
  assert.deepEqual(e.fetched.map((r) => r.url), [EP1, EP2]);
  assert.equal(e.post('testPush').error, '모르는 요청입니다.');
});

test('회원 완전 삭제: 시트 메뉴에만 있고, 그 사람의 회원·기록·알림 줄을 전부 지움 (다른 사람 것은 그대로)', () => {
  const e = makeEnv('2027-01-05', '06:00');
  e.g.setupPush();
  e.post('register', '영희'); e.post('register', '철수');
  e.post('mark', '영희', '2027-01-01', true); e.post('mark', '영희', '2027-01-02', true);
  e.post('mark', '철수', '2027-01-01', true);
  e.post('subscribe', '영희', EP1, 6); e.post('unsubscribe', EP1); e.post('subscribe', '영희', EP1, 7);
  e.post('subscribe', '철수', EP2, 6);
  e.g.onOpen();
  assert.deepEqual(e.ui.menus[0].items.map((x) => x[1]), ['newGroupMenu', 'groupLinksMenu', 'adminPhoneMenu', 'newTermMenu', 'deleteMemberMenu']);
  e.ui.answers.push(['OK', ' 영희 '], ['YES']);
  e.g.deleteMemberMenu();
  assert.ok(e.ui.alerts[0].includes('기록 2줄') && e.ui.alerts[0].includes('알림 3줄'), e.ui.alerts[0]);
  assert.deepEqual(e.sheets['회원'].rows.slice(1).map((r) => r[0]), ['철수']);
  assert.deepEqual(e.sheets['기록'].rows.slice(1).map((r) => r[1]), ['철수']);
  assert.deepEqual(e.sheets['알림'].rows.slice(1).map((r) => r[2]), [EP2], '영희 휴대폰 주소의 해제 줄까지');
  assert.ok(e.ui.alerts[1].includes('삭제 완료'));
  assert.deepEqual([...e.get().data.members], ['철수']);
});

test('회원 완전 삭제: 아니오·취소·없는 이름이면 아무것도 안 지움, 화면(링크)에서는 못 부름', () => {
  const e = makeEnv('2027-01-05');
  e.post('register', '영희'); e.post('mark', '영희', '2027-01-01', true);
  e.ui.answers.push(['OK', '영희'], ['NO']);
  e.g.deleteMemberMenu();
  e.ui.answers.push(['CANCEL', '영희']);
  e.g.deleteMemberMenu();
  e.ui.answers.push(['OK', '없는사람']);
  e.g.deleteMemberMenu();
  assert.ok(e.ui.alerts.some((a) => a.includes('없는 이름')));
  assert.equal(e.sheets['회원'].rows.length, 2);
  assert.equal(e.sheets['기록'].rows.length, 2);
  for (const fn of ['deleteMember_', 'deleteMemberMenu', 'onOpen', 'newTermMenu', 'setTerm_']) assert.equal(e.post(fn, '영희').error, '모르는 요청입니다.');
});

test('리더(편집자)는 회원 완전 삭제를 못 함 — 관리자(시트 주인)만', () => {
  const e = makeEnv('2027-01-05');
  e.post('register', '영희');
  e.who.email = 'leader@example.com';
  e.g.deleteMemberMenu();
  assert.ok(e.ui.alerts[0].includes('관리자'));
  assert.equal(e.ui.prompts.length, 0, '이름도 묻지 않음');
  assert.equal(e.sheets['회원'].rows.length, 2);
});

test('새 회차: 리더가 시작일을 정함 → 2기 읽기표, 참여한 사람만 함께 읽기, 진도는 0부터', () => {
  const e = makeEnv('2027-12-20', '06:00');
  e.g.setupPush();
  e.post('register', '영희'); e.post('register', '철수');
  e.post('mark', '영희', '2027-12-20', true);
  e.who.email = 'leader@example.com'; // 리더도 할 수 있음
  e.ui.answers.push(['OK', '2027-12-25']);
  e.g.newTermMenu();
  assert.ok(e.ui.alerts.pop().includes('끝납니다'), '1기가 끝나기 전 날짜는 거절');
  e.ui.answers.push(['OK', '2028-01-03'], ['YES']);
  e.g.newTermMenu();
  assert.ok(e.ui.alerts.pop().includes('2기 준비 완료'));
  let st = e.get().data;
  assert.deepEqual(st.terms.map((t) => [t.n, t.start]), [[1, '2027-01-01'], [2, '2028-01-03']]);
  // 2기 시작 전 날짜 고치기 (새 회차를 또 만들지 않음)
  e.ui.answers.push(['OK', '2028-01-01'], ['YES']);
  e.g.newTermMenu();
  st = e.get().data;
  assert.deepEqual(st.terms.map((t) => [t.n, t.start]), [[1, '2027-01-01'], [2, '2028-01-01']]);
  // 참여: 영희만, 새로 온 민수는 등록하면 바로 2기
  assert.ok(e.post('join', '영희').ok);
  e.post('join', '영희');
  e.post('register', '민수');
  st = e.get().data;
  assert.deepEqual([...st.joins].map((j) => [...j]), [['영희', '2', '읽기', '참여'], ['민수', '2', '읽기', '참여']]);
  assert.deepEqual([...e.g.Core.participants(st.terms[1], st.members, st.joins)], ['영희', '민수']);
});

test('2기가 시작되면 알림은 2기 참여자에게만, 기록은 2기 날짜로', () => {
  const e = makeEnv('2028-01-01', '06:00');
  e.g.setupPush();
  e.post('register', '영희'); e.post('register', '철수');
  e.post('subscribe', '영희', EP1, 6); e.post('subscribe', '철수', EP2, 6);
  e.ui.answers.push(['OK', '2028-01-01'], ['YES']);
  e.g.newTermMenu();
  e.post('join', '영희');
  assert.equal(e.g.sendMorning(), 1);
  assert.deepEqual(e.fetched.map((r) => r.url), [EP1]);
  assert.ok(e.post('mark', '영희', '2028-01-01', true).ok);
  assert.ok(!e.post('mark', '영희', '2027-12-31', true).ok, '1기와 2기 사이 쉬는 날은 읽기표에 없음');
});

test('완전 삭제는 참여 기록도 지움', () => {
  const e = makeEnv('2027-12-30');
  e.post('register', '영희');
  e.ui.answers.push(['OK', '2028-01-03'], ['YES']);
  e.g.newTermMenu();
  e.post('join', '영희');
  e.ui.answers.push(['OK', '영희'], ['YES']);
  e.g.deleteMemberMenu();
  assert.equal(e.sheets['참여'].rows.length, 1);
});

test('필사 팀: 따로 참여·나가기, 필사 완료 기록, 알림은 두 팀 합쳐서', () => {
  const e = makeEnv('2027-01-05', '06:00');
  e.g.setupPush();
  e.post('register', '영희'); e.post('register', '민수');
  assert.ok(e.post('join', '민수', '필사', true).ok);
  assert.ok(e.post('join', '민수', '읽기', false).ok);          // 민수는 필사만
  assert.ok(e.post('join', '영희', '필사', true).ok);           // 영희는 둘 다
  e.post('join', '영희', '필사', true);                         // 같은 상태면 줄 안 늘어남
  assert.ok(!e.post('join', '영희', '노래', true).ok);
  const st = e.get().data;
  const t1 = st.terms[0];
  assert.deepEqual([...e.g.Core.participants(t1, st.members, st.joins, '읽기')], ['영희']);
  assert.deepEqual([...e.g.Core.participants(t1, st.members, st.joins, '필사')], ['영희', '민수']);
  assert.equal(e.sheets['참여'].rows.length, 4, '머리줄 + 3줄');
  assert.deepEqual([...e.sheets['참여'].rows[0]], ['시각', '이름', '회차', '팀', '동작', '모임']);
  assert.ok(e.post('mark', '민수', '2027-01-05', true, '필사').ok);
  assert.ok(!e.post('mark', '민수', '2027-01-05', true, '그림').ok);
  assert.deepEqual([...e.sheets['기록'].rows.slice(-1)[0].slice(1, 4)], ['민수', '2027-01-05', '필사완료']);
  e.post('subscribe', '민수', EP1, 6);
  assert.equal(e.g.sendMorning(), 1, '필사만 하는 사람도 알림');
});

test('예전 3칸짜리 참여 시트에 팀·동작 제목을 붙임', () => {
  const e = makeEnv('2027-12-30');
  e.post('register', '영희');
  e.ui.answers.push(['OK', '2028-01-03'], ['YES']);
  e.g.newTermMenu();
  e.sheets['참여'] = undefined;
  const sh = e.g.SpreadsheetApp.getActiveSpreadsheet().insertSheet('참여');
  sh.rows.push(['시각', '이름', '회차'], ['x', '영희', '2']);
  const st = e.get().data;
  assert.deepEqual([...e.sheets['참여'].rows[0]], ['시각', '이름', '회차', '팀', '동작', '모임']);
  assert.deepEqual([...e.g.Core.participants(st.terms[1], st.members, st.joins)], ['영희'], '예전 줄 = 읽기 참여');
});

test('시트 칸 제목을 회장님이 고쳐도 서버가 되돌리지 않음 (비어 있을 때만 채움)', () => {
  const e = makeEnv('2027-01-05');
  e.post('register', '영희');
  e.post('subscribe', '영희', EP1, 6);
  e.sheets['알림'].rows[0][4] = '받는 시간';
  e.post('subscribe', '영희', EP1, 7);
  assert.equal(e.sheets['알림'].rows[0][4], '받는 시간');
});

// ── 여러 모임 (한 시트, 링크 끝 &g=코드) ──
function makeGroup(e, name, first) {
  if (first) e.ui.answers.push(['OK', first]);
  e.ui.answers.push(['OK', name]);
  e.g.newGroupMenu();
  const link = e.ui.alerts[e.ui.alerts.length - 1];
  return link.match(/&g=([a-z0-9]+)/)[1];
}

test('새 모임: 관리자만, 처음 모임 이름도 한 번 묻고, 그 모임 전용 링크를 보여 줌', () => {
  const e = makeEnv('2027-01-05');
  e.who.email = 'leader@example.com';
  e.g.newGroupMenu();
  assert.match(e.ui.alerts[0], /관리자/);
  assert.equal(e.sheets['모임'], undefined);
  e.who.email = 'owner@example.com';
  const code = makeGroup(e, '3여전도회', '1여전도회');
  assert.equal(e.props.GROUP0_NAME, '1여전도회');
  assert.match(e.ui.alerts[e.ui.alerts.length - 1], new RegExp('\\?s=' + DEPLOY + '&g=' + code));
  // 두 번째부터는 처음 모임 이름을 다시 묻지 않음, 같은 이름은 거절
  const n = e.ui.prompts.length;
  e.ui.answers.push(['OK', '3여전도회']);
  e.g.newGroupMenu();
  assert.equal(e.ui.prompts.length, n + 1);
  assert.match(e.ui.alerts[e.ui.alerts.length - 1], /이미 있는/);
  assert.equal(e.sheets['모임'].rows.length, 2);
});

test('모임끼리 명단·기록·참여가 섞이지 않고, 예전 링크(모임 없음)는 그대로', () => {
  const e = makeEnv('2027-01-05');
  e.post('register', '영희');
  e.post('mark', '영희', '2027-01-05', true);
  const code = makeGroup(e, '3여전도회', '1여전도회');
  const r = e.postG(code, 'register', '영희'); // 같은 이름이어도 다른 모임이면 다른 사람
  assert.ok(r.ok);
  assert.deepEqual(r.data.records, []);
  assert.equal(r.data.groupName, '3여전도회');
  e.postG(code, 'register', '순자');
  e.postG(code, 'mark', '순자', '2027-01-04', true);
  const a = e.get(), b = e.get({ g: code });
  assert.deepEqual(a.data.members, ['영희']);
  assert.deepEqual(a.data.records, [['영희', '2027-01-05', '완료']]);
  assert.equal(a.data.groupName, '1여전도회');
  assert.deepEqual(b.data.members, ['영희', '순자']);
  assert.deepEqual(b.data.records, [['순자', '2027-01-04', '완료']]);
  assert.equal(e.post('mark', '순자', '2027-01-05', true).error, '등록되지 않은 이름입니다.', '다른 모임 사람은 기록 못 함');
  assert.match(e.get({ g: 'zzzzzz' }).error, /모르는 모임/);
  assert.match(e.postG('zzzzzz', 'register', 'x').error, /모르는 모임/);
  assert.equal(e.sheets['회원'].rows.length, 4, '모르는 모임으로는 아무것도 안 씀');
});

test('새 회차·회원 삭제는 모임을 먼저 고르고, 그 모임 것만 바꿈', () => {
  const e = makeEnv('2027-01-05');
  e.post('register', '영희');
  const code = makeGroup(e, '3여전도회', '1여전도회');
  e.postG(code, 'register', '영희');
  e.postG(code, 'mark', '영희', '2027-01-05', true);
  // 삭제: 2번(3여전도회) 고르기 → 이름 → 예
  e.ui.answers.push(['OK', '2'], ['OK', '영희'], ['YES']);
  e.g.deleteMemberMenu();
  assert.deepEqual(e.get({ g: code }).data.members, []);
  assert.deepEqual(e.get().data.members, ['영희'], '처음 모임의 영희는 그대로');
  // 새 회차: 2번 고르기 → 날짜
  e.ui.answers.push(['OK', '2'], ['OK', '2028-01-03'], ['YES']);
  e.g.newTermMenu();
  assert.equal(e.get({ g: code }).data.terms.length, 2);
  assert.equal(e.get().data.terms.length, 1);
  // 취소하면 아무것도 안 함
  e.ui.answers.push(['CANCEL', '']);
  e.g.newTermMenu();
  assert.equal(e.get().data.terms.length, 1);
});

test('아침 알림은 모든 모임에 감 (모임마다 자기 회차 기준)', () => {
  const e = makeEnv('2027-01-05', '06:00');
  e.g.setupPush();
  e.post('register', '영희');
  e.post('subscribe', '영희', EP1, 6);
  const code = makeGroup(e, '3여전도회', '1여전도회');
  e.postG(code, 'register', '순자');
  e.postG(code, 'subscribe', '순자', EP2, 6);
  assert.deepEqual(e.get().data.members, ['영희']);
  e.g.sendMorning();
  const urls = e.fetched.map((r) => r.url).sort();
  assert.deepEqual(urls, [EP1, EP2].sort());
});

test('관리자 폰: 시트 주인 메뉴로 받은 열쇠가 있어야만 앱에서 모임을 만듦, 다시 등록하면 예전 열쇠는 안 됨', () => {
  const e = makeEnv('2027-01-05');
  assert.match(e.post('adminInfo', '').error, /관리자 폰이 아닙니다/, '등록 전에는 누구도 안 됨');
  e.who.email = 'leader@example.com';
  e.g.adminPhoneMenu();
  assert.equal(e.props.ADMIN_KEY, undefined, '리더는 등록 못 함');
  e.who.email = 'owner@example.com';
  e.ui.answers.push(['YES']);
  e.g.adminPhoneMenu();
  const key = e.props.ADMIN_KEY;
  assert.match(key, /^[a-f0-9]{32}$/);
  assert.ok(e.ui.alerts.some((a) => a.includes('&admin=' + key) && a.includes('?s=' + DEPLOY)));
  assert.match(e.post('adminInfo', 'x'.repeat(32)).error, /관리자 폰이 아닙니다/);
  // 처음 모임 이름 → 새 모임
  assert.match(e.post('adminNewGroup', key, '29여 아비가일').error, /처음 모임 이름/);
  assert.equal(e.post('adminSetGroup0', key, '30여 로데').data.groups[0].name, '30여 로데');
  const r = e.post('adminNewGroup', key, '29여 아비가일');
  assert.equal(r.data.groups.length, 2);
  assert.equal(r.data.groups[1].name, '29여 아비가일');
  assert.match(r.data.groups[1].link, new RegExp('\\?s=' + DEPLOY + '&g=' + r.data.groups[1].code + '$'));
  assert.equal(r.data.groups[0].link.includes('&g='), false);
  assert.match(e.post('adminNewGroup', key, '29여 아비가일').error, /이미 있는/);
  assert.equal(e.get({ g: r.data.groups[1].code }).data.groupName, '29여 아비가일');
  assert.equal(e.get().data.groupName, '30여 로데');
  // 다시 등록 → 예전 열쇠 무효
  e.ui.answers.push(['YES']);
  e.g.adminPhoneMenu();
  assert.match(e.post('adminInfo', key).error, /관리자 폰이 아닙니다/);
  assert.ok(e.post('adminInfo', e.props.ADMIN_KEY).ok);
  // 아니오면 그대로
  const k2 = e.props.ADMIN_KEY;
  e.ui.answers.push(['NO']);
  e.g.adminPhoneMenu();
  assert.equal(e.props.ADMIN_KEY, k2);
});
