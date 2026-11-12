# worker-asr: WhisperX. Com GPU (docker-compose.gpu.yml + nvidia-container-toolkit) usa CUDA; sem GPU roda em CPU.
FROM python:3.11-slim-trixie
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 HF_HOME=/cache/hf TORCH_HOME=/cache/torch
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg curl \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY backend/requirements.txt backend/requirements-asr.txt ./
RUN pip install -r requirements-asr.txt
COPY backend/ /app/
RUN useradd -m -u 1000 kontrul && mkdir -p /data /cache && chown kontrul:kontrul /data /cache
USER kontrul
ENV KONTRUL_DATA_DIR=/data
CMD ["dramatiq", "app.workers.tasks", "--queues", "transcribe", "--processes", "1", "--threads", "1"]
