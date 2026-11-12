// 묵상(해마다)·내보내기·가져오기 가상 시험 — 실제 브라우저로 날짜를 바꿔 가며 확인.
// 돌리는 법: 저장소 맨 위에서  python3 -m http.server 8765  띄운 뒤  node bible-reading/tools/notes_check.js
// (파일은 /tmp 아래 임시 폴더에 만듦)
const { chromium } = require('playwright');
const fs = require('fs');
const results = [];
const TMP = fs.mkdtempSync(require('os').tmpdir() + '/notes-');
const ok = (name, cond, info) => results.push((cond ? '통과 ' : '실패 ') + name + (cond ? '' : '  ← ' + JSON.stringify(info)));
const URL = 'http://localhost:8765/bible/?s=demo&today=2027-01-01';
async function phone(b, when, seed) {
  const ctx = await b.newContext({ viewport: { width: 390, height: 844 }, acceptDownloads: true });
  const p = await ctx.newPage();
  await p.clock.setFixedTime(new Date(when));
  await p.addInitScript((seed) => { if (!sessionStorage.getItem('s')) { sessionStorage.setItem('s','1');
    localStorage.setItem('bible.name', '김은혜'); localStorage.setItem('bible.alarm','none');
    for (const k in seed) localStorage.setItem(k, JSON.stringify(seed[k])); }
    sessionStorage.setItem('bible.installSkip2','1'); }, seed || {});
  await p.goto(URL); await p.waitForTimeout(700);
  return p;
}
const memo = (p) => p.evaluate(() => JSON.parse(localStorage.getItem('bible.memo') || '{}'));
async function writeMemo(p, k, text) {
  if (!(await p.$('.reader'))) { await p.click('[data-act="read"]'); await p.waitForTimeout(600); }
  await p.click('.reader p[data-k="' + k + '"]'); await p.click('[data-act="v-memo"]'); await p.fill('#memotext', text); await p.click('[data-act="v-memo-save"]');
}
async function openMemo(p, k) { await p.click('.reader p[data-k="' + k + '"]'); await p.click('[data-act="v-memo"]'); }
(async () => {
  const b = await chromium.launch();
  // 1) 예전 모양 묵상(지금 앱으로 2027년에 쓴 것) → 새 앱에서 2027년 묵상으로 보임
  const at27 = new Date('2027-05-01T09:00:00+09:00').getTime();
  let p = await phone(b, '2027-05-02T09:00:00+09:00', { 'bible.memo': { '1-1-1': { label: '창세기 1:1', text: '옛 모양', at: at27 } } });
  await p.click('[data-act="read"]'); await p.waitForTimeout(600);
  await openMemo(p, '1-1-1');
  ok('예전 묵상이 올해 칸에 그대로', (await p.inputValue('#memotext')) === '옛 모양');
  ok('표시(묵상 꼬리표·줄)', !!(await p.$('.reader p.hasmemo[data-k="1-1-1"] .mk.memo')));
  // 2) 12-31 23:59 KST 에 쓰면 2027, 01-01 00:01 KST 에 쓰면 2028
  p = await phone(b, '2027-12-31T23:59:00+09:00');
  await writeMemo(p, '1-1-2', '섣달 그믐');
  ok('12-31 23:59 → 2027년', !!(await memo(p))['1-1-2'].y['2027'], await memo(p));
  p = await phone(b, '2028-01-01T00:01:00+09:00', { 'bible.memo': { '1-1-2': { label: '창세기 1:2', y: { '2027': { text: '섣달 그믐', at: 1 } } } } });
  await writeMemo(p, '1-1-2', '새해 첫날');
  let m = await memo(p);
  ok('01-01 00:01 → 2028년, 2027년 그대로', m['1-1-2'].y['2028'].text === '새해 첫날' && m['1-1-2'].y['2027'].text === '섣달 그믐', m);
  // 3) 올해 칸에는 올해 것만, 지난해는 읽기 전용으로 위에
  await openMemo(p, '1-1-2');
  ok('입력칸 = 2028년 글', (await p.inputValue('#memotext')) === '새해 첫날');
  ok('지난해 2027 보임', (await p.textContent('#versebar')).includes('2027년 묵상'));
  // 4) 올해 것 삭제 → 2027 남음, 표시도 남음
  await p.click('[data-act="v-memo-del"]'); m = await memo(p);
  ok('2028 삭제해도 2027 남음', !m['1-1-2'].y['2028'] && m['1-1-2'].y['2027'].text === '섣달 그믐', m);
  ok('삭제 뒤에도 묵상 표시 남음', !!(await p.$('.reader p.hasmemo[data-k="1-1-2"]')));
  // 5) 2027 것만 있는 절을 2028년에 열면 입력칸은 비어 있음 (작년 글을 덮어쓰지 않음)
  await openMemo(p, '1-1-2');
  ok('2028 입력칸 비어 있음', (await p.inputValue('#memotext')) === '');
  await p.click('[data-act="v-memo-close"]');
  // 6) 형광펜·책갈피 + 내보내기
  await p.click('.reader p[data-k="1-1-3"]'); await p.click('[data-act="v-hl"][data-c="2"]');
  await p.click('.reader p[data-k="1-1-4"]'); await p.click('[data-act="v-bm"]');
  await p.click('[data-act="close-read"]'); await p.click('[data-tab="set"]'); await p.waitForTimeout(300);
  const [dl] = await Promise.all([p.waitForEvent('download'), p.click('[data-act="notes-export"]')]);
  const f = TMP + '/vt.json'; await dl.saveAs(f);
  const d = JSON.parse(fs.readFileSync(f, 'utf8'));
  ok('파일에 묵상·형광펜·책갈피', d.memo['1-1-2'] && d.hl['1-1-3'] === 2 && d.bm['1-1-4'], d);
  // 7) 새 폰(이미 다른 묵상 있음)에 가져오기 → 합쳐짐, 두 번째는 0
  const q = await phone(b, '2028-02-01T09:00:00+09:00', { 'bible.memo': { '2-1-1': { label: '출애굽기 1:1', y: { '2028': { text: '새 폰 글', at: 5 } } } } });
  await q.click('[data-tab="set"]'); await q.waitForTimeout(300);
  await q.setInputFiles('#notesfile', f); await q.waitForTimeout(400);
  const t1 = await q.textContent('#toast');
  await q.setInputFiles('#notesfile', f); await q.waitForTimeout(400);
  const t2 = await q.textContent('#toast');
  m = await memo(q);
  ok('새 폰 글 + 가져온 글 둘 다', m['2-1-1'] && m['1-1-2'].y['2027'], m);
  ok('형광펜·책갈피 들어옴', await q.evaluate(() => JSON.parse(localStorage.getItem('bible.hl'))['1-1-3'] === 2 && !!JSON.parse(localStorage.getItem('bible.bm'))['1-1-4']));
  ok('첫 가져오기 개수 안내', /가져오기 완료/.test(t1), t1);
  ok('두 번째는 겹치지 않음', /새로 들어온 것 없음/.test(t2), t2);
  ok('설정 목록에 해 표시', (await q.textContent('body')).includes('창세기 1:2 · 2027년'));
  // 8) 같은 해 같은 절이 양쪽에 다르면 나중에 쓴 쪽
  fs.writeFileSync(TMP + '/vt2.json', JSON.stringify({ app: 'bible-notes', v: 1, hl: {}, bm: {}, memo: { '2-1-1': { label: '출애굽기 1:1', y: { '2028': { text: '옛 파일 글', at: 1 } } } } }));
  await q.setInputFiles('#notesfile', TMP + '/vt2.json'); await q.waitForTimeout(300);
  ok('옛 파일이 새 글을 덮지 않음', (await memo(q))['2-1-1'].y['2028'].text === '새 폰 글');
  // 9) 엉뚱한 파일 → 거절, 아무것도 안 바뀜
  const before = JSON.stringify(await memo(q));
  fs.writeFileSync(TMP + '/bad.json', '{"hello":1}');
  await q.setInputFiles('#notesfile', TMP + '/bad.json'); await q.waitForTimeout(300);
  ok('다른 파일 거절 안내', /아니에요/.test(await q.textContent('#toast')), await q.textContent('#toast'));
  fs.writeFileSync(TMP + '/bad2.json', 'not json');
  await q.setInputFiles('#notesfile', TMP + '/bad2.json'); await q.waitForTimeout(300);
  ok('깨진 파일 거절 안내', /읽을 수 없는/.test(await q.textContent('#toast')), await q.textContent('#toast'));
  ok('거절 뒤 그대로', JSON.stringify(await memo(q)) === before);
  // 10) 이상한 글자(태그)가 든 파일 → 글자로만 보임
  fs.writeFileSync(TMP + '/x.json', JSON.stringify({ app: 'bible-notes', v: 1, memo: { '1-1-5': { label: '<img src=x onerror=alert(1)>', y: { '2028': { text: '<b>x</b>', at: 9 } } } } }));
  await q.setInputFiles('#notesfile', TMP + '/x.json'); await q.waitForTimeout(300);
  ok('태그가 실행되지 않음', !(await q.$('.notelink img')) && (await q.textContent('body')).includes('<img'));
  await b.close();
  console.log(results.join('\n'));
})();
