# `backend/docker-compose.yml`

> Starts the local helpers for development: Neo4j, a Fuseki SPARQL server that stands in for SPARQL source, and the app container as it would run on Fargate.

**Part of:** [Deployment](../../flows/deployment.md) · [Load data](../../flows/load-data.md) · [Storage and versions](../../flows/storage-and-versions.md)  ·  **Layer:** Tooling

## Purpose
A deployment may use a Neo4j database and a SPARQL knowledge graph. To build and test without them, this file starts look-alikes on your laptop. It also lets you run the real container image against a local S3 stand-in, to check the Fargate setup before deploying. Docker Compose starts several containers from one file (see the [glossary](../../glossary.md)).

## How it works
Three services. All ports bind to `127.0.0.1`, so they are only reachable from this machine.
1. `neo4j` (always on with `docker compose up`): image `neo4j:5.26-community`, ports 7474 (browser) and 7687 (bolt, the driver protocol). Password from `NEO4J_PASSWORD` in `.env` (compose stops with an error if it is not set). Heap 1 GB, page cache 512 MB. Data kept in the volume `neo4j-data`.
2. `fuseki` (profile `sparql-sim`): image `secoresearch/fuseki` pinned by digest to version 6.2.0 (amd64), port 3030. Admin password from `FUSEKI_ADMIN_PASSWORD`. Writes and updates enabled so test data can be loaded. Start: `docker compose --env-file .env --profile sparql-sim up -d fuseki`.
3. `app` (profile `app`): builds the root [`Dockerfile`](../Dockerfile.md) as `lessons-chatbot:local`, maps host port 8080 to container port 8000. Runs with `STORAGE=s3` and `FEEDBACK_STORE=s3` against a moto S3 stand-in on the host (`http://host.docker.internal:9000`, fake keys `local-test`), checks for new index versions every 5 s, uses Ollama on the host for embeddings (`bge-m3`), Bedrock (or `CONTAINER_LLM_PROVIDER`) for the model, and turns on the admin upload with `ADMIN_TOKEN` from `.env`. Bedrock credentials for a local test are passed from the shell environment (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN`); nothing is mounted, and on Fargate the task role is used instead. Start the S3 stand-in first: `pip install "moto[server]"` and `moto_server -p 9000`, then `docker compose --env-file .env --profile app up -d --build app`.

A profile means the service only starts when you name that profile.

## Key components
- `services.neo4j`, `services.fuseki`, `services.app`, `volumes.neo4j-data`.

## Configuration
From `backend/.env` (passed with `--env-file .env`):
- `NEO4J_PASSWORD` (required for `neo4j`).
- `FUSEKI_ADMIN_PASSWORD` (required for `fuseki`).
- `ADMIN_TOKEN` (for the `app` admin page).
- `CONTAINER_LLM_PROVIDER` (default `bedrock`), `CONTAINER_LLM_MODEL_ID` (default `us.amazon.nova-2-lite-v1:0`).

Set inside the `app` service: `STORAGE`, `S3_BUCKET=lessons`, `S3_ENDPOINT_URL`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `FEEDBACK_STORE`, `INDEX_POLL_SECONDS=5`, `DATASET_CONFIG`, `EMBEDDING_PROVIDER=ollama`, `EMBEDDING_MODEL_ID=bge-m3`, `OLLAMA_URL`, `LLM_PROVIDER`, `LLM_MODEL_ID`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN` (from the shell, empty by default), `FEATURE_UPLOAD_UI=true`.

## Dependencies
- **Used by:** developers running Neo4j, the Fuseki stand-in for SPARQL source, or the app container locally.
- **Uses:** the root [`Dockerfile`](../Dockerfile.md). The app reads its settings through [`settings.py`](app/settings.md).

## Example
```
cd backend
docker compose --env-file .env up -d neo4j
```
Neo4j Browser is then at `http://localhost:7474`; the app connects with `NEO4J_URI=bolt://localhost:7687`.

## Known limitations and improvements
- Fuseki runs as `linux/amd64`, so on Apple Silicon it runs under emulation (slower).
- Loading the data into Fuseki is a separate, manual step not in this file (an RDF file made from the CSVs is uploaded into an in-memory dataset `lessons`). Because the dataset is in memory, it is gone after a Fuseki restart.
- `S3_ACCESS_KEY`/`S3_SECRET_KEY` are fake values for the local moto server only.
