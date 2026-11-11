// 개역개정 링크 시험 — 본문은 저작권 때문에 앱에 넣지 않고 대한성서공회 웹사이트로 연결
const test = require('node:test');
const assert = require('node:assert/strict');
const C = require('../core.js');

test('그날 장 목록과 개역개정 링크 (확인된 주소 형식)', () => {
  const list = C.chaptersOf(C.portionFor('2027-01-03'));
  assert.deepEqual(list.map((x) => x.chapter), [7, 8, 9, 10, 11]);
  assert.equal(list[0].book, 1);
  assert.equal(list[0].gae, 'https://www.bskorea.or.kr/bible/korbibReadpage.php?version=GAE&book=gen&chap=7');
  assert.equal(C.GAE_CODES.length, 66);
  assert.equal(new Set(C.GAE_CODES).size, 66);
  // 실제 주소로 확인한 넷
  assert.equal(C.GAE_CODES[0], 'gen');
  assert.equal(C.GAE_CODES[25], 'ezk');
  assert.equal(C.GAE_CODES[42], 'jhn');
  assert.equal(C.GAE_CODES[61], '1jn');
});

test('권을 넘는 날도 장 목록이 이어진다', () => {
  const i = C.chapterIndex('창세기', 50);
  const list = C.chaptersOf({ from: i, to: i + 2 });
  assert.deepEqual(list.map((x) => x.name + x.chapter), ['창세기50', '출애굽기1', '출애굽기2']);
});

test('개역한글 본문은 앱에 없다 (사장님 결정 2026-11-11: 혼선 방지)', () => {
  const fs = require('node:fs'), path = require('node:path');
  assert.ok(!fs.existsSync(path.join(__dirname, '..', '..', 'bible', 'text')));
});
