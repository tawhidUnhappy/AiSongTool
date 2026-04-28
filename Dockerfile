# ── AiSongTool — CPU image (works on any machine, no GPU required) ────────────
FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PYTHONUTF8=1

ENV DEMUCS_PYTHON=/opt/venvs/demucs/bin/python
ENV WHISPERX_PYTHON=/opt/venvs/whisperx/bin/python

ENV XDG_CACHE_HOME=/root/.cache
ENV HF_HOME=/root/.cache/huggingface
ENV HF_HUB_CACHE=/root/.cache/huggingface/hub
ENV TRANSFORMERS_CACHE=/root/.cache/huggingface
ENV TORCH_HOME=/root/.cache/torch
ENV HF_HUB_DISABLE_TELEMETRY=1

ENV PIP_DEFAULT_TIMEOUT=600

RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        ca-certificates \
        libsndfile1 \
        && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Main app deps
COPY pyproject.toml ./
RUN pip install --no-cache-dir \
        "fastapi>=0.110" \
        "uvicorn[standard]>=0.27" \
        "python-multipart>=0.0.9" \
        "pydantic>=2.0"

# Demucs venv — pin torch before demucs so pip cannot upgrade it
RUN python -m venv /opt/venvs/demucs
RUN /opt/venvs/demucs/bin/pip install --no-cache-dir \
        --index-url https://download.pytorch.org/whl/cpu \
        "torch==2.5.1+cpu" \
        "torchaudio==2.5.1+cpu"
RUN /opt/venvs/demucs/bin/pip install --no-cache-dir "demucs==4.0.1" soundfile

# WhisperX venv — pin torch first so whisperx cannot pull 2.6.x from PyPI
RUN python -m venv /opt/venvs/whisperx
RUN /opt/venvs/whisperx/bin/pip install --no-cache-dir \
        --index-url https://download.pytorch.org/whl/cpu \
        "torch==2.5.1+cpu" \
        "torchaudio==2.5.1+cpu"
RUN /opt/venvs/whisperx/bin/pip install --no-cache-dir \
        --extra-index-url https://download.pytorch.org/whl/cpu \
        "whisperx==3.7.4"

RUN mkdir -p \
        /root/.cache \
        /root/.cache/torch \
        /root/.cache/huggingface \
        /root/.cache/huggingface/hub \
        /app/jobs

COPY aisongtool/ ./aisongtool/
COPY workers/ ./workers/
COPY webui/ ./webui/
RUN pip install --no-cache-dir --no-deps .

EXPOSE 8000
CMD ["uvicorn", "aisongtool.server:app", "--host", "0.0.0.0", "--port", "8000"]