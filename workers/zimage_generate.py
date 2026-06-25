#!/usr/bin/env python3
"""Generate one image with Z-Image-Turbo, using a pre-quantized 4-bit
(bitsandbytes) build (unsloth/Z-Image-Turbo-unsloth-bnb-4bit) instead of the
original Tongyi-MAI/Z-Image-Turbo bf16 weights — about a quarter of the
download size (~3-4GB vs ~12GB) and the same fraction of VRAM, since the
weights stay in 4-bit in memory rather than being upcast. Works on any CUDA
GPU (no Transformer Engine / Blackwell requirement, unlike the FP8 variant).

Runs inside the isolated zimage-uv venv only — no `aisongtool` package
imports here, matching workers/demucs_separate.py's pattern. One-shot: load
the model, make one image, save it, exit.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def generate(prompt: str, out_path: Path, width: int, height: int, seed: int | None) -> None:
    import torch
    from diffusers import ZImagePipeline

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"[zimage] device={device}", flush=True)
    print("[zimage] loading Z-Image-Turbo (4-bit) — first run downloads a few GB from "
          "Hugging Face, which can take a while.", flush=True)

    pipe = ZImagePipeline.from_pretrained(
        "unsloth/Z-Image-Turbo-unsloth-bnb-4bit", torch_dtype=torch.bfloat16
    )
    if device == "cuda":
        # Try the whole pipeline straight on the GPU first — fastest path,
        # and on a clean 12GB card this often just fits. Only fall back to
        # CPU offload (keeps the submodule currently computing on the GPU,
        # swaps the rest to system RAM — the same technique ACE-Step's own
        # server uses) if it genuinely doesn't fit. Going straight to
        # offload unconditionally (the previous version of this script)
        # made every run pay offload's RAM-streaming cost even when the
        # GPU had plenty of room.
        try:
            pipe.to(device)
            print("[zimage] model loaded fully on GPU.", flush=True)
        except torch.cuda.OutOfMemoryError:
            print("[zimage] full-GPU load didn't fit — falling back to CPU offload "
                  "(slower, splits the model across RAM and VRAM).", flush=True)
            torch.cuda.empty_cache()
            pipe.enable_model_cpu_offload()
            print("[zimage] model loaded with CPU offload.", flush=True)
    else:
        pipe.to(device)
        print("[zimage] model loaded.", flush=True)

    generator = torch.Generator(device).manual_seed(seed) if seed is not None else None

    print(f"[zimage] generating ({width}x{height})...", flush=True)
    image = pipe(
        prompt=prompt,
        num_inference_steps=8,
        guidance_scale=0.0,
        height=height,
        width=width,
        generator=generator,
    ).images[0]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(out_path)
    print(f"[zimage] saved -> {out_path}", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--width", type=int, default=1024)
    ap.add_argument("--height", type=int, default=1024)
    ap.add_argument("--seed", type=int, default=None)
    args = ap.parse_args()

    try:
        generate(args.prompt, args.out.expanduser().resolve(), args.width, args.height, args.seed)
        return 0
    except Exception as exc:
        print(f"\n[zimage] ERROR: {exc}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
