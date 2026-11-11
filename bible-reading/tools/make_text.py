"""개역한글 본문(jsonl) → bible/text/01.json … 66.json (권별, 앱이 그날 필요한 권만 받음)

    python3 bible-reading/tools/make_text.py <krv_holybible.jsonl>

원본: https://github.com/crizin/bible-db  data/krv/krv_holybible.jsonl
      (성경전서 개역한글판, 대한성서공회 — 저작재산권 보호기간 만료, Public Domain)
본문은 한 글자도 고치지 않습니다(저작인격권 동일성유지권). 출처는 bible/text/SOURCE.md.
파일 모양: {"b": "창세기", "c": [["1절", "2절", …], …]}   — c[장-1][절-1]
"""
import hashlib
import json
import os
import sys

src = sys.argv[1]
out = os.path.join(os.path.dirname(__file__), '..', '..', 'bible', 'text')
os.makedirs(out, exist_ok=True)

books = {}
with open(src, encoding='utf-8') as f:
    for line in f:
        r = json.loads(line)
        b = books.setdefault(r['book'], {'b': r['name_kr'], 'c': []})
        while len(b['c']) < r['chapter']:
            b['c'].append([])
        ch = b['c'][r['chapter'] - 1]
        if r['verse'] != len(ch) + 1:
            sys.exit(f"절 번호가 이어지지 않음: {r['code']} {r['chapter']}:{r['verse']}")
        ch.append(r['text'])

assert sorted(books) == list(range(1, 67)), '66권이 아님'
for n, b in books.items():
    with open(os.path.join(out, f'{n:02d}.json'), 'w', encoding='utf-8') as f:
        json.dump(b, f, ensure_ascii=False, separators=(',', ':'))

sha = hashlib.sha256(open(src, 'rb').read()).hexdigest()
print(f'66권 → {out}  (원본 sha256 {sha})')
