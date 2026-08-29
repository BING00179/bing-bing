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
