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

# Modelle werden NICHT im Build heruntergeladen (spart Build-Zeit + RAM)
# Download passiert lazy beim ersten Request zur Laufzeit

COPY app.py .

# PORT wird von Railway dynamisch gesetzt (Standard: 8080 als Fallback)
ENV PORT=8080
EXPOSE ${PORT}

# Gunicorn: 1 Worker, 2 Threads, 180s Timeout, kein --preload (lazy model load)
CMD ["sh", "-c", "echo '>>> Starting gunicorn on port '$PORT && exec gunicorn app:app --bind 0.0.0.0:$PORT --workers 1 --threads 2 --timeout 180 --access-logfile - --error-logfile -"]
