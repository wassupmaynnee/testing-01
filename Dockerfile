# Frozen runtime: Python 3.14.
FROM python:3.14-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# System deps: ffmpeg (cut/reframe/burn), libGL/glib for opencv runtime.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ffmpeg libgl1 libglib2.0-0 curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY . .

RUN chmod +x entrypoint.sh
EXPOSE 8011

# Container-local ffmpeg lives on PATH; override the frozen Windows defaults.
ENV FFMPEG_BIN=/usr/bin/ffmpeg \
    FFPROBE_BIN=/usr/bin/ffprobe

# Liveness for deploy hosts / `docker run` (compose declares its own too).
HEALTHCHECK --interval=15s --timeout=5s --start-period=40s --retries=10 \
  CMD curl -fsS http://localhost:8011/health || exit 1

ENTRYPOINT ["./entrypoint.sh"]
