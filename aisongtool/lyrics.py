from __future__ import annotations

import re
from dataclasses import dataclass

def normalize_apostrophes(s: str) -> str:
    return (
        s.replace("\u2019", "'")
         .replace("\u2018", "'")
         .replace("\u02BC", "'")
         .replace("\uFF07", "'")
    )

def norm_word(w: str) -> str:
    w = normalize_apostrophes(w).lower()
    w = re.sub(r"[^a-z0-9]+", "", w)
    return w

WORD_RE = re.compile(r"[A-Za-z0-9']+")

@dataclass(frozen=True)
class LyricLine:
    text: str
    words: list[str]

SECTION_BASE = {
    "verse", "vers", "chorus", "bridge", "intro", "outro", "hook", "refrain",
    "interlude", "breakdown", "drop",
    "instrumental", "acapella", "a_cappella", "acappella", "spoken", "spokenword",
    "prechorus", "postchorus", "prehook", "posthook",
    "pre", "post",
    "stanza", "coda", "tag", "solo", "skit", "adlib", "adlibs",
    "rap", "rapping", "singing", "chanting", "humming",
    "vamp", "turnaround", "outtro", "segue",
}

HEADING_OK_EXTRA = {
    "final", "last", "repeat", "reprise", "soft", "broken", "clean", "loud",
    "part", "pt", "section", "build", "drop",
    "x", "times",
    "alt", "alternate", "alternative", "electric", "acoustic",
    "male", "female", "all", "both", "together", "group",
    "harmonies", "harmony", "backing", "background", "lead",
    "big", "full", "half", "short", "long", "double", "triple",
    "opening", "closing", "main", "extended", "condensed",
}

ROMAN = {"i","ii","iii","iv","v","vi","vii","viii","ix","x"}

# Only words that are unambiguously production/effect notes and would never be sung.
# Keep this list small and conservative — when in doubt, do NOT add a word here.
_TECHNICAL_ONLY = {
    "reverb", "reverbed", "slowed", "sped", "spedup", "speedup",
    "remix", "edit", "sfx", "fx",
    "adlib", "adlibs",
    "acapella", "acappella", "instrumental",
    "spoken", "spokenword",
}

def _tokens_for_heading_check(s: str) -> list[str]:
    s = normalize_apostrophes(s).lower().strip()
    s = s.strip(" \t-–—*#[](){}<>:")
    s = re.sub(r"[\[\]\(\)\{\}<>:;,.!?\u2014\u2013\-_/\\|]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    if not s:
        return []
    return re.findall(r"[a-z0-9]+", s)

def is_heading_line(line: str) -> bool:
    toks = _tokens_for_heading_check(line)
    if not toks:
        return False

    has_section = False
    section_keywords = {
        "verse", "vers", "chorus", "bridge", "intro", "outro", "hook", "refrain",
        "interlude", "breakdown", "drop", "instrumental",
        "stanza", "coda", "tag", "solo", "skit", "adlib", "adlibs",
        "rap", "rapping", "singing", "chanting", "humming",
        "vamp", "turnaround", "outtro", "segue",
    }
    if any(t in section_keywords for t in toks):
        has_section = True
    if ("pre" in toks and "chorus" in toks) or ("post" in toks and "chorus" in toks):
        has_section = True
    if ("pre" in toks and "hook" in toks) or ("post" in toks and "hook" in toks):
        has_section = True
    if "prechorus" in toks or "postchorus" in toks or "prehook" in toks or "posthook" in toks:
        has_section = True

    if not has_section:
        return False

    for t in toks:
        if t in SECTION_BASE or t in HEADING_OK_EXTRA:
            continue
        if t.isdigit():
            continue
        if t in ROMAN:
            continue
        if re.fullmatch(r"\d+x", t) or re.fullmatch(r"x\d+", t):
            continue
        return False

    if len(line.strip()) > 80:
        return False
    return True

def is_noise_line(line: str) -> bool:
    s = line.strip()
    return bool(s) and re.fullmatch(r"[\W_]+", s) is not None

def is_stage_direction_line(line: str) -> bool:
    """Return True only for lines that are clearly NOT lyrics.

    Rules:
    - [Square brackets]: filter only if the content is a section heading
      (e.g. [Verse 1], [Chorus]). Keep everything else like [ad-lib].
    - (Parentheses): filter only if the content is a section heading OR
      every word is an unambiguous technical/production term.
      Anything that could plausibly be a backing vocal is kept.
    """
    s = line.strip()
    if len(s) < 3:
        return False

    in_brackets = s[0] == "[" and s[-1] == "]"
    in_parens   = s[0] == "(" and s[-1] == ")"
    if not (in_brackets or in_parens):
        return False

    inner = s[1:-1].strip()
    if not inner:
        return True

    # [Square brackets] — only strip section headings, keep everything else
    if in_brackets:
        return is_heading_line(s) or is_heading_line(inner)

    # (Parentheses) — strip section headings
    if is_heading_line(s) or is_heading_line(inner):
        return True

    # (Parentheses) — strip ONLY if every word is an unambiguous technical term.
    # Short phrase (≤ 4 words) where ALL words are in _TECHNICAL_ONLY.
    toks = _tokens_for_heading_check(inner)
    if not toks:
        return True
    filler = {"and", "with", "the", "a", "an"}
    if len(toks) <= 4 and all(t in _TECHNICAL_ONLY or t in filler for t in toks):
        return True

    # Everything else (backing vocals, echo lines, etc.) → keep
    return False

def preprocess_lyrics_to_lines(raw: str) -> list[str]:
    cleaned: list[str] = []
    for ln in raw.splitlines():
        s = ln.strip()
        if not s:
            continue
        if is_noise_line(s):
            continue

        s = re.sub(r"^\s*\d+\)\s*", "", s).strip()
        s = re.sub(r"^\s*[-•]\s*", "", s).strip()

        if is_stage_direction_line(s):
            continue

        if re.fullmatch(r"[\[\(].*?[\]\)]", s) and is_heading_line(s):
            continue
        if is_heading_line(s):
            continue

        cleaned.append(normalize_apostrophes(s))
    return cleaned

def tokenize_line(line: str) -> list[str]:
    line = normalize_apostrophes(line)
    return [norm_word(m.group(0)) for m in WORD_RE.finditer(line) if norm_word(m.group(0))]

def build_lyric_lines(raw_lyrics: str) -> list[LyricLine]:
    lines = preprocess_lyrics_to_lines(raw_lyrics)
    return [LyricLine(text=ln, words=tokenize_line(ln)) for ln in lines]


def preprocess_lyrics_to_segments(raw: str) -> list[list[str]]:
    """
    Split lyrics into segments (verse, chorus, etc.).
    A new segment begins at every blank line or section heading like [Verse 1].
    Each segment is a list of cleaned, non-empty lyric lines.
    """
    segments: list[list[str]] = []
    current: list[str] = []

    for ln in raw.splitlines():
        s = ln.strip()

        # Blank line or heading → close current segment
        if not s or is_heading_line(s) or (re.fullmatch(r"[\[\(].*?[\]\)]", s) and is_heading_line(s)):
            if current:
                segments.append(current)
                current = []
            continue

        if is_noise_line(s):
            continue

        s = re.sub(r"^\s*\d+\)\s*", "", s).strip()
        s = re.sub(r"^\s*[-•]\s*", "", s).strip()

        if is_stage_direction_line(s):
            continue

        current.append(normalize_apostrophes(s))

    if current:
        segments.append(current)

    return [seg for seg in segments if seg]


def build_lyric_segments(raw_lyrics: str) -> list[list[LyricLine]]:
    """Return lyrics grouped into segments (one list of LyricLine per segment)."""
    segs = preprocess_lyrics_to_segments(raw_lyrics)
    return [
        [LyricLine(text=ln, words=tokenize_line(ln)) for ln in seg]
        for seg in segs
    ]
