# -*- coding: utf-8 -*-
"""배포 전에 앱 버전을 올립니다.  사용법: python3 bump-version.py
   sw.js 의 VERSION 과 index.html 의 APP_VERSION 을 같은 값으로 맞춰,
   이미 설치한 분들 기기가 새 버전을 받아 가도록 합니다."""
import re, os, datetime

here = os.path.dirname(os.path.abspath(__file__))
sw   = open(os.path.join(here, 'sw.js'), encoding='utf-8').read()
html = open(os.path.join(here, 'index.html'), encoding='utf-8').read()

today = datetime.date.today().strftime('%Y.%m.%d')
cur = re.search(r'var VERSION = "([^"]+)"', sw).group(1)
n = int(cur.rsplit('-', 1)[1]) + 1 if cur.startswith(today) else 1
new = '%s-%d' % (today, n)

sw   = re.sub(r'var VERSION = "[^"]+"', 'var VERSION = "%s"' % new, sw, count=1)
html = re.sub(r'var APP_VERSION = "[^"]+"', 'var APP_VERSION = "%s"' % new, html, count=1)
open(os.path.join(here, 'sw.js'), 'w', encoding='utf-8').write(sw)
open(os.path.join(here, 'index.html'), 'w', encoding='utf-8').write(html)
print('%s  →  %s' % (cur, new))

# 변경 내역을 빠뜨리지 않도록 확인
m = re.search(r'var RELEASES = \[\s*\{ v:"([^"]+)"', html)
if not m or m.group(1) != new:
    print('  ⚠  index.html 의 RELEASES 맨 위에 v"%s" 항목을 추가하세요.' % new)
    print('     추가하지 않으면 사용자에게 업데이트 안내가 뜨지 않습니다.')
else:
    print('  ✓  변경 내역 준비됨: %s' % m.group(1))
