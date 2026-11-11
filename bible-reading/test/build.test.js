const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { build } = require('../build.js');

const out = build();
const core = fs.readFileSync(path.join(__dirname, '..', 'core.js'), 'utf8');

test('붙여넣기 파일 둘에 core 가 들어 있다', () => {
  assert.ok(out.code.includes('var BOOKS = ['));
  assert.ok(out.code.includes('function getState()'));
  assert.ok(out.index.includes('var BOOKS = ['));
  assert.ok(!out.index.includes('/*CORE*/'));
  assert.ok(!out.code.includes('module.exports'), '앱스 스크립트에는 module 이 없음');
});

test('미리보기는 가짜 서버를 쓰고 진짜와 같은 화면', () => {
  assert.ok(out.preview.includes('google = '));
  assert.ok(out.preview.includes('함께 읽는 성경'));
});

test('공개 저장소 — 시트·배포 주소가 들어가지 않는다', () => {
  for (const s of [out.code, out.index, out.preview, core]) {
    assert.ok(!/docs\.google\.com\/spreadsheets\/d\//.test(s));
    assert.ok(!/script\.google\.com\/macros\/s\//.test(s));
  }
});

test('가짜 서버도 미래 날짜를 막는다 (진짜와 같은 규칙)', () => {
  assert.ok(out.preview.includes('아직 오지 않은 날은 체크할 수 없어요.'));
});

test('저장소의 dist 가 최신이다 (node bible-reading/build.js 를 잊지 않게)', () => {
  const dist = path.join(__dirname, '..', 'dist');
  assert.equal(fs.readFileSync(path.join(dist, 'Code.gs'), 'utf8'), out.code);
  assert.equal(fs.readFileSync(path.join(dist, 'Index.html'), 'utf8'), out.index);
  assert.equal(fs.readFileSync(path.join(dist, 'preview.html'), 'utf8'), out.preview);
});
