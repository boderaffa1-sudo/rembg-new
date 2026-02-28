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

# Nur Default-Modell herunterladen (RAM-sparend, andere on-demand)
RUN python -c "\
from rembg import new_session; \
print('>>> Downloading birefnet-general...'); \
s1 = new_session('birefnet-general'); \
print('>>> Model downloaded.'); \
"

COPY app.py .

# PORT wird von Railway dynamisch gesetzt (Standard: 8080 als Fallback)
ENV PORT=8080
EXPOSE ${PORT}

# Gunicorn: 1 Worker (RAM-sparend), 4 Threads (concurrent requests),
# 120s Timeout (grosse Bilder brauchen Zeit), Preload (Modell einmal laden)
# Shell-Form damit $PORT zur Laufzeit aufgeloest wird
# KEIN --preload: Modell wird lazy beim ersten Request geladen (spart RAM beim Boot)
CMD gunicorn app:app --bind 0.0.0.0:$PORT --workers 1 --threads 2 --timeout 180 --access-logfile - --error-logfile -
