// node bible-reading/build.js
//   dist/Code.gs     ← 앱스 스크립트의 Code.gs 에 통째로 붙여넣기
//   dist/Index.html  ← 앱스 스크립트에 HTML 파일 'Index' 를 만들어 붙여넣기
//   dist/preview.html← 내 컴퓨터에서 미리보기 (가짜 서버, 기록은 이 브라우저에만)
const fs = require('node:fs');
const path = require('node:path');

const here = __dirname;
const read = (f) => fs.readFileSync(path.join(here, f), 'utf8');

// 앱스 스크립트에는 module 이 없으므로 마지막 export 줄은 뺍니다.
function coreSource() {
  return read('core.js').replace(/\nif \(typeof module[^\n]*\n?$/, '\n');
}

// 미리보기용 가짜 서버: server.gs 와 같은 규칙, 기록은 localStorage.
// ?today=2027-01-05 로 날짜를 바꿔 볼 수 있습니다.
const FAKE = `
var google = (function () {
  var K = 'bible.preview.db';
  function db() { try { return JSON.parse(localStorage.getItem(K)) || { members: [], records: [] }; } catch (e) { return { members: [], records: [] }; } }
  function put(d) { try { localStorage.setItem(K, JSON.stringify(d)); } catch (e) {} }
  function today() {
    var q = new URLSearchParams(location.search).get('today');
    return q || new Date(Date.now() + 9 * 3600000).toISOString().slice(0, 10);
  }
  function state(d) { return { today: today(), members: d.members.slice(), records: d.records.slice() }; }
  var api = {
    getState: function () { return state(db()); },
    register: function (name) {
      var n = Core.validName(name);
      if (!n) throw new Error('이름은 1~20자로 적어 주세요.');
      var d = db(); if (d.members.indexOf(n) < 0) d.members.push(n); put(d);
      var s = state(d); s.name = n; return s;
    },
    mark: function (name, date, done) {
      if (!Core.portionFor(date)) throw new Error('읽기표에 없는 날짜입니다.');
      if (date > today()) throw new Error('아직 오지 않은 날은 체크할 수 없어요.');
      var d = db();
      if (d.members.indexOf(name) < 0) throw new Error('등록되지 않은 이름입니다.');
      d.records.push([name, date, done ? '완료' : '취소']); put(d); return state(d);
    }
  };
  function runner(ok, fail) {
    var r = {
      withSuccessHandler: function (f) { return runner(f, fail); },
      withFailureHandler: function (f) { return runner(ok, f); }
    };
    Object.keys(api).forEach(function (k) {
      r[k] = function () {
        var a = arguments;
        setTimeout(function () { try { ok(api[k].apply(null, a)); } catch (e) { fail(e); } }, 150);
      };
    });
    return r;
  }
  return { script: { run: runner(function () {}, function () {}) } };
})();
`;

function build() {
  const core = coreSource();
  const app = read('app.html');
  const index = app.replace('/*CORE*/', () => core);
  const code = '// 자동 생성 파일 — bible-reading/build.js. 고칠 때는 core.js·server.gs 를 고치세요.\n\n' +
    core + '\n' + read('server.gs');
  const preview = index.replace('<script>\n' + core, () => '<script>\n' + core + '\n' + FAKE);
  return { code, index, preview };
}

if (require.main === module) {
  const out = build();
  const dist = path.join(here, 'dist');
  fs.mkdirSync(dist, { recursive: true });
  fs.writeFileSync(path.join(dist, 'Code.gs'), out.code);
  fs.writeFileSync(path.join(dist, 'Index.html'), out.index);
  fs.writeFileSync(path.join(dist, 'preview.html'), out.preview);
  console.log('만들었습니다: dist/Code.gs, dist/Index.html, dist/preview.html');
}

module.exports = { build };
