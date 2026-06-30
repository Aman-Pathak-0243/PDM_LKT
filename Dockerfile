# Predictive Maintenance — container image (client delivery).
# Uses the Playwright base image so Chromium + its system libs are preinstalled.
FROM mcr.microsoft.com/playwright/python:v1.49.0-jammy

WORKDIR /app

# Install Python deps first for layer caching.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && python -m playwright install chromium

# App code.
COPY . .

# Runtime data lives on a mounted volume (see docker-compose.yml).
ENV DATA_DIR=/data/store_root \
    LOG_DIR=/data/logs \
    APP_HOST=0.0.0.0 \
    APP_PORT=8800 \
    STORAGE_BACKEND=csv

EXPOSE 8800

# Container healthcheck hits the app's health endpoint.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8800/api/health').status==200 else 1)"

CMD ["python", "run.py"]
