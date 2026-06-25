#!/usr/bin/env python3
"""Standalone Gradio UI for Z-Image-Turbo — loads the model once and serves
repeated generations, the same shape as ACE-Step's own `acestep` Gradio
entry point (`aisongtool ace-step app`). Useful for testing prompts
interactively without paying the ~1 minute model-load cost on every single
image, and as an isolated way to confirm Z-Image itself works independently
of the Create flow's one-shot `zimage_generate.py` invocation.

Runs inside the isolated zimage-uv venv only, same as zimage_generate.py.
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=7861)
    args = ap.parse_args()

    import gradio as gr
    import torch
    from diffusers import ZImagePipeline

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"[zimage-gui] device={device}", flush=True)
    print("[zimage-gui] loading Z-Image-Turbo (4-bit) — first run downloads a few GB from "
          "Hugging Face, which can take a while.", flush=True)

    pipe = ZImagePipeline.from_pretrained(
        "unsloth/Z-Image-Turbo-unsloth-bnb-4bit", torch_dtype=torch.bfloat16
    )
    if device == "cuda":
        # See zimage_generate.py — try the GPU outright first, only fall
        # back to (slower) CPU offload if it genuinely doesn't fit.
        try:
            pipe.to(device)
            print("[zimage-gui] model loaded fully on GPU.", flush=True)
        except torch.cuda.OutOfMemoryError:
            print("[zimage-gui] full-GPU load didn't fit — falling back to CPU offload "
                  "(slower, splits the model across RAM and VRAM).", flush=True)
            torch.cuda.empty_cache()
            pipe.enable_model_cpu_offload()
            print("[zimage-gui] model loaded with CPU offload.", flush=True)
    else:
        pipe.to(device)
        print("[zimage-gui] model loaded — ready.", flush=True)

    # Gradio's own gr.Image output only writes to its temp cache, which can
    # get cleaned up — also save a persistent copy next to the rest of the
    # app's output (resolved from this file's own location, not cwd, since
    # this script runs with the zimage-uv env dir as its working directory).
    out_dir = Path(__file__).resolve().parent.parent / "output" / "zimage-gui"
    out_dir.mkdir(parents=True, exist_ok=True)

    def _generate(prompt: str, width: int, height: int, seed: float):
        generator = None
        if seed is not None and seed >= 0:
            generator = torch.Generator(device).manual_seed(int(seed))
        image = pipe(
            prompt=prompt,
            num_inference_steps=8,
            guidance_scale=0.0,
            height=int(height),
            width=int(width),
            generator=generator,
        ).images[0]
        out_path = out_dir / f"{int(time.time())}.png"
        image.save(out_path)
        print(f"[zimage-gui] saved -> {out_path}", flush=True)
        return image

    with gr.Blocks(title="Z-Image-Turbo") as demo:
        gr.Markdown("# Z-Image-Turbo")
        prompt_box = gr.Textbox(label="Prompt", lines=2)
        with gr.Row():
            width_box = gr.Number(label="Width", value=1024, precision=0)
            height_box = gr.Number(label="Height", value=1024, precision=0)
            seed_box = gr.Number(label="Seed (blank/-1 = random)", value=-1, precision=0)
        run_button = gr.Button("Generate", variant="primary")
        output_image = gr.Image(label="Result")
        run_button.click(_generate, inputs=[prompt_box, width_box, height_box, seed_box], outputs=output_image)

    demo.queue().launch(server_name=args.host, server_port=args.port, inbrowser=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
