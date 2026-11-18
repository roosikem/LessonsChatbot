# `backend/requirements.txt`

> The Python packages the backend needs to run, and the extra ones needed to run the tests.

**Part of:** [Deployment](../../flows/deployment.md)  ·  **Layer:** Tooling

## Purpose
`pip install -r requirements.txt` installs everything the app needs; the [`Dockerfile`](../Dockerfile.md) does exactly that. The dev file adds test tools, so the container image stays smaller.

## How it works
`requirements.txt` (runtime), each with a minimum version:
- `boto3>=1.40`: AWS SDK, for Bedrock (chat models such as Amazon Nova or Claude, and embedding models), STS (cross-account role) and S3.
- `pydantic>=2.7`: data checks for API requests.
- `pydantic-settings>=2.3`: reads settings from `.env` and environment variables.
- `PyYAML>=6.0`: reads `config/*.yaml`.
- `numpy>=1.26`: vectors and scores for the in-memory search.
- `neo4j>=5.20`: Neo4j driver for the graph store.
- `fastapi>=0.115`: the web API.
- `uvicorn>=0.30`: the web server that runs FastAPI.
- `python-multipart>=0.0.9`: lets FastAPI read file uploads (admin page).
- `openpyxl>=3.1`: reads Excel `.xlsx`/`.xlsm` files.

## Key components
The file above.

## Configuration
None.

## Dependencies
- **Used by:** the [`Dockerfile`](../Dockerfile.md) and developers setting up `backend/.venv`.
- **Uses:** nothing.

## Example
```
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Known limitations and improvements
- Only minimum versions (`>=`), no upper bounds and no lock file, so a new major version can break the build without any code change. Idea: a pinned lock file (for example from `pip freeze`) for the image.
- No SPARQL library is needed: [`sparql.py`](app/sparql.md) uses only Python's built-in `urllib`.
