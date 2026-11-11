const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { build, site } = require('../build.js');

const out = build();
const text = (f) => out.files[f].toString('utf8');

test('Code.gs 에 core·webpush·server 가 다 들어 있고 module 은 없다', () => {
  assert.ok(out.code.includes('var BOOKS = ['));
  assert.ok(out.code.includes('function signES256'));
  assert.ok(out.code.includes('function doPost(e)'));
  assert.ok(out.code.includes('function sendMorning()'));
  assert.ok(!out.code.includes('module.exports'), '앱스 스크립트에는 module 이 없음');
});

test('화면은 core.js·api.js 를 불러오고, sw.js 도 core.js 를 쓴다', () => {
  assert.ok(text('index.html').includes('<script src="core.js"></script>'));
  assert.ok(text('index.html').includes('<script src="api.js"></script>'));
  assert.ok(text('sw.js').includes("importScripts('core.js')"));
  assert.ok(text('index.html').includes('rel="manifest"'));
});

test('홈 화면 앱이 ?s= 를 잃지 않게 manifest 에 start_url 을 두지 않는다', () => {
  // start_url 이 없으면 '추가한 그 페이지 주소'(링크의 ?s= 포함)로 열립니다.
  const m = JSON.parse(text('manifest.webmanifest'));
  assert.equal(m.start_url, undefined);
  assert.equal(m.display, 'standalone');
});

test('공개 저장소 — 배포 주소·시트 주소·개인키가 들어가지 않는다', () => {
  const all = [out.code, ...Object.keys(out.files).filter((f) => !f.endsWith('.png')).map(text)];
  for (const s of all) {
    assert.ok(!/docs\.google\.com\/spreadsheets\/d\//.test(s));
    assert.ok(!/script\.google\.com\/macros\/s\/[A-Za-z0-9_-]{20,}/.test(s), '배포 아이디가 박혀 있음');
    assert.ok(!/VAPID_PRIVATE['"]?\s*[:=]\s*['"][A-Za-z0-9_-]{30,}/.test(s), '개인키가 박혀 있음');
  }
});

test('저장소의 결과물이 최신이다 (node bible-reading/build.js 를 잊지 않게)', () => {
  assert.equal(fs.readFileSync(path.join(__dirname, '..', 'dist', 'Code.gs'), 'utf8'), out.code);
  for (const [f, buf] of Object.entries(out.files)) {
    assert.ok(fs.readFileSync(path.join(site, f)).equals(buf), 'bible/' + f + ' 이 옛것');
  }
});

test('앱스 스크립트가 못 읽는 BigInt 표기(0n)가 Code.gs 에 없다', () => {
  // 2026-11-11 실제 편집기에서 'Unexpected token ILLEGAL 라인 283' 으로 저장이 막혔던 것
  const code = out.code.replace(/\/\/[^\n]*/g, '').replace(/'(?:\\.|[^'\\\n])*'/g, "''");
  assert.ok(!/\b(0x[0-9a-fA-F]+|\d+)n\b/.test(code), code.match(/\b(0x[0-9a-fA-F]+|\d+)n\b/));
});
