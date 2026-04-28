#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def eprint(*a):
    print(*a, file=sys.stderr)


def configure_runtime_caches() -> None:
    """
    Force all model/tool caches into persistent Docker-mounted folders.

    This MUST run before importing torch / torchaudio / whisperx so those
    libraries pick up the cache locations on first import.
    """
    xdg_cache_home = os.environ.get("XDG_CACHE_HOME", "/root/.cache")
    hf_home = os.environ.get("HF_HOME", f"{xdg_cache_home}/huggingface")
    torch_home = os.environ.get("TORCH_HOME", f"{xdg_cache_home}/torch")

    os.environ.setdefault("XDG_CACHE_HOME", xdg_cache_home)
    os.environ.setdefault("HF_HOME", hf_home)
    os.environ.setdefault("HF_HUB_CACHE", f"{hf_home}/hub")
    os.environ.setdefault("TRANSFORMERS_CACHE", hf_home)
    os.environ.setdefault("TORCH_HOME", torch_home)

    # Optional but nice in containers
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")


def pick_default_device() -> str:
    try:
        import torch  # type: ignore

        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


def patch_torch_load_weights_only() -> None:
    """PyTorch 2.6 changed torch.load default weights_only=True, breaking
    pyannote checkpoints that store omegaconf objects.

    Two-pronged fix:
    1. add_safe_globals — PyTorch 2.6 official approach, allowlists omegaconf types.
    2. Wrapper function — forces weights_only=False on every call as a fallback.
    """
    try:
        import torch
        import torch.serialization

        # ── Fix 1: allowlist omegaconf types (torch 2.6 recommended) ──────────
        if hasattr(torch.serialization, "add_safe_globals"):
            safe = []
            for name in (
                "omegaconf.listconfig.ListConfig",
                "omegaconf.dictconfig.DictConfig",
                "omegaconf.nodes.AnyNode",
                "omegaconf.nodes.IntegerNode",
                "omegaconf.nodes.FloatNode",
                "omegaconf.nodes.StringNode",
                "omegaconf.nodes.BooleanNode",
            ):
                try:
                    module, cls = name.rsplit(".", 1)
                    import importlib
                    safe.append(getattr(importlib.import_module(module), cls))
                except Exception:
                    pass
            if safe:
                torch.serialization.add_safe_globals(safe)

        # ── Fix 2: wrapper that forces weights_only=False (belt-and-suspenders) ─
        if not hasattr(torch, "_aisongtool_load_patched"):
            _orig = torch.load
            def _patched_load(*args, **kwargs):
                kwargs["weights_only"] = False
                return _orig(*args, **kwargs)
            torch.load = _patched_load
            torch._aisongtool_load_patched = True

    except Exception:
        pass


def patch_torchaudio_for_pyannote() -> None:
    """
    Fix WhisperX -> pyannote.audio import crash on some torchaudio versions where
    torchaudio.AudioMetaData is not exposed at the top-level.

    This keeps "pyannote" VAD available (quality-first) without needing to create
    .venv/Lib/site-packages/sitecustomize.py.
    """
    try:
        import torchaudio  # type: ignore

        if hasattr(torchaudio, "AudioMetaData"):
            return

        AudioMetaData = None

        try:
            from torchaudio.backend.common import AudioMetaData as AMD  # type: ignore

            AudioMetaData = AMD
        except Exception:
            try:
                from torchaudio.backend._common import AudioMetaData as AMD  # type: ignore

                AudioMetaData = AMD
            except Exception:
                AudioMetaData = None

        if AudioMetaData is not None:
            torchaudio.AudioMetaData = AudioMetaData  # type: ignore[attr-defined]

    except Exception:
        pass


def normalize_language_code(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip().lower()
    if not value:
        return None

    # common normalizations
    aliases = {
        "jp": "ja",
        "eng": "en",
        "english": "en",
        "japanese": "ja",
        "arabic": "ar",
        "russian": "ru",
    }
    return aliases.get(value, value)


def should_skip_alignment(
    detected_lang: str | None,
    explicit_language: str | None,
    explicit_align_model: str | None,
) -> tuple[bool, str]:
    """
    Skip alignment in known bad cases to avoid useless re-download attempts.

    Your log showed WhisperX auto-detected `ru` and then tried to load:
    jonatasgrosman/wav2vec2-large-xlsr-53-russian
    which failed and caused extra Hugging Face download churn.
    """
    lang = normalize_language_code(detected_lang)

    if explicit_align_model:
        return False, ""

    if not lang:
        return True, "detected language is empty"

    # If the user explicitly forced a language, trust it.
    if explicit_language:
        return False, ""

    # This is the exact failure case from your log.
    if lang == "ru":
        return (
            True,
            "auto-detected language 'ru' is unreliable for this pipeline; skipping align to avoid bad model downloads",
        )

    return False, ""


def main() -> int:
    configure_runtime_caches()

    ap = argparse.ArgumentParser(
        description="WhisperX ASR + forced alignment -> word timestamps"
    )
    ap.add_argument("--audio", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--overwrite", action="store_true")

    ap.add_argument("--model", default="large-v3")
    ap.add_argument("--language", default="", help="e.g. en, ja. Empty=auto")
    ap.add_argument("--device", default="", help="cuda/cpu. Empty=auto")
    ap.add_argument("--compute_type", default="", help="float16/int8. Empty=auto")
    ap.add_argument("--batch_size", type=int, default=0)

    ap.add_argument(
        "--align", action="store_true", help="Run WhisperX forced alignment step"
    )
    ap.add_argument(
        "--align_model",
        default="",
        help="Optional explicit align model name (usually leave empty)",
    )

    ap.add_argument(
        "--vad",
        default="silero",
        choices=["pyannote", "silero"],
        help="VAD backend. silero=fast/robust (default), pyannote=better boundaries.",
    )

    args = ap.parse_args()

    audio_path = Path(args.audio).resolve()
    out_path = Path(args.out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if out_path.exists() and not args.overwrite:
        eprint(f"[ERROR] output exists (use --overwrite): {out_path}")
        return 2
    if not audio_path.exists():
        eprint(f"[ERROR] audio not found: {audio_path}")
        return 2

    device = args.device or pick_default_device()
    compute_type = args.compute_type or ("float16" if device == "cuda" else "int8")
    language = normalize_language_code(args.language.strip() or None)
    batch_size = args.batch_size or (16 if device == "cuda" else 4)

    print("[INFO] WhisperX settings:")
    print(f"  model:        {args.model}")
    print(f"  device:       {device}")
    print(f"  compute_type: {compute_type}")
    print(f"  language:     {language}")
    print(f"  batch_size:   {batch_size}")
    print(f"  vad:          {args.vad}")
    print(f"  align:        {bool(args.align)}")
    print(f"  audio:        {audio_path}")
    print(f"  out:          {out_path}")
    print(f"  HF_HOME:      {os.environ.get('HF_HOME')}")
    print(f"  TORCH_HOME:   {os.environ.get('TORCH_HOME')}")

    patch_torch_load_weights_only()
    patch_torchaudio_for_pyannote()

    try:
        import whisperx  # type: ignore
    except Exception as ex:
        eprint(f"[ERROR] whisperx import failed in this env: {ex}")
        return 3

    load_kwargs = dict(
        device=device,
        compute_type=compute_type,
        language=language,
    )

    try:
        model = whisperx.load_model(
            args.model,
            vad_method=args.vad,
            **load_kwargs,
        )
    except TypeError:
        model = whisperx.load_model(
            args.model,
            **load_kwargs,
        )

    result = model.transcribe(str(audio_path), batch_size=batch_size)

    if args.align:
        try:
            detected_lang = normalize_language_code(
                result.get("language") or language or "en"
            )
            print(f"[INFO] Align language: {detected_lang}")

            skip_align, reason = should_skip_alignment(
                detected_lang=detected_lang,
                explicit_language=language,
                explicit_align_model=args.align_model.strip() or None,
            )
            if skip_align:
                print(f"[WARN] Skipping alignment: {reason}")
            else:
                audio = whisperx.load_audio(str(audio_path))

                align_kwargs = {}
                if args.align_model.strip():
                    align_kwargs["model_name"] = args.align_model.strip()

                try:
                    align_model, metadata = whisperx.load_align_model(
                        language_code=detected_lang,
                        device=device,
                        **align_kwargs,
                    )
                except TypeError:
                    align_model, metadata = whisperx.load_align_model(
                        language_code=detected_lang,
                        device=device,
                    )

                aligned = None
                try:
                    aligned = whisperx.align(
                        result["segments"],
                        align_model,
                        metadata,
                        audio,
                        device,
                        return_char_alignments=False,
                    )
                except TypeError:
                    try:
                        aligned = whisperx.align(
                            result["segments"],
                            align_model,
                            metadata,
                            audio,
                            device,
                        )
                    except TypeError:
                        aligned = whisperx.align(
                            segments=result["segments"],
                            model=align_model,
                            metadata=metadata,
                            audio=audio,
                            device=device,
                        )

                if isinstance(aligned, dict) and "segments" in aligned:
                    result["segments"] = aligned["segments"]
                    print(
                        "[INFO] Alignment done: segments updated with word timestamps."
                    )
                else:
                    print(
                        "[WARN] Alignment returned unexpected structure; keeping original segments."
                    )

        except Exception as ex:
            eprint(f"[WARN] Alignment step failed; continuing without alignment: {ex}")

    out_payload = {
        "text": result.get("text", ""),
        "language": result.get("language"),
        "segments": result.get("segments", []),
    }
    out_path.write_text(
        json.dumps(out_payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("[INFO] Wrote:", out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
