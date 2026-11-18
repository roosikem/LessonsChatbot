# `.dockerignore`, `.gitignore` and `backend/.gitignore`

> Two lists of files to leave out: `.dockerignore` keeps them out of the container image, `.gitignore` keeps them out of git.

**Part of:** [Deployment](../flows/deployment.md)  ·  **Layer:** Tooling

## Purpose
Secrets (the `.env` file) and local data must never end up in an image or a repository. These files make that the default, so nobody has to remember it.

## How it works
`.dockerignore` (used by `docker build`) is an allow-list: it first excludes everything (`*`), then lets in only
`backend/app/`, `backend/config/`, `backend/requirements.txt` and `frontend/`. Inside those it still drops
`__pycache__`, `*.pyc` and any `.env`. Anything new in the project stays out of the image unless it is added here.

`.gitignore` (used by git) keeps secrets, the Python environment, runtime data and editor files out of the repository:
- `.env`, `**/.env` (but not `.env.example`), `.venv/`, `__pycache__/`, `*.pyc`, `.pytest_cache/`, `**/data/`, `*.log`, `*.tmp`, `.idea/`, `.vscode/`, `.DS_Store`

`backend/.gitignore` repeats the basics for the backend folder: `.env`, `.venv/`, `data/`, `__pycache__/`.

## Key components
The two files.

## Configuration
None.

## Dependencies
- **Used by:** `docker build` with the [`Dockerfile`](Dockerfile.md); git.
- **Uses:** nothing.

## Example
`backend/.env` holds the Neo4j password. With these rules, `docker build .` does not send it to the build, and `git status` does not list it.

## Known limitations and improvements
- Because `sample-data` is excluded from the image, the default `config/dataset.yaml` (which points at `sample-data/made-up/overall_list.csv`) has no file to read inside the container; the index must come from S3 or an upload. See the [`Dockerfile`](Dockerfile.md) page.
- The project is a git repository (branch `main`). It holds the app (backend code, config, `requirements.txt`, `.env.example`, `docker-compose.yml`, frontend, Dockerfile), the made-up sample data and `projects-docs/`. The root `.gitignore` keeps out secrets (`.env`), the virtual environment, runtime data (`data/`) and editor files. Check what would be committed with `git status` before every commit.
