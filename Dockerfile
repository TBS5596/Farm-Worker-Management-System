# Farm Worker Management System
#
# Built for a small always-on machine at the farm office - a mini PC or a
# Raspberry Pi 4. The OpenCV runtime libraries and v4l-utils are installed so a
# USB webcam passed into the container works, and ffmpeg so RTSP IP cameras and
# mp4 clip writing work.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FMS_HOST=0.0.0.0 \
    FMS_PORT=8010 \
    FMS_DEBUG=off

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libglib2.0-0 \
    libgl1 \
    libsm6 \
    libxext6 \
    libxrender1 \
    v4l-utils \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
# opencv-contrib-python must be the only OpenCV wheel present: installing plain
# opencv-python alongside it shadows cv2.face and silently disables the LBPH
# face recognizer.
RUN pip install --no-cache-dir -r requirements.txt \
    && pip uninstall -y opencv-python opencv-python-headless 2>/dev/null || true

COPY . .

RUN mkdir -p /app/captures/faces /app/captures/clips /app/data

EXPOSE 8010

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8010/api/v1/health || exit 1

CMD ["python", "app.py"]
