// 회차(한 번 통독 = 한 회차) 시험
const test = require('node:test');
const assert = require('node:assert/strict');
const C = require('../core.js');

test('시작일만 바꾸면 그날 창세기 1장부터 새 읽기표 (주일 5장·그 밖 3장, 1,189장 전부)', () => {
  const p = C.makePlan('2028-01-01'); // 토요일
  assert.equal(C.portionLabel(p.portionFor('2028-01-01')), '창세기 1~3장');
  assert.equal(C.portionLabel(p.portionFor('2028-01-02')), '창세기 4~8장', '주일 5장');
  assert.equal(p.portionFor('2027-12-31'), null);
  let n = 0;
  for (let d = p.START; d <= p.END; d = C.addDays(d, 1)) { const x = p.portionFor(d); n += x.to - x.from + 1; }
  assert.equal(n, 1189);
  assert.equal(C.portionLabel(p.portionFor(p.END)).startsWith('요한계시록'), true);
});

test('회차마다 진도·밀린 날은 0부터 (지난 회차 기록은 안 셈)', () => {
  const p2 = C.makePlan('2028-01-03');
  const recs = [['영희', '2027-03-01', '완료'], ['영희', '2028-01-03', '완료']];
  assert.equal(p2.doneSet(recs, '영희').size, 1);
  assert.equal(p2.progress(p2.doneSet(recs, '영희')).chapters, 3);
  assert.equal(p2.missedDays(new Set(), '2028-01-03'), 0);
  assert.equal(C.doneSet(recs, '영희').size, 1, '1기는 1기 날짜만');
});

test('회차 목록: 시트가 비면 1기(2027-01-01)만, 시작일 순 정렬', () => {
  assert.deepEqual(C.termsFrom([]), [{ n: 1, start: '2027-01-01' }]);
  assert.deepEqual(C.termsFrom([['2', '2028-01-03', 'x'], ['1', '2027-01-01', 'x'], ['3', '날짜아님']]),
    [{ n: 1, start: '2027-01-01' }, { n: 2, start: '2028-01-03' }]);
});

test('지금 회차와 다음 회차', () => {
  const t = C.termsFrom([['1', '2027-01-01'], ['2', '2028-01-03']]);
  assert.deepEqual(C.termsNow(t, '2026-11-11'), { cur: t[0], next: null }, '시작 전엔 1기가 지금 회차');
  assert.deepEqual(C.termsNow(t, '2027-12-30'), { cur: t[0], next: t[1] }, '1기 끝나고 2기 시작 전');
  assert.deepEqual(C.termsNow(t, '2028-01-03'), { cur: t[1], next: null });
});

test('참여자: 1기는 등록한 사람 전부, 2기부터는 참여를 누른 사람만 (등록 순서)', () => {
  const members = ['영희', '철수', '민수'];
  const joins = [['민수', '2'], ['영희', '2'], ['철수', '3']];
  assert.deepEqual(C.participants({ n: 1 }, members, joins), members);
  assert.deepEqual(C.participants({ n: 2 }, members, joins), ['영희', '민수']);
});
