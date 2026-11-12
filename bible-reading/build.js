// node bible-reading/build.js
//   bible-reading/dist/Code.gs ← 앱스 스크립트 Code.gs 에 통째로 붙여넣기 (서버: 기록·알림)
//   bible/                     ← 화면. 기본 브랜치에 머지되면 GitHub Pages 로
//                                https://bing00179.github.io/bing-bing/bible/ 에 뜸
//   미리보기: bible/index.html?s=preview (가짜 서버, 기록은 그 브라우저에만)
const fs = require('node:fs');
const path = require('node:path');

const here = __dirname;
const site = path.join(here, '..', 'bible');
const read = (f) => fs.readFileSync(path.join(here, f), 'utf8');

// 앱스 스크립트에는 module 이 없으므로 마지막 export 줄은 뺍니다.
const noExport = (src) => src.replace(/\nif \(typeof module[^\n]*\n?$/, '\n');

const WEB_FILES = ['index.html', 'api.js', 'sw.js', 'manifest.webmanifest', 'icon-180.png', 'icon-192.png', 'icon-512.png'];

function build() {
  const code = '// 자동 생성 파일 — bible-reading/build.js. 고칠 때는 core.js·webpush.js·server.gs 를 고치세요.\n\n' +
    noExport(read('core.js')) + '\n' + noExport(read('webpush.js')) + '\n' + read('server.gs');
  const files = { 'core.js': Buffer.from(read('core.js')) };
  for (const f of WEB_FILES) files[f] = fs.readFileSync(path.join(here, 'web', f));
  // 그림(있을 때만): 카톡 링크 미리보기·처음 화면
  for (const f of ['hero.jpg', 'og.jpg']) if (fs.existsSync(path.join(here, 'web', f))) files[f] = fs.readFileSync(path.join(here, 'web', f));
  return { code, files };
}

function write(out) {
  fs.mkdirSync(path.join(here, 'dist'), { recursive: true });
  fs.writeFileSync(path.join(here, 'dist', 'Code.gs'), out.code);
  fs.mkdirSync(site, { recursive: true });
  for (const [f, buf] of Object.entries(out.files)) fs.writeFileSync(path.join(site, f), buf);
}

if (require.main === module) {
  write(build());
  console.log('만들었습니다: bible-reading/dist/Code.gs, bible/ (' + (WEB_FILES.length + 1) + '개 파일)');
}

module.exports = { build, site };
