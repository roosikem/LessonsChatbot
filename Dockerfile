# Talk to Lessons Learned: API + chat UI + admin page in one container.
# Build from the repo root:  docker build -t lessons-chatbot .
# Configure with environment variables (see backend/.env.example); no .env or data is baked in.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv/backend
COPY backend/requirements.txt .
RUN pip install -r requirements.txt

COPY backend/app ./app
COPY backend/config ./config
COPY frontend /srv/frontend

# run as a normal user; data/ is only a working copy (the shared index lives in S3 when STORAGE=s3)
RUN useradd --create-home --uid 1000 app && mkdir -p /srv/backend/data && chown -R app /srv/backend/data
USER app

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"

CMD ["uvicorn", "app.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
