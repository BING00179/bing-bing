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
  const fetched = [];
  let fetchCode = () => 201;
  const clock = new Date(todayKST + 'T' + (timeKST || '07:00') + ':00+09:00');

  function Sheet(name) {
    const rows = [];
    const s = {
      rows,
      getLastRow: () => rows.length,
      setFrozenRows() {},
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
    SpreadsheetApp: { getActiveSpreadsheet: () => ({ getSheetByName: (n) => sheets[n] || null, insertSheet: Sheet }) },
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
  };
  vm.createContext(g);
  vm.runInContext(CODE, g);
  const get = (p) => JSON.parse(g.doGet({ parameter: p || {} }).text);
  const post = (fn, ...args) => JSON.parse(g.doPost({ postData: { contents: JSON.stringify({ fn, args }) } }).text);
  return { g, sheets, props, triggers, fetched, get, post, setFetch: (f) => { fetchCode = f; } };
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
