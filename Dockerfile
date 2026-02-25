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

# Pre-download the rembg model during build
RUN python -c "from rembg import remove, new_session; from PIL import Image; import io; session = new_session('isnet-general-use'); img = Image.new('RGB', (10,10), 'white'); buf = io.BytesIO(); img.save(buf, format='PNG'); remove(buf.getvalue(), session=session)"

COPY app.py .

EXPOSE 8080

CMD ["python", "app.py"]
