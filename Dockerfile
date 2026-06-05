FROM python:3.12-slim

WORKDIR /app

# Deps first for layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

# Railway injects $PORT; default 8000 for local `docker run`.
CMD ["sh", "-c", "uvicorn dashboard.server:app --host 0.0.0.0 --port ${PORT:-8000}"]
