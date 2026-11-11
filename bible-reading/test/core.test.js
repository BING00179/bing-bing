// 시험: node --test bible-reading/test
const test = require('node:test');
const assert = require('node:assert/strict');
const C = require('../core.js');

function* days(from, to) {
  for (let d = from; d <= to; d = C.addDays(d, 1)) yield d;
}

test('66권, 1,189장', () => {
  assert.equal(C.BOOKS.length, 66);
  assert.equal(C.BOOKS.reduce((s, b) => s + b[1], 0), 1189);
  assert.equal(C.TOTAL, 1189);
});

test('시작 전·끝난 뒤는 분량 없음', () => {
  assert.equal(C.portionFor('2026-12-31'), null);
  assert.equal(C.portionFor('2027-12-29'), null);
  assert.equal(C.END, '2027-12-28');
});

test('첫날(금) 창세기 1~3, 첫 주일 창세기 7~11', () => {
  assert.equal(C.portionLabel(C.portionFor('2027-01-01')), '창세기 1~3장');
  assert.equal(C.portionLabel(C.portionFor('2027-01-02')), '창세기 4~6장');
  assert.equal(C.portionLabel(C.portionFor('2027-01-03')), '창세기 7~11장');
});

test('모든 장이 정확히 한 번씩, 순서대로', () => {
  const seen = [];
  for (const d of days(C.START, C.END)) {
    const p = C.portionFor(d);
    assert.ok(p, d);
    for (let i = p.from; i <= p.to; i++) seen.push(i);
  }
  assert.equal(seen.length, 1189);
  seen.forEach((v, i) => assert.equal(v, i));
});

test('주일 5장, 그 밖 3장 (마지막 날만 2장)', () => {
  for (const d of days(C.START, C.addDays(C.END, -1))) {
    const p = C.portionFor(d);
    const sunday = new Date(d + 'T00:00:00Z').getUTCDay() === 0;
    assert.equal(p.to - p.from + 1, sunday ? 5 : 3, d);
  }
  assert.equal(C.portionLabel(C.portionFor(C.END)), '요한계시록 21~22장');
});

test('분량 이름: 한 장, 권을 넘는 경우', () => {
  const idx = (book, ch) => C.chapterIndex(book, ch);
  assert.equal(C.portionLabel({ from: idx('오바댜', 1), to: idx('오바댜', 1) }), '오바댜 1장');
  assert.equal(C.portionLabel({ from: idx('창세기', 50), to: idx('출애굽기', 2) }), '창세기 50장 ~ 출애굽기 2장');
});

test('기록: 마지막 줄이 상태, 다른 사람 것은 안 섞임', () => {
  const recs = [
    ['영희', '2027-01-01', '완료'],
    ['철수', '2027-01-02', '완료'],
    ['영희', '2027-01-02', '완료'],
    ['영희', '2027-01-02', '취소'],
    ['영희', '2027-01-03', '완료'],
    ['영희', '2027-01-03', '완료'],
  ];
  assert.deepEqual([...C.doneSet(recs, '영희')].sort(), ['2027-01-01', '2027-01-03']);
  assert.deepEqual([...C.doneSet(recs, '철수')], ['2027-01-02']);
  assert.equal(C.doneSet(recs, '없는사람').size, 0);
});

test('진도율: 장 수 합 / 1,189', () => {
  const p = C.progress(new Set(['2027-01-01', '2027-01-02', '2027-01-03']));
  assert.equal(p.chapters, 11);
  assert.equal(p.percent, 0.9);
  assert.equal(C.progress(new Set()).chapters, 0);
  const all = new Set(days(C.START, C.END));
  assert.deepEqual(C.progress(all), { chapters: 1189, percent: 100 });
});

test('밀린 날: 오늘은 안 셈, 어제는 셈, 시작 전 0, 끝 뒤 안 늘어남', () => {
  const none = new Set();
  assert.equal(C.missedDays(none, '2026-11-11'), 0);
  assert.equal(C.missedDays(none, '2027-01-01'), 0);
  assert.equal(C.missedDays(none, '2027-01-02'), 1);
  assert.equal(C.missedDays(new Set(['2027-01-01']), '2027-01-02'), 0);
  assert.equal(C.missedDays(new Set(['2027-01-02']), '2027-01-03'), 1);
  assert.equal(C.missedDays(none, '2027-12-29'), 362);
  assert.equal(C.missedDays(none, '2028-03-01'), 362);
  assert.equal(C.missedDays(new Set(['2027-01-01']), '2028-03-01'), 361);
});

test('어디까지: 가장 늦은 완료 날의 끝 장', () => {
  assert.equal(C.lastReadLabel(new Set()), '');
  assert.equal(C.lastReadLabel(new Set(['2027-01-03', '2027-01-01'])), '창세기 11장까지');
});

test('이름: 공백 정리, 1~20자', () => {
  assert.equal(C.validName('  김 영희 '), '김 영희');
  assert.equal(C.validName('   '), null);
  assert.equal(C.validName('가'.repeat(21)), null);
  assert.equal(C.validName(null), null);
});

test('날짜 더하기는 시간대와 무관', () => {
  assert.equal(C.addDays('2027-12-31', 1), '2028-01-01');
  assert.equal(C.addDays('2027-03-01', -1), '2027-02-28');
});
