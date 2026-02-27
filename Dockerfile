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

EXPOSE 8080

CMD ["python", "app.py"]
