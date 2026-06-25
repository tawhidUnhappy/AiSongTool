#!/usr/bin/env python3
"""Standalone Gradio UI for Gemma 4 — loads the model once and serves
repeated requests, the same shape as zimage_gradio.py / ACE-Step's own
bundled UI. Two tabs: the original structured song/image-prompt writer, and
a normal multi-turn streaming Chat tab for using Gemma 4 like any other
chatbot.

Why not Ollama: Ollama would mean a second runtime plus re-downloading this
model from scratch in GGUF format, when the weights are already cached
here via `transformers` for the writer tools. `gr.ChatInterface` (built
into the `gradio` dependency this already has) gives the same multi-turn-
history + streaming chat UX directly on top of the model already loaded
below — no extra install, no duplicate download.

Runs inside the isolated gemma-uv venv only, same as gemma_write.py (which
this imports the instructions/JSON-extraction from — both scripts run from
the same workers/ directory, so a plain `import gemma_write` resolves fine
with no path-hacking).
"""
from __future__ import annotations

import argparse

from gemma_write import _MODE_INSTRUCTIONS, _extract_json


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=7862)
    args = ap.parse_args()

    import gradio as gr
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

    print("[gemma-gui] loading tokenizer...", flush=True)
    tokenizer = AutoTokenizer.from_pretrained("google/gemma-4-E4B-it")
    print("[gemma-gui] tokenizer ready. loading model weights — first run downloads several "
          "GB from Hugging Face, which can take a while.", flush=True)
    model = AutoModelForCausalLM.from_pretrained(
        "google/gemma-4-E4B-it",
        quantization_config=BitsAndBytesConfig(load_in_4bit=True),
        device_map="auto",
    )
    print("[gemma-gui] model loaded — ready.", flush=True)

    _MODE_BY_LABEL = {
        "Song name + style + lyrics + image prompt": "full",
        "Image prompt only": "image_prompt",
        "Detect lyrics language": "detect_language",
    }

    def _write(prompt: str, mode_label: str):
        empty = ("", "", "", "", "")
        if not prompt.strip():
            return empty
        mode = _MODE_BY_LABEL[mode_label]
        messages = [
            {"role": "system", "content": _MODE_INSTRUCTIONS[mode]},
            {"role": "user", "content": prompt},
        ]
        inputs = tokenizer.apply_chat_template(
            messages, add_generation_prompt=True, return_tensors="pt", return_dict=True,
        ).to(model.device)
        max_new_tokens = 32 if mode == "detect_language" else 1024
        with torch.no_grad():
            output_ids = model.generate(**inputs, max_new_tokens=max_new_tokens, do_sample=True, temperature=0.8)
        generated = output_ids[0][inputs["input_ids"].shape[-1]:]
        text = tokenizer.decode(generated, skip_special_tokens=True)
        try:
            data = _extract_json(text)
        except ValueError as exc:
            return f"(failed to parse model output: {exc})", "", "", "", ""
        if mode == "detect_language":
            return "", "", "", "", data.get("language", "")
        if mode == "image_prompt":
            return "", "", "", data.get("image_prompt", ""), ""
        return data.get("song_name", ""), data.get("song_style", ""), data.get("lyrics", ""), data.get(
            "image_prompt", ""
        ), ""

    _CHAT_SYSTEM_PROMPT = "You are a helpful, friendly conversational assistant."

    def _chat(message: str, history: list[dict]):
        from threading import Thread
        from transformers import TextIteratorStreamer

        messages = [{"role": "system", "content": _CHAT_SYSTEM_PROMPT}, *history,
                    {"role": "user", "content": message}]
        inputs = tokenizer.apply_chat_template(
            messages, add_generation_prompt=True, return_tensors="pt", return_dict=True,
        ).to(model.device)
        # TextIteratorStreamer + a background generate() call is the
        # standard transformers pattern for token-by-token streaming —
        # generate() blocks until done, so it has to run off the main
        # thread for the streamer to yield tokens as they're produced
        # instead of all at once at the end.
        streamer = TextIteratorStreamer(tokenizer, skip_prompt=True, skip_special_tokens=True)
        Thread(target=model.generate, kwargs=dict(
            **inputs, max_new_tokens=1024, do_sample=True, temperature=0.8, streamer=streamer,
        )).start()

        partial = ""
        for chunk in streamer:
            partial += chunk
            yield partial

    with gr.Blocks(title="Gemma 4") as demo:
        gr.Markdown("# Gemma 4")
        with gr.Tab("Song / Image Prompt Writer"):
            prompt_box = gr.Textbox(label="Short description (or lyrics, for language detection)", lines=2)
            mode_box = gr.Radio(
                list(_MODE_BY_LABEL),
                value="Song name + style + lyrics + image prompt",
                label="Mode",
            )
            run_button = gr.Button("Write", variant="primary")
            song_name_box = gr.Textbox(label="Song name")
            song_style_box = gr.Textbox(label="Song style", lines=2)
            lyrics_box = gr.Textbox(label="Lyrics", lines=10)
            image_prompt_box = gr.Textbox(label="Image prompt", lines=2)
            language_box = gr.Textbox(label="Detected language")
            run_button.click(
                _write,
                inputs=[prompt_box, mode_box],
                outputs=[song_name_box, song_style_box, lyrics_box, image_prompt_box, language_box],
            )
        with gr.Tab("Chat"):
            gr.ChatInterface(_chat, type="messages", title="Chat with Gemma 4")

    demo.queue().launch(server_name=args.host, server_port=args.port, inbrowser=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
