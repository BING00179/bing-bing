// 달력 알림 파일(.ics) 시험
const test = require('node:test');
const assert = require('node:assert/strict');
const C = require('../core.js');

const URL = 'https://example.org/app';
const ics = C.icsFor(URL);
const lines = ics.split('\r\n');
const events = ics.split('BEGIN:VEVENT').slice(1);
// 접힌 줄을 다시 펴서 읽기
const unfolded = ics.replace(/\r\n /g, '');

test('달력 파일 틀 — CRLF 줄바꿈, 처음과 끝', () => {
  assert.equal(lines[0], 'BEGIN:VCALENDAR');
  assert.equal(lines[lines.length - 2], 'END:VCALENDAR');
  assert.equal(lines[lines.length - 1], '');
  assert.ok(!/[^\r]\n/.test(ics), 'LF 만 있는 줄바꿈 없음');
});

test('하루 한 일정, 362일', () => {
  assert.equal(events.length, C.DAY_COUNT);
  assert.equal(C.DAY_COUNT, 362);
});

test('첫날 한국 시각 아침 6시 = 전날 21시 UTC', () => {
  assert.ok(events[0].includes('DTSTART:20261231T210000Z'));
  assert.ok(events[events.length - 1].includes('DTSTART:20271227T210000Z'));
});

test('일정마다 알림이 시작 시각에 울린다', () => {
  for (const e of events) {
    assert.ok(e.includes('BEGIN:VALARM'));
    assert.ok(e.includes('ACTION:DISPLAY'));
    assert.ok(e.includes('TRIGGER:PT0M'));
  }
});

test('제목은 그날 분량, 메모에 앱 주소', () => {
  const u = unfolded.split('BEGIN:VEVENT').slice(1);
  assert.ok(u[0].includes('SUMMARY:📖 창세기 1~3장'));
  assert.ok(u[2].includes('SUMMARY:📖 창세기 7~11장'), '첫 주일 5장');
  assert.ok(u[0].includes(URL));
  assert.ok(u[u.length - 1].includes('SUMMARY:📖 요한계시록 21~22장'));
});

test('UID 가 날마다 다르고 다시 만들어도 같다', () => {
  const uids = events.map((e) => e.match(/UID:([^\r]+)/)[1]);
  assert.equal(new Set(uids).size, uids.length);
  assert.equal(C.icsFor(URL), ics);
});

test('한 줄은 75바이트 이하 (한글이 잘리지 않게 접음)', () => {
  for (const l of lines) assert.ok(Buffer.byteLength(l, 'utf8') <= 75, l);
  assert.ok(!unfolded.includes('�'));
});

test('쉼표·세미콜론·줄바꿈은 달력 규칙대로 이스케이프', () => {
  assert.equal(C.icsEscape('a,b;c\nd\\e'), 'a\\,b\\;c\\nd\\\\e');
});

test('알림 시각은 각자 고름 — 5시~22시 정시, 기본 6시', () => {
  assert.deepEqual(C.ALARM_HOURS, [5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22]);
  assert.equal(C.DEFAULT_ALARM_HOUR, 6);
  assert.equal(C.alarmHour('7'), 7);
  assert.equal(C.alarmHour(4), null);
  assert.equal(C.alarmHour(23), null);
  assert.equal(C.alarmHour('7시'), null);
  assert.equal(C.alarmHour(6.5), null);
  assert.equal(C.hourLabel(5), '오전 5시');
  assert.equal(C.hourLabel(12), '낮 12시');
  assert.equal(C.hourLabel(21), '밤 9시');
  assert.equal(C.hourLabel(18), '오후 6시');
});

test('달력 파일도 고른 시각으로 (밤 9시 = 12:00 UTC)', () => {
  const e = C.icsFor(URL, 21).split('BEGIN:VEVENT')[1];
  assert.ok(e.includes('DTSTART:20270101T120000Z'));
  assert.equal(C.icsFor(URL), C.icsFor(URL, 6), '기본은 6시');
});
