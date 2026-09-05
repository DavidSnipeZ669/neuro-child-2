"""
Bootstrap the LanguageCenter with free, public-domain English text.

Usage:
    pip install nltk
    python bootstrap_corpus.py        # trains on the whole free corpus, no limit, saves as it goes
"""
from __future__ import annotations

import sys
import time

from neuro_child.language_center import LanguageCenter


def _ensure_nltk_data():
    import nltk
    for pkg, path in [
        ("gutenberg", "corpora/gutenberg"),
        ("brown", "corpora/brown"),
        ("punkt_tab", "tokenizers/punkt_tab"),
    ]:
        try:
            nltk.data.find(path)
        except LookupError:
            nltk.download(pkg)


def iter_sentences(max_sentences: int | None = None):
    from nltk.corpus import gutenberg, brown

    count = 0
    for fileid in gutenberg.fileids():
        for sent in gutenberg.sents(fileid):
            text = " ".join(sent).strip()
            if len(text) >= 5:
                yield text
                count += 1
                if max_sentences and count >= max_sentences:
                    return
    for sent in brown.sents():
        text = " ".join(sent).strip()
        if len(text) >= 5:
            yield text
            count += 1
            if max_sentences and count >= max_sentences:
                return


def bootstrap(max_sentences: int | None = None, save_every: int = 500, verbose: bool = True):
    _ensure_nltk_data()
    lc = LanguageCenter()

    start = time.time()
    n = 0
    loss_sum = 0.0
    for sentence in iter_sentences(max_sentences):
        loss = lc.learn(sentence)
        loss_sum += loss
        n += 1
        if n % save_every == 0:
            lc.save()
            if verbose:
                elapsed = time.time() - start
                print(
                    f"[{n} sentences | {elapsed:.0f}s] "
                    f"avg_loss={loss_sum / save_every:.4f} stats={lc.get_stats()}"
                )
            loss_sum = 0.0

    lc.save()
    if verbose:
        print(f"Done. Trained on {n} sentences. Final stats: {lc.get_stats()}")
    return lc


if __name__ == "__main__":
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    bootstrap(max_sentences=limit)
