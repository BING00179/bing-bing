# -*- coding: utf-8 -*-
"""index.html + dictionary.js → 파일 하나로 합친 standalone.html 을 만듭니다.
   사용법:  python3 build-single.py
   결과물은 어디에 두든 더블클릭 한 번으로 열리는 단일 HTML 파일입니다."""
import os, re

here = os.path.dirname(os.path.abspath(__file__))
html = open(os.path.join(here, 'index.html'), encoding='utf-8').read()
dic  = open(os.path.join(here, 'dictionary.js'), encoding='utf-8').read()

# 사전 파일을 본문에 그대로 넣는다
html = html.replace('<script src="dictionary.js"></script>', '<script>\n' + dic + '\n</script>')

# 파일 하나로 쓸 때는 없는 파일들이므로 참조를 뺀다 (홈 화면 설치는 인터넷 주소가 있을 때만 동작)
for pat in [r'<link rel="manifest"[^>]*>\n?', r'<link rel="apple-touch-icon"[^>]*>\n?', r'<link rel="icon"[^>]*>\n?']:
    html = re.sub(pat, '', html)
html = re.sub(r'\n *//? ?홈 화면에 설치했을 때.*?\n *\}\n', '\n', html, flags=re.S)
html = re.sub(r'\n */\* 홈 화면에 설치했을 때.*?\n *\}\n', '\n', html, flags=re.S)

out = os.path.join(here, 'standalone.html')
open(out, 'w', encoding='utf-8').write(html)
print('만들었습니다:', out, '(%.0f KB)' % (len(html.encode('utf-8')) / 1024))
