# `Dockerfile`

> Builds one container image with the API, the chat page and the admin page, ready to run on AWS Fargate.

**Part of:** [Deployment](../flows/deployment.md) · [Storage and versions](../flows/storage-and-versions.md)  ·  **Layer:** Tooling

## Purpose
To run the chatbot on AWS it must be packed as a container image (a file system snapshot plus a start command, see the [glossary](../glossary.md)). Fargate is the AWS service that runs such containers without managing servers. The image holds only code and config. Settings come from environment variables, and the search index comes from S3 when `STORAGE=s3`, so the same image works for every environment.

## How it works
1. Starts from `python:3.13-slim`.
2. Sets `PYTHONDONTWRITEBYTECODE=1` (no `.pyc` files), `PYTHONUNBUFFERED=1` (logs appear at once), `PIP_NO_CACHE_DIR=1` (smaller image).
3. Working folder `/srv/backend`. Copies `backend/requirements.txt` first and installs it, so this layer is cached when only code changes.
4. Copies `backend/app`, `backend/config`, and `frontend` to `/srv/frontend`. The API finds the frontend as `backend/../frontend`, which matches this layout.
5. Creates user `app` (uid 1000), makes `/srv/backend/data` owned by it, and switches to it (the app does not run as root). `data/` is only a working copy.
6. Opens port 8000. A `HEALTHCHECK` calls `http://127.0.0.1:8000/api/health` every 30 s (timeout 5 s, 60 s start period, 3 retries). `/api/health` returns 503 until an index is loaded.
7. Starts `uvicorn app.api:create_app --factory --host 0.0.0.0 --port 8000`. `--factory` means uvicorn calls `create_app()` to get the app.

## Key components
- `FROM`, `ENV`, `WORKDIR`, `COPY`/`RUN pip install`, `useradd`/`USER app`, `EXPOSE 8000`, `HEALTHCHECK`, `CMD`.

## Configuration
None in the file. All settings are environment variables at run time (see `backend/.env.example` and [`settings.py`](backend/app/settings.md)). For Fargate, the [deployment flow](../flows/deployment.md) uses `STORAGE=s3`, `S3_BUCKET`, `FEEDBACK_STORE=s3` and the task role for AWS access.

## Dependencies
- **Used by:** `docker build -t lessons-chatbot .` from the repo root; the `app` service in [`backend/docker-compose.yml`](backend/docker-compose.yml.md).
- **Uses:** [`backend/requirements.txt`](backend/requirements.md), [`backend/app/api.py`](backend/app/api.md), the `frontend/` files ([`index.html`](frontend/index.html.md), [`admin.html`](frontend/admin.html.md)). What is left out is set by [`.dockerignore`](ignore-files.md).

## Example
```
docker build -t lessons-chatbot .
docker run -p 8080:8000 -e STORAGE=s3 -e S3_BUCKET=my-bucket ... lessons-chatbot
```
Then `http://localhost:8080/` shows the chat once `/api/health` is OK.

## Known limitations and improvements
- `sample-data/` is not in the image (see [`.dockerignore`](ignore-files.md)), but `config/dataset.yaml` points at `sample-data/made-up/overall_list.csv`. So the container cannot build an index from the default config by itself; it needs an index already in S3 or an upload through the admin page.
- Single-stage build; dependencies are not pinned to exact versions (see [`requirements.md`](backend/requirements.md)), so two builds on different days can differ. Idea: a lock file.
- The health check starts a Python process every 30 s. That is a small cost; it avoids adding another tool to the image.
