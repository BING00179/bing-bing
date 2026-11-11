// 앱 안 본문(개역한글) 파일과 개역개정 링크 시험
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const C = require('../core.js');

const DIR = path.join(__dirname, '..', '..', 'bible', 'text');
const book = (n) => JSON.parse(fs.readFileSync(path.join(DIR, String(n).padStart(2, '0') + '.json'), 'utf8'));

test('66권 파일, 장 수가 읽기표와 같고 빈 절이 없다', () => {
  let verses = 0;
  C.BOOKS.forEach(([name, chapters], i) => {
    const b = book(i + 1);
    assert.equal(b.c.length, chapters, name);
    for (const ch of b.c) {
      assert.ok(ch.length > 0, name);
      for (const v of ch) assert.ok(typeof v === 'string' && v.trim().length > 0, name);
      verses += ch.length;
    }
  });
  assert.equal(verses, 31101);
});

test('처음과 끝 절이 개역한글 그대로', () => {
  assert.equal(book(1).c[0][0], '태초에 하나님이 천지를 창조하시니라');
  assert.equal(book(66).c[21][20], '주 예수의 은혜가 모든 자들에게 있을찌어다 아멘');
  assert.equal(book(1).b, '창세기');
});

test('출처 파일이 있다', () => {
  const s = fs.readFileSync(path.join(DIR, 'SOURCE.md'), 'utf8');
  assert.ok(s.includes('개역한글판'));
  assert.ok(s.includes('fd40780326e24efe9e16efb775db39ddf6f5d0980a97344de618533d5a6663c1'));
});

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
