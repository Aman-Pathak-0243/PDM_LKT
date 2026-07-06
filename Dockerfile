# Predictive Maintenance — container image (client / LAN delivery).
# Uses the Playwright base image so Chromium + its system libraries are preinstalled
# (the app fetches Grafana panels via headless Chromium).
FROM mcr.microsoft.com/playwright/python:v1.49.0-jammy

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install Python deps first for layer caching. Re-run `playwright install` so the
# browser matches whatever playwright version pip resolves (belt-and-suspenders
# over the version bundled in the base image).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && python -m playwright install chromium

# App code (see .dockerignore: .env, database/, data/, logs/, .venv are excluded).
COPY . .

# Runtime config. Data + logs live under /app/database and /app/logs, which
# docker-compose bind-mounts to ./database and ./logs on the host, so the CSV
# store persists across restarts and is visible/back-up-able on the host — the
# same folders a native `python run.py` uses. Secrets/URLs come from .env at run.
ENV STORAGE_BACKEND=csv \
    DATA_DIR=/app/database \
    LOG_DIR=/app/logs \
    APP_HOST=0.0.0.0 \
    APP_PORT=8800 \
    PLAYWRIGHT_HEADLESS=true

EXPOSE 8800

# Healthcheck hits the app's own health endpoint.
HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8800/api/health').status==200 else 1)"

# Web dashboard + APScheduler automation run in this one process.
CMD ["python", "run.py"]
