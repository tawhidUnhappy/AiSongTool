#!/usr/bin/env python3
"""Use Gemma 4 (google/gemma-4-E4B-it) for the Create flow's per-field
"let Gemma write it" options:

- `--mode full` (default): song name + song style + lyrics + an image
  prompt from one short description.
- `--mode image_prompt`: just an image prompt, for flows that only want
  Gemma's help with the background image.
- `--mode detect_language`: given literal lyrics text, returns its ISO
  639-1 language code — used instead of guessing when vocal_language is
  left on "Auto", since acestep.cpp's own metadata-fill guesses from the
  caption alone and has been observed picking a wrong language entirely.

Runs inside the isolated gemma-uv venv only — no `aisongtool` package imports
here, matching workers/demucs_separate.py's pattern. One-shot: load the
model, write one JSON result, exit.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_FULL_INSTRUCTIONS = (
    "You are a songwriting and prompt-writing assistant for an AI music + image "
    "generation pipeline. Given a short description of a song someone wants, "
    "produce exactly one JSON object with these four string keys:\n"
    '- "song_name": a short, catchy title for the song.\n'
    '- "song_style": a short style/caption description for an AI music generator '
    "(genre, mood, tempo, instrumentation, vocal style) — not lyrics.\n"
    '- "lyrics": full song lyrics with verse/chorus structure, plain text, '
    "newline-separated lines.\n"
    '- "image_prompt": a vivid, visual scene description for an AI image '
    "generator, matching the song's theme and mood — not text about the song.\n"
    "Respond with ONLY the JSON object, no markdown fences, no extra commentary."
)

# `--mode reference` — `--prompt` is a pasted reference song (lyrics and/or
# a description of it), used purely as STYLE inspiration. The instructions
# explicitly forbid reusing the reference's actual words/title/imagery —
# the point is a genuinely new, original song in a similar vein, not a
# reworded copy of the reference's protected expression.
_REFERENCE_INSTRUCTIONS = (
    "You are a songwriting and prompt-writing assistant for an AI music + image "
    "generation pipeline. You will be given a REFERENCE SONG (lyrics and/or a "
    "description of one) purely as style inspiration — its genre, mood, tempo, "
    "instrumentation, song structure, and rhyme scheme. Write a completely NEW, "
    "ORIGINAL song in that same style — not a copy or reworded version of it:\n"
    "- Do NOT reuse any specific lines, phrases, hooks, titles, character names, or "
    "imagery from the reference. Every line of the new lyrics must be your own "
    "original writing.\n"
    "- Do NOT closely paraphrase the reference's lyrics line-by-line — write a "
    "different story/theme in the same genre and mood instead.\n"
    "- It is fine (encouraged) to match the reference's tempo, instrumentation, vocal "
    "style, song structure (verse/chorus layout), and general mood.\n"
    "Produce exactly one JSON object with these four string keys:\n"
    '- "song_name": a short, catchy title for the new song (not the reference\'s title).\n'
    '- "song_style": a short style/caption description for an AI music generator '
    "(genre, mood, tempo, instrumentation, vocal style) — not lyrics.\n"
    '- "lyrics": full original song lyrics with verse/chorus structure, plain text, '
    "newline-separated lines.\n"
    '- "image_prompt": a vivid, visual scene description for an AI image '
    "generator, matching the new song's theme and mood — not text about the song.\n"
    "Respond with ONLY the JSON object, no markdown fences, no extra commentary."
)

# `--mode image_prompt` — just the background-image prompt, no song
# name/style/lyrics, for flows that still want Gemma's help with the image
# alone.
_IMAGE_PROMPT_INSTRUCTIONS = (
    "You are a prompt-writing assistant for an AI image generator. Given a short "
    "description, produce exactly one JSON object with one string key:\n"
    '- "image_prompt": a vivid, visual scene description for an AI image '
    "generator, matching the description's theme and mood — not text about a song.\n"
    "Respond with ONLY the JSON object, no markdown fences, no extra commentary."
)

# `--mode detect_language` — `--prompt` is the literal lyrics text here, not
# a description.
_DETECT_LANGUAGE_INSTRUCTIONS = (
    "You detect the language of song lyrics. Given the lyrics text, respond with "
    'exactly one JSON object: {"language": "xx"} where xx is the ISO 639-1 '
    "two-letter code (e.g. en, ja, ko, zh, es, fr, de, hi, ar) of the language the "
    "lyrics are written in. Respond with ONLY the JSON object, no markdown fences, "
    "no extra commentary."
)


_TRAILING_COMMA_RE = re.compile(r",(\s*[}\]])")


def _extract_json(text: str) -> dict:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError(f"No JSON object found in model output: {text[:300]!r}")
    raw = match.group(0)
    # strict=False: LLMs routinely emit literal newlines inside JSON string
    # values (e.g. multi-line lyrics) instead of escaping them as \n, which
    # the strict JSON grammar rejects as a "control character" — Python's
    # parser has a documented non-strict mode specifically for this.
    try:
        return json.loads(raw, strict=False)
    except json.JSONDecodeError:
        # The other routine LLM quirk: a trailing comma right before a
        # closing brace/bracket (`"key": "value",\n}`) — valid in JS object
        # literals, not in JSON. Safe to strip rather than treat as a real
        # parse failure; only falls back to this on the first attempt
        # failing, so a clean response pays no extra regex cost.
        return json.loads(_TRAILING_COMMA_RE.sub(r"\1", raw), strict=False)


_MODE_INSTRUCTIONS = {
    "full": _FULL_INSTRUCTIONS,
    "reference": _REFERENCE_INSTRUCTIONS,
    "image_prompt": _IMAGE_PROMPT_INSTRUCTIONS,
    "detect_language": _DETECT_LANGUAGE_INSTRUCTIONS,
}
_MODE_REQUIRED_KEYS = {
    "full": ("song_name", "song_style", "lyrics", "image_prompt"),
    "reference": ("song_name", "song_style", "lyrics", "image_prompt"),
    "image_prompt": ("image_prompt",),
    "detect_language": ("language",),
}
_MODE_LABELS = {
    "full": "song name + style + lyrics + image prompt",
    "reference": "an original song inspired by the reference",
    "image_prompt": "image prompt",
    "detect_language": "language",
}


def _duration_guidance(seconds: float) -> str:
    minutes, secs = divmod(int(round(seconds)), 60)
    # ~2 words/second of sung vocals is a reasonable average pace; actual
    # songs also spend some of their runtime on intro/outro/instrumental
    # sections with no singing at all, so the usable singing time (and thus
    # word budget) is intentionally a bit less than the full duration.
    sung_seconds = seconds * 0.75
    words_low, words_high = int(sung_seconds * 1.6), int(sung_seconds * 2.4)
    return (
        f"\nThe song should be about {minutes}m{secs:02d}s ({int(seconds)} seconds) long in total. "
        f"Write lyrics sized for that — roughly {words_low}-{words_high} words total, structured into "
        "verses/chorus (add a bridge for longer songs, keep it to one or two short verses for shorter "
        "ones) — not enough lyrics for a noticeably longer or shorter song."
    )


def _max_new_tokens_for(mode: str, duration: float | None) -> int:
    if mode == "detect_language":
        return 32
    if not duration:
        return 1024
    # Longer songs need more lyrics (plus the JSON wrapper/style/image
    # prompt around them) — scale the generation budget with duration
    # instead of one fixed cap that's generous for a 1-minute song but
    # tight for a 4-minute one.
    return max(1024, min(2048, int(duration * 6) + 400))


def write(
    prompt: str,
    out_path: Path,
    mode: str,
    model_id: str = "google/gemma-4-E4B-it",
    duration: float | None = None,
) -> None:
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

    print(f"[gemma] loading tokenizer ({model_id})...", flush=True)
    tokenizer = AutoTokenizer.from_pretrained(model_id)
    print("[gemma] tokenizer ready. loading model weights — first run downloads several "
          "GB from Hugging Face, which can take a while with no per-byte progress shown "
          "here yet (file-listing/auth round trips happen before the download itself "
          "starts printing).", flush=True)
    quant_config = BitsAndBytesConfig(load_in_4bit=True)
    model = AutoModelForCausalLM.from_pretrained(
        model_id,
        quantization_config=quant_config,
        device_map="auto",
    )
    print("[gemma] model loaded.", flush=True)

    instructions = _MODE_INSTRUCTIONS[mode]
    if mode in ("full", "reference") and duration:
        instructions += _duration_guidance(duration)

    messages = [
        {"role": "system", "content": instructions},
        {"role": "user", "content": prompt},
    ]
    inputs = tokenizer.apply_chat_template(
        messages, add_generation_prompt=True, return_tensors="pt", return_dict=True,
    ).to(model.device)

    print(f"[gemma] writing {_MODE_LABELS[mode]}...", flush=True)
    max_new_tokens = _max_new_tokens_for(mode, duration)
    with torch.no_grad():
        output_ids = model.generate(**inputs, max_new_tokens=max_new_tokens, do_sample=True, temperature=0.8)
    generated = output_ids[0][inputs["input_ids"].shape[-1]:]
    text = tokenizer.decode(generated, skip_special_tokens=True)

    data = _extract_json(text)
    for key in _MODE_REQUIRED_KEYS[mode]:
        if not data.get(key):
            raise ValueError(f"Model output is missing required key '{key}': {data}")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[gemma] saved -> {out_path}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--mode", choices=list(_MODE_INSTRUCTIONS), default="full")
    ap.add_argument("--model", default="google/gemma-4-E4B-it")
    ap.add_argument(
        "--duration", type=float, default=None,
        help="Target song length in seconds, for the full/reference (lyrics-writing) modes only.",
    )
    args = ap.parse_args()

    try:
        write(args.prompt, args.out.expanduser().resolve(), args.mode, args.model, args.duration)
        return 0
    except Exception as exc:
        print(f"\n[gemma] ERROR: {exc}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
