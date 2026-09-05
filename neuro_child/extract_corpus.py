"""
Extract English sentences from B:\Local AI corpus files.
Writes clean sentences to neuro_child/memory/english_corpus.txt for training.
"""
from __future__ import annotations

import re
from pathlib import Path

BASE = Path(r'B:\Local AI')
OUT = Path(__file__).resolve().parent / 'memory' / 'english_corpus.txt'

patterns = [
    '*.txt',
    '*.html',
]

seen = set()
out_lines = []

for pattern in patterns:
    for path in BASE.rglob(pattern):
        try:
            text = path.read_text(encoding='utf-8', errors='ignore')
        except Exception:
            continue
        
        # For HTML, strip tags
        if path.suffix == '.html':
            text = re.sub(r'<[^>]+>', ' ', text)
            text = re.sub(r'&[a-z]+;', ' ', text)
        
        sentences = re.split(r'(?<=[.!?])\s+', text)
        for s in sentences:
            s = s.strip()
            if not s:
                continue
            alpha = sum(c.isalpha() for c in s)
            if alpha < 15 or alpha / max(len(s), 1) < 0.5:
                continue
            if len(s) > 300:
                continue
            if s in seen:
                continue
            seen.add(s)
            out_lines.append(s)
            if len(out_lines) >= 20000:
                break
        if len(out_lines) >= 20000:
            break
    if len(out_lines) >= 20000:
        break

OUT.write_text('\n'.join(out_lines), encoding='utf-8')
print(f'Wrote {len(out_lines)} sentences to {OUT}')
