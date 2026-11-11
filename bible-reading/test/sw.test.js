// sw.js(알림 띄우는 곳)를 가짜 서비스워커 환경에서 돌립니다.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const SITE = path.join(__dirname, '..', '..', 'bible');

function load(nowKST, search) {
  const handlers = {};
  const shown = [];
  const opened = [];
  const self = {
    location: { search },
    registration: { scope: 'https://bing00179.github.io/bing-bing/bible/',
      showNotification: (t, o) => { shown.push([t, o]); return Promise.resolve(); } },
    clients: { matchAll: () => Promise.resolve([]), openWindow: (u) => { opened.push(u); return Promise.resolve(); }, claim: () => Promise.resolve() },
    addEventListener: (k, f) => { handlers[k] = f; },
    skipWaiting() {},
  };
  const RealDate = Date;
  const fixed = new RealDate(nowKST.replace(' ', 'T') + ':00+09:00').getTime();
  class FakeDate extends RealDate { constructor(...a) { super(...(a.length ? a : [fixed])); } static now() { return fixed; } }
  const ctx = { self, URL, Date: FakeDate, Promise };
  ctx.importScripts = (f) => vm.runInContext(fs.readFileSync(path.join(SITE, f), 'utf8'), ctx);
  vm.createContext(ctx);
  vm.runInContext(fs.readFileSync(path.join(SITE, 'sw.js'), 'utf8'), ctx);
  return { handlers, shown, opened };
}

async function push(env) {
  let p; env.handlers.push({ waitUntil: (x) => { p = x; } }); await p;
}

test('아침 6시 알림: 그날 분량을 띄운다 (한국 날짜 기준)', async () => {
  const e = load('2027-01-03 06:00', '?s=ABC');
  await push(e);
  assert.equal(e.shown.length, 1);
  assert.equal(e.shown[0][0], '📖 오늘 읽을 곳');
  assert.equal(e.shown[0][1].body, '창세기 7~11장');
  assert.equal(e.shown[0][1].tag, 'bible-2027-01-03');
});

test('한국 새벽(UTC 로는 전날)에도 한국 날짜를 쓴다', async () => {
  const e = load('2027-01-02 00:30', '?s=ABC'); // UTC 1월 1일 15:30
  await push(e);
  assert.equal(e.shown[0][1].body, '창세기 4~6장');
});

test('읽기표 밖이어도 알림은 반드시 띄운다 (아이폰은 안 띄우면 권한이 끊김)', async () => {
  const e = load('2028-01-02 06:00', '?s=ABC');
  await push(e);
  assert.equal(e.shown.length, 1);
  assert.equal(e.shown[0][1].body, '함께 읽는 성경');
});

test('알림을 누르면 ?s= 가 붙은 앱 주소로 연다', async () => {
  const e = load('2027-01-03 06:00', '?s=ABC');
  await push(e);
  let p, closed = false;
  e.handlers.notificationclick({ notification: { data: e.shown[0][1].data, close: () => { closed = true; } }, waitUntil: (x) => { p = x; } });
  await p;
  assert.ok(closed);
  assert.deepEqual(e.opened, ['https://bing00179.github.io/bing-bing/bible/?s=ABC']);
});
