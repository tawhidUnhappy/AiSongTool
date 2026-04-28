from __future__ import annotations

import re
from dataclasses import dataclass

from .lyrics import norm_word, normalize_apostrophes

WORD_RE = re.compile(r"[A-Za-z0-9']+")

@dataclass
class WWord:
    w: str
    start: float
    end: float

def extract_whisper_words(whisper_json: dict) -> list[WWord]:
    segs = whisper_json.get("segments") or []
    out: list[WWord] = []

    for s in segs:
        words = s.get("words")
        if isinstance(words, list) and words:
            for ww in words:
                t = (ww.get("word") or "").strip()
                if not t:
                    continue
                t = normalize_apostrophes(t)
                nw = norm_word(t)
                if not nw:
                    continue
                st = float(ww.get("start") or s.get("start") or 0.0)
                en = float(ww.get("end") or s.get("end") or (st + 0.2))
                out.append(WWord(nw, st, en))

    if out:
        return out

    for s in segs:
        text = normalize_apostrophes((s.get("text") or "").strip())
        st = float(s.get("start") or 0.0)
        en = float(s.get("end") or (st + 1.0))
        toks = [norm_word(m.group(0)) for m in WORD_RE.finditer(text) if norm_word(m.group(0))]
        if not toks:
            continue
        dur = max(0.001, en - st)
        step = dur / len(toks)
        for i, w in enumerate(toks):
            out.append(WWord(w, st + i * step, min(en, st + (i + 1) * step)))
    return out

def align_words(lyrics_words: list[str], whisper_words: list[WWord]) -> list[tuple[int | None, int | None]]:
    n = len(lyrics_words)
    m = len(whisper_words)

    dp = [[0] * (m + 1) for _ in range(n + 1)]
    bt = [[0] * (m + 1) for _ in range(n + 1)]

    for i in range(1, n + 1):
        dp[i][0] = i
        bt[i][0] = 2
    for j in range(1, m + 1):
        dp[0][j] = j
        bt[0][j] = 3

    for i in range(1, n + 1):
        lw = lyrics_words[i - 1]
        for j in range(1, m + 1):
            ww = whisper_words[j - 1].w
            cost = 0 if lw == ww else 1
            diag = dp[i - 1][j - 1] + cost
            up = dp[i - 1][j] + 1
            left = dp[i][j - 1] + 1
            best = diag
            b = 1
            if up < best:
                best = up
                b = 2
            if left < best:
                best = left
                b = 3
            dp[i][j] = best
            bt[i][j] = b

    i, j = n, m
    pairs: list[tuple[int | None, int | None]] = []
    while i > 0 or j > 0:
        b = bt[i][j]
        if b == 1:
            pairs.append((i - 1, j - 1))
            i -= 1
            j -= 1
        elif b == 2:
            pairs.append((i - 1, None))
            i -= 1
        else:
            pairs.append((None, j - 1))
            j -= 1
    pairs.reverse()
    return pairs
