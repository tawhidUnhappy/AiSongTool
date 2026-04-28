#!/usr/bin/env python3
"""
Separate vocals + instrumental using the demucs internal Python API.

Uses demucs.pretrained + demucs.apply directly — no CLI, no torchaudio.save().
Audio is written with soundfile which is reliable on all platforms.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def separate(song_path: Path, out_dir: Path, model_name: str = "htdemucs") -> None:
    import torch
    import soundfile as sf
    from demucs.pretrained import get_model
    from demucs.apply import apply_model
    from demucs.audio import AudioFile

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"[demucs] device={device}  model={model_name}")

    model = get_model(model_name)
    model.eval()
    if device == "cuda":
        model = model.cuda()

    sr   = model.samplerate
    ch   = model.audio_channels
    srcs = model.sources  # e.g. ['drums','bass','other','vocals']

    print(f"[demucs] loading audio: {song_path.name}")
    wav = AudioFile(str(song_path)).read(streams=0, samplerate=sr, channels=ch)
    # wav: Tensor(channels, samples)

    # Normalise (same as demucs CLI does internally)
    ref  = wav.mean(0)
    mean = ref.mean()
    std  = ref.std()
    wav  = (wav - mean) / (std + 1e-8)

    print("[demucs] separating …")
    with torch.no_grad():
        out = apply_model(model, wav[None].to(device), progress=True)
    # out: Tensor(batch=1, num_sources, channels, samples)
    out = out[0]  # (num_sources, channels, samples)

    # Denormalise
    out = out * (std + 1e-8) + mean

    out_dir.mkdir(parents=True, exist_ok=True)

    def save(tensor: "torch.Tensor", path: Path) -> None:
        # soundfile expects (samples, channels)
        arr = tensor.cpu().float().numpy().T
        sf.write(str(path), arr, sr, subtype="PCM_16")
        print(f"[demucs] saved → {path.name}")

    vocals_idx   = srcs.index("vocals")
    vocals       = out[vocals_idx]
    instrumental = sum(out[i] for i in range(len(srcs)) if i != vocals_idx)

    save(vocals,       out_dir / "vocals.wav")
    save(instrumental, out_dir / "instrumental.wav")
    print("[demucs] done")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("song", type=Path)
    ap.add_argument("out",  type=Path)
    ap.add_argument("--model", default="htdemucs")
    args = ap.parse_args()

    try:
        separate(
            args.song.expanduser().resolve(),
            args.out.expanduser().resolve(),
            model_name=args.model,
        )
        return 0
    except Exception as exc:
        print(f"\n❌ {exc}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
