FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download all 3 models during build (so they are cached in the image)
RUN python -c "\
from rembg import new_session; \
from PIL import Image; \
import io; \
img = Image.new('RGB', (10,10), 'white'); \
buf = io.BytesIO(); \
img.save(buf, format='PNG'); \
test_bytes = buf.getvalue(); \
print('>>> Downloading birefnet-general...'); \
s1 = new_session('birefnet-general'); \
print('>>> Downloading birefnet-general-lite...'); \
s2 = new_session('birefnet-general-lite'); \
print('>>> Downloading isnet-general-use...'); \
s3 = new_session('isnet-general-use'); \
print('>>> All models downloaded.'); \
"

COPY app.py .

# PORT wird von Railway dynamisch gesetzt (Standard: 8080 als Fallback)
ENV PORT=8080
EXPOSE ${PORT}

# Gunicorn: 1 Worker (RAM-sparend), 4 Threads (concurrent requests),
# 120s Timeout (grosse Bilder brauchen Zeit), Preload (Modell einmal laden)
# Shell-Form damit $PORT zur Laufzeit aufgeloest wird
CMD gunicorn app:app --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 120 --preload --access-logfile - --error-logfile -
