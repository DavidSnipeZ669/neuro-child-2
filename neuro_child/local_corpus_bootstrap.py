"""
Ingest a folder of local files (Cornell Movie Dialogs corpus, HTML script
transcripts, Gutenberg .txt books, plain text, word lists, etc.) into the
LanguageCenter automatically. Auto-detects format per file - no manual
cleanup needed.

Usage:
    python local_corpus_bootstrap.py "B:\\Local AI"
    python local_corpus_bootstrap.py "B:\\Local AI" 50000   # optional sentence cap
"""
from __future__ import annotations

import re
import sys
import time
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterator, List

from neuro_child.language_center import LanguageCenter

SKIP_HTML_TAGS = {"script", "style", "head", "title"}
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
SPEAKER_PREFIX_RE = re.compile(r"^[A-Z][A-Za-z0-9 .'_-]{0,24}:\s*")


class _VisibleTextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self._skip_depth = 0
        self.chunks: List[str] = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() in SKIP_HTML_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag):
        if tag.lower() in SKIP_HTML_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data):
        if self._skip_depth == 0:
            text = data.strip()
            if text:
                self.chunks.append(text)


def extract_html_text(path: Path) -> str:
    raw = path.read_text(encoding="utf-8", errors="ignore")
    parser = _VisibleTextExtractor()
    parser.feed(raw)
    return "\n".join(parser.chunks)


def extract_cornell_lines(path: Path) -> List[str]:
    lines = []
    raw = path.read_text(encoding="utf-8", errors="ignore")
    for row in raw.splitlines():
        parts = row.split(" +++$+++ ")
        if len(parts) >= 5:
            text = parts[4].strip()
            if text:
                lines.append(text)
    return lines


GUTENBERG_START_RE = re.compile(r"\*\*\*\s*START OF (THE|THIS) PROJECT GUTENBERG EBOOK.*?\*\*\*", re.IGNORECASE)
GUTENBERG_END_RE = re.compile(r"\*\*\*\s*END OF (THE|THIS) PROJECT GUTENBERG EBOOK.*?\*\*\*", re.IGNORECASE)


def extract_gutenberg_text(raw: str) -> str:
    start_match = GUTENBERG_START_RE.search(raw)
    end_match = GUTENBERG_END_RE.search(raw)
    start = start_match.end() if start_match else 0
    end = end_match.start() if end_match else len(raw)
    return raw[start:end]


def looks_like_gutenberg(raw_head: str) -> bool:
    return "PROJECT GUTENBERG" in raw_head.upper()


def looks_like_cornell_lines(path: Path, raw_head: str) -> bool:
    return "movie_lines" in path.name.lower() or " +++$+++ " in raw_head


def naive_sentence_split(text: str) -> List[str]:
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []
    return [s.strip() for s in SENTENCE_SPLIT_RE.split(text) if len(s.strip()) >= 4]


def sentences_from_file(path: Path) -> Iterator[str]:
    suffix = path.suffix.lower()
    try:
        if suffix in (".html", ".htm"):
            text = extract_html_text(path)
            for line in text.splitlines():
                line = SPEAKER_PREFIX_RE.sub("", line.strip())
                yield from naive_sentence_split(line)
            return

        if suffix == ".txt":
            head = path.read_text(encoding="utf-8", errors="ignore")[:5000]
            if looks_like_cornell_lines(path, head):
                yield from extract_cornell_lines(path)
                return
            raw = path.read_text(encoding="utf-8", errors="ignore")
            if looks_like_gutenberg(head):
                raw = extract_gutenberg_text(raw)
            yield from naive_sentence_split(raw)
            return
    except Exception as e:
        print(f"  (skipped {path.name}: {e})")


def iter_corpus_files(root: Path) -> Iterator[Path]:
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() in (".txt", ".html", ".htm"):
            yield path


def maybe_extract_zips(root: Path):
    code_markers = {"setup.py", "package.json", "pyproject.toml", ".gitignore"}
    for zpath in root.rglob("*.zip"):
        extract_dir = zpath.with_suffix("")
        if extract_dir.exists():
            continue
        try:
            with zipfile.ZipFile(zpath) as zf:
                names = zf.namelist()
                top_level = {n.split("/")[0] for n in names}
                if top_level & code_markers or any(n.endswith((".py", ".js")) for n in names[:20]):
                    continue
                zf.extractall(extract_dir)
                print(f"  extracted {zpath.name} -> {extract_dir.name}/")
        except Exception as e:
            print(f"  (couldn't extract {zpath.name}: {e})")


def bootstrap_from_folder(root_dir: str, max_sentences: int | None = None, save_every: int = 1000):
    root = Path(root_dir)
    if not root.exists():
        print(f"Folder not found: {root}")
        return

    print(f"Scanning {root} ...")
    maybe_extract_zips(root)

    lc = LanguageCenter()
    start = time.time()
    n = 0
    loss_sum = 0.0
    files_seen = 0

    for path in iter_corpus_files(root):
        files_seen += 1
        for sentence in sentences_from_file(path):
            loss = lc.learn(sentence)
            loss_sum += loss
            n += 1
            if n % save_every == 0:
                lc.save()
                elapsed = time.time() - start
                print(f"[{n} sentences | {files_seen} files | {elapsed:.0f}s] "
                      f"avg_loss={loss_sum / save_every:.4f} stats={lc.get_stats()}")
                loss_sum = 0.0
            if max_sentences and n >= max_sentences:
                lc.save()
                print(f"Reached cap of {max_sentences} sentences.")
                return lc

    lc.save()
    print(f"Done. {files_seen} files scanned, {n} sentences trained. Final stats: {lc.get_stats()}")
    return lc


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python local_corpus_bootstrap.py <folder> [max_sentences]")
        sys.exit(1)
    folder = sys.argv[1]
    cap = int(sys.argv[2]) if len(sys.argv) > 2 else None
    bootstrap_from_folder(folder, max_sentences=cap)
