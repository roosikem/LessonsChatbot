# `backend/.env.example`

> The template for `backend/.env`: every setting with a short comment. Copy it, fill in the secrets, and choose local models or Amazon Bedrock.

**Part of:** [Deployment](../../flows/deployment.md) · [Agents](../../flows/agents.md) · [Storage and versions](../../flows/storage-and-versions.md)  ·  **Layer:** Config

## Purpose
All features and connections are switched in one place, without code changes. This file shows every name with a working local default. The real `.env` holds secrets (passwords, tokens) and must never be committed; on Fargate the same values come from the platform's secret store as environment variables.

## How it works
1. `cp backend/.env.example backend/.env`, then edit `backend/.env`.
2. [settings.py](app/settings.md) reads `backend/.env` at start (real environment variables win over the file).
3. The startup check stops the app with one clear message if a combination does not work.
4. `docker compose --env-file .env ...` (run in `backend/`) also reads it: `NEO4J_PASSWORD` sets the password of the local Neo4j container, `FUSEKI_ADMIN_PASSWORD` the one of the local Fuseki container.

Two things to know about the copied file:
- An empty value such as `GRADER_PROVIDER=` means "not set, use the default" (settings drop empty values before checking), so a straight copy starts.
- `DATA_DIR=./data`, `DATASET_CONFIG=./config/dataset.yaml` and `ASSISTANT_CONFIG=./config/assistant.yaml` are relative to the folder you start from (the file says so). Start the app and the CLI from `backend/`, or leave these lines out to use the built-in defaults.

## Key components
The file has these sections. Every name is explained in [settings.py](app/settings.md); here is how to set them up.

### 1. Local models with Ollama (default, free, offline)
[Ollama](../../glossary.md) runs models on the laptop.
```env
LLM_PROVIDER=ollama
LLM_MODEL_ID=gemma4:12b           # any Ollama chat model
EMBEDDING_PROVIDER=ollama
EMBEDDING_MODEL_ID=bge-m3
EMBEDDING_DIM=1024
OLLAMA_URL=http://localhost:11434
```
Ollama must be running and the models pulled (`ollama pull bge-m3`, `ollama pull <model>`). After changing the embedding model, run `python -m app.cli ingest` again: an index only works with the model it was built with.

### 2. Amazon Bedrock (Claude, Nova and others on AWS)
```env
LLM_PROVIDER=bedrock
LLM_MODEL_ID=us.amazon.nova-2-lite-v1:0     # an inference profile that is enabled in your account
EMBEDDING_PROVIDER=bedrock                  # optional; ollama embeddings + Bedrock LLM also works
EMBEDDING_MODEL_ID=amazon.titan-embed-text-v2:0
EMBEDDING_DIM=1024                          # Titan V2: 1024, 512 or 256
BEDROCK_AWS_PROFILE=default                 # laptop: profile from ~/.aws used only for Bedrock
BEDROCK_REGION=us-east-1
```
- Check in the Bedrock console that the model is enabled in that region.
- On Fargate leave `BEDROCK_AWS_PROFILE` out or empty; the task role is used. If Bedrock is in another account, set `BEDROCK_ROLE_ARN` (commented out in the file).
- Retries and pools: `BEDROCK_MAX_ATTEMPTS=4`, `BEDROCK_MAX_CONNECTIONS=32`, `BEDROCK_READ_TIMEOUT=60`.
- Mixing is fine: the model and the embeddings are set separately.

### 3. Evidence grader (optional second model)
The grader checks each found lesson before the answer is written; if none fit, the bot says so instead of stretching.
```env
FEATURE_EVIDENCE_GRADING=true
GRADER_PROVIDER=bedrock                     # empty or left out: use LLM_PROVIDER
GRADER_MODEL_ID=us.amazon.nova-2-lite-v1:0  # tested good; nova-micro was too lenient
GRADER_MAX_CANDIDATES=8
AGENT_GRADER_URL=                           # set to run it as its own service: python -m app.cli serve grader
```
`FEATURE_PARALLEL_GRADING=true` (in the Latency section) runs it at the same time as the final answer.

### 4. Neo4j (optional graph)
```env
FEATURE_NEO4J=true
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=<secret>
NEO4J_DATABASE=neo4j
NEO4J_FULLTEXT_ANALYZER=english
SEARCH_STORE=neo4j                          # optional: let Neo4j also do the search; memory is the default
```
Local Neo4j: `docker compose --env-file .env up -d neo4j` in `backend/`, then `python -m app.cli ingest` (builds the index and the graph). With `FEATURE_NEO4J=true` the chat gets "related lessons". `SEARCH_STORE=neo4j` without `FEATURE_NEO4J=true` and `NEO4J_URI` stops at start.

### 5. SPARQL knowledge graph (optional, read-only data source)
```env
DATA_SOURCE=sparql
FEATURE_SPARQL_SOURCE=true
SPARQL_ENDPOINT=http://localhost:3030/lessons/sparql   # local Fuseki stand-in
SPARQL_TOKEN=<secret>                 # Bearer token, or:
SPARQL_USER=
SPARQL_PASSWORD=<secret>
FUSEKI_ADMIN_PASSWORD=<secret>              # only for the local Fuseki container
```
With `DATA_SOURCE=sparql` and the default `DATASET_CONFIG`, the app uses [dataset.sparql.yaml](config/dataset.sparql.yaml.md) by itself. Local stand-in: `docker compose --env-file .env --profile sparql-sim up -d fuseki`.

### 6. S3 storage (for containers on Fargate)
The file has a "Storage" section with `STORAGE=local`, `INDEX_POLL_SECONDS=30` and the `S3_*` names commented out (details in the [deployment flow](../../flows/deployment.md)). With S3, index versions, raw uploads and (optionally) feedback are shared by all containers.
```env
STORAGE=s3
S3_BUCKET=<bucket>
S3_PREFIX=lessons
S3_REGION=<region>
FEEDBACK_STORE=s3              # one object per vote; needs STORAGE=s3
INDEX_POLL_SECONDS=30          # how often a container checks for a new index version
# local stand-in only (moto):
S3_ENDPOINT_URL=http://localhost:9000
S3_ACCESS_KEY=local-test
S3_SECRET_KEY=local-test
# laptop with a real bucket:
S3_AWS_PROFILE=<profile>
```
On Fargate: no keys, the task role needs S3 and Bedrock rights. See [storage and versions](../../flows/storage-and-versions.md).

### 7. The other sections
- **Data**: `DATA_SOURCE=file`, `DATA_DIR`, `DATASET_CONFIG` ([dataset.yaml](config/dataset.yaml.md)).
- **Search**: `SEARCH_STORE`, `TOP_K_*`, `FEATURE_VECTOR_SEARCH`, `FEATURE_KEYWORD_SEARCH`, `FEATURE_CONTEXT_BOOST`, `SCORE_W_CONTEXT`, `SCORE_W_RELATED`, `CONFIDENCE_MIN_SIMILARITY` (calibrate per embedding model with `python -m app.cli eval retrieval`).
- **Agents as separate services**: `AGENT_*_URL`, empty = in-process. See [agents](../../flows/agents.md).
- **Ranking from users**: `FEATURE_SCORE_ORDER`, `FEATURE_FEEDBACK_BOOST`, `SCORE_W_FEEDBACK`, `FEEDBACK_MIN_SIMILARITY`, `FEEDBACK_HALF_LIFE_DAYS`. See [feedback](../../flows/feedback.md).
- **Load and Bedrock resilience**: `MAX_CONCURRENT_ANSWERS`, `BUSY_WAIT_SECONDS`, `BEDROCK_*`, `USER_HEADER` (commented out).
- **Latency**: `FEATURE_PARALLEL_GRADING`, `FEATURE_ANSWER_CACHE`, `ANSWER_CACHE_*`, `FEATURE_STOP_RULE`, `FEATURE_AUTO_RESOLVE_CONTEXT`, `FEATURE_REASONS_IN_CODE`, `TOOL_TEXT_CHARS`.
- **Answer behaviour**: `FEATURE_CLARIFYING_QUESTIONS`, `FEATURE_GROUNDING_CHECKS`.
- **Feedback / admin / UI**: `FEATURE_FEEDBACK`, `FEEDBACK_STORE`, `FEATURE_UPLOAD_UI`, `ADMIN_TOKEN` (secret, required with uploads), `UPLOAD_MAX_MB`, `UPLOAD_MAX_ROWS`, `FEATURE_STREAMING`, `FEATURE_DEBUG_PANEL`.
- **Wording**: `ASSISTANT_CONFIG` ([assistant.yaml](config/assistant.yaml.md)); `APP_NAME` (commented out) renames the app in the UI without editing that file.
- **Planned, not built yet**: a comment block (`SEARCH_STORE=pgvector`, `FEEDBACK_STORE=dynamodb`, rerank, AgentCore guardrails, LLM enrichment at ingest, MCP server, search-first fast path); setting those has no effect.

## Configuration
This file is the settings. Full list with defaults and meaning: [settings.py](app/settings.md).

## Dependencies
- **Used by:** you (copied to `backend/.env`), [settings.py](app/settings.md) (reads `.env`), `backend/docker-compose.yml` (`--env-file .env`).
- **Uses:** nothing.

## Example
A laptop setup with local embeddings, Bedrock for the answer, a small Bedrock grader and Neo4j:
```env
LLM_PROVIDER=bedrock
LLM_MODEL_ID=us.amazon.nova-2-lite-v1:0
EMBEDDING_PROVIDER=ollama
EMBEDDING_MODEL_ID=bge-m3
BEDROCK_AWS_PROFILE=default
FEATURE_EVIDENCE_GRADING=true
GRADER_MODEL_ID=us.amazon.nova-2-lite-v1:0
FEATURE_NEO4J=true
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=<secret>
```
(`GRADER_PROVIDER` left out, so the grader also uses Bedrock.) Then `python -m app.cli ingest` and `uvicorn app.api:create_app --factory --port 8000` from `backend/`.

## Known limitations and improvements
- `FUSEKI_ADMIN_PASSWORD` is read by Docker Compose only, not by the app; the comment says so, but it sits among the app's SPARQL source settings.
- `AGENT_GRADER_URL` sits in the grader section, not with the other `AGENT_*_URL` names.
- Relative paths depend on the start folder. Idea: resolve them against `backend/` in the code.
