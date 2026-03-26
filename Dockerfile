FROM python:3.11-slim

# System dependencies required by weasyprint for HTML-to-PDF rendering
RUN apt-get update && apt-get install -y \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    libcairo2 \
    libgdk-pixbuf2.0-0 \
    libffi-dev \
    shared-mime-info \
    fonts-noto \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .

# Cloud Run Jobs run the container to completion.
# Exit code 0 = success, non-zero = failure (Cloud Scheduler can retry).
CMD ["python", "main.py"]
