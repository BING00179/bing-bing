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
    createMenu(title) { const m = { title, items: [], addItem(l, f) { m.items.push([l, f]); return m; }, addToUi() { ui.menus.push(m); } }; return m; },
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
          setValues(v) { v.forEach((row, i) => { rows[r - 1 + i] = row.map(String); }); return this; },
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
  return { g, sheets, props, triggers, fetched, ui, who, get, post, setFetch: (f) => { fetchCode = f; } };
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
  assert.equal(e.sheets['알림'].rows[0][4], '알림 시각');
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
  assert.deepEqual(e.ui.menus[0].items.map((x) => x[1]), ['newTermMenu', 'deleteMemberMenu']);
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
  assert.deepEqual([...st.joins].map((j) => [...j]), [['영희', '2'], ['민수', '2']]);
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
