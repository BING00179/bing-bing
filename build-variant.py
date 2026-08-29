# -*- coding: utf-8 -*-
"""미국식·영국식 선택판을 us-uk/ 폴더로 만들어 냅니다.
   사용법: python3 build-variant.py
   기본 앱(index.html)은 건드리지 않습니다. 두 앱은 각자 저장소를 쓰므로 단어도 섞이지 않습니다."""
import os, re, shutil

here = os.path.dirname(os.path.abspath(__file__))
out  = os.path.join(here, 'us-uk')
os.makedirs(out, exist_ok=True)

# ── index.html ────────────────────────────────────
html = open(os.path.join(here, 'index.html'), encoding='utf-8').read()

def one(pat, repl, text, name):
    new, n = re.subn(pat, repl, text, count=1)
    assert n == 1, '치환 실패: ' + name
    return new

# 1) 두 억양 켜기
html = one(r'var ACCENTS = \["en-US"\];', 'var ACCENTS = ["en-US", "en-GB"];', html, 'ACCENTS')
# 2) 저장소 분리 — 기본 앱과 단어가 섞이지 않도록
html = one(r'var KEY = "daily-english-words/v1";',
           'var KEY = "daily-english-words/us-uk/v1";', html, 'KEY')
# 3) 이름과 설명
html = one(r'<title>매일 영어 단어장</title>',
           '<title>매일 영어 단어장 · 미국식/영국식</title>', html, 'title')
html = one(r'<meta name="apple-mobile-web-app-title" content="영어 단어장">',
           '<meta name="apple-mobile-web-app-title" content="영어 단어장 US·UK">', html, 'apple-title')
html = one(r'<h1>매일 영어 <em>단어장</em></h1>',
           '<h1>매일 영어 <em>단어장</em> <small>US · UK</small></h1>', html, 'h1')
html = one(r'단어를 적으면 원어민 발음으로 읽어주고, 날짜별로 쌓아 둡니다\.',
           '미국식·영국식 발음을 골라 듣고, 날짜별로 쌓아 둡니다.', html, 'sub')
# 4) 색을 바꿔 두 앱을 한눈에 구분되게 (자두색 계열)
for a, b in [('--accent:#0e6a63;',  '--accent:#7a3f5e;'),
             ('--accent-soft:#d8ebe8;', '--accent-soft:#f0dee7;'),
             ('--accent:#49b5a8;',  '--accent:#d98cb0;'),
             ('--accent-soft:#1d3a36;', '--accent-soft:#3a2130;'),
             ('--accent-ink:#08110f;', '--accent-ink:#1a0d14;'),
             ('content="#0e6a63"',  'content="#7a3f5e"')]:
    html = html.replace(a, b)
html = html.replace('h1 em{font-style:italic; color:var(--accent)}',
                    'h1 em{font-style:italic; color:var(--accent)}\n'
                    'h1 small{font-family:var(--mono); font-size:12px; font-weight:500; color:var(--ink-2); letter-spacing:.06em; vertical-align:middle}')
open(os.path.join(out, 'index.html'), 'w', encoding='utf-8').write(html)

# ── sw.js — 캐시 이름을 분리한다 ───────────────────
sw = open(os.path.join(here, 'sw.js'), encoding='utf-8').read()
sw = one(r'var CACHE = "eng-words-" \+ VERSION;', 'var CACHE = "eng-words-usuk-" + VERSION;', sw, 'CACHE')
open(os.path.join(out, 'sw.js'), 'w', encoding='utf-8').write(sw)

# ── manifest ──────────────────────────────────────
mf = open(os.path.join(here, 'manifest.webmanifest'), encoding='utf-8').read()
mf = mf.replace('"name": "매일 영어 단어장"', '"name": "매일 영어 단어장 (미국식·영국식)"')
mf = mf.replace('"short_name": "영어 단어장"', '"short_name": "단어장 US·UK"')
mf = mf.replace('"description": "영어 단어를 원어민 발음으로 들려주고 날짜별로 저장하는 단어장"',
                '"description": "미국식·영국식 발음을 골라 들으며 단어를 쌓는 단어장"')
mf = mf.replace('"theme_color": "#0e6a63"', '"theme_color": "#7a3f5e"')
open(os.path.join(out, 'manifest.webmanifest'), 'w', encoding='utf-8').write(mf)

# ── 사전과 아이콘 ─────────────────────────────────
shutil.copy(os.path.join(here, 'dictionary.js'), os.path.join(out, 'dictionary.js'))
for f in ['icon-180.png', 'icon-192.png', 'icon-512.png', 'icon-maskable-512.png']:
    src = os.path.join(here, 'usuk-' + f)          # 색이 다른 전용 아이콘이 있으면 그것을
    shutil.copy(src if os.path.exists(src) else os.path.join(here, f), os.path.join(out, f))
open(os.path.join(out, '.nojekyll'), 'w').close()

print('us-uk/ 생성 완료 —', ', '.join(sorted(os.listdir(out))))
