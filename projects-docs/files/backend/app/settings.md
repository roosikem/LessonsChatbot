# `backend/app/settings.py`

> Every setting of the app in one class, read from `backend/.env` or environment variables, with a check that the combination makes sense.

**Part of:** [Agents](../../../flows/agents.md) · [Deployment](../../../flows/deployment.md) · [Storage and versions](../../../flows/storage-and-versions.md)  ·  **Layer:** Config

## Purpose
Every feature can be switched on or off with a flag, and the model, Neo4j and the SPARQL source are chosen in `.env`. This file is where those flags live. Code never reads environment variables itself; it asks `get_settings()`. For example, switching the chatbot from a local model to Claude or Nova on Amazon Bedrock is `LLM_PROVIDER=bedrock` plus `LLM_MODEL_ID=...`, no code change.

## How it works
1. `Settings` is a [pydantic-settings](../../../glossary.md) class: each field is one setting. The field `llm_provider` is read from the environment variable `LLM_PROVIDER` (upper case, same name).
2. Values come from real environment variables first, then from `backend/.env`. Unknown names are ignored (`extra="ignore"`).
3. Before the values are checked, `empty_means_unset()` drops empty values: `GRADER_PROVIDER=` (nothing after `=`, as in `.env.example`) means "use the default", not an empty string.
4. After loading, `check_combinations()` runs:
   - With `DATA_SOURCE=sparql` and the default `dataset.yaml`, it switches `DATASET_CONFIG` to `dataset.sparql.yaml` by itself.
   - It collects every bad combination and stops the app with one message listing them all (for example "SEARCH_STORE=neo4j needs FEATURE_NEO4J=true and NEO4J_URI; STORAGE=s3 needs S3_BUCKET").
5. `get_settings()` builds the object once and caches it (`lru_cache`).

## Key components
- `BACKEND_DIR`: the `backend/` folder. Default paths are built from it.
- `Settings`: the class, fields listed below.
- `Settings.empty_means_unset(data)`: runs first; removes keys whose value is `""`, so the code default applies.
- `Settings.check_combinations()`: the startup check.
- `get_settings()`: the one shared settings object.

## Configuration
Grouped by purpose. "Default" is the value in the code when the setting is missing. Where [`.env.example`](../env.example.md) suggests a different value, it is noted.

### Models (LLM and embeddings)
- `LLM_PROVIDER` (default `ollama`): who runs the chat model. `ollama` (local) or `bedrock`.
- `LLM_MODEL_ID` (default none): the model name, for example `gemma4:12b` on Ollama or `us.amazon.nova-2-lite-v1:0` on Bedrock. No default in the code, so set it.
- `LLM_MAX_TOOL_ROUNDS` (default `2`): at most this many rounds of tool calls (searches) by the answer agent; then the final answer is written.
- `EMBEDDING_PROVIDER` (default `ollama`): who makes the [embeddings](../../../glossary.md) (number lists that capture meaning). `ollama`, `bedrock` or `local` (a hash, for tests only).
- `EMBEDDING_MODEL_ID` (default `bge-m3`): the embedding model. The index must be built and searched with the same model.
- `EMBEDDING_DIM` (default `1024`): length of each vector.
- `OLLAMA_URL` (default `http://localhost:11434`): where Ollama runs.

### Amazon Bedrock connection
- `BEDROCK_AWS_PROFILE` (default none): AWS profile for Bedrock calls on a laptop.
- `BEDROCK_REGION` (default `us-east-1`).
- `BEDROCK_ROLE_ARN` (default none): Bedrock in another AWS account; the app assumes this role.
- `BEDROCK_MAX_ATTEMPTS` (default `4`): retries after the first try, with backoff, on throttling and timeouts.
- `BEDROCK_MAX_CONNECTIONS` (default `32`): connection pool per Bedrock client.
- `BEDROCK_READ_TIMEOUT` (default `60`): seconds.

### Data source
- `DATA_SOURCE` (default `file`): `file` (CSV/Excel from the mapping) or `sparql` (SPARQL).
- `DATA_DIR` (default `backend/data`): local folder for index versions, uploads, feedback, eval runs. `.env.example` uses `./data`, which is relative to the folder you start the app in.
- `DATASET_CONFIG` (default `backend/config/dataset.yaml`): the [mapping](../config/dataset.yaml.md) from columns to roles.
- `ASSISTANT_CONFIG` (default `backend/config/assistant.yaml`): [wording and word lists](../config/assistant.yaml.md).

### Storage (local disk or S3)
- `STORAGE` (default `local`): `local` or `s3`. With `s3`, index versions, raw uploads and the `CURRENT` pointer are in S3 and shared by all containers. See [storage and versions](../../../flows/storage-and-versions.md).
- `S3_BUCKET` (default none): required when `STORAGE=s3`.
- `S3_PREFIX` (default `lessons`): folder inside the bucket.
- `S3_REGION` (default `us-east-1`).
- `S3_ENDPOINT_URL` (default none): only for a local S3 stand-in (moto).
- `S3_AWS_PROFILE` (default none): for local runs; on Fargate the task role is used.
- `S3_ACCESS_KEY`, `S3_SECRET_KEY` (default none): only for S3 stand-ins.
- `INDEX_POLL_SECONDS` (default `30`): how often a container checks for a new index version.

### Search
- `SEARCH_STORE` (default `memory`): `memory` (in-process index) or `neo4j`. `pgvector` is rejected as "planned".
- `TOP_K_CANDIDATES` (default `20`): size of the wider candidate list (used inside the memory and Neo4j search, and for context look-ups).
- `TOP_K_ANSWER` (default `8`): how many hits a search call returns when the caller gives no `k`.
- `FEATURE_VECTOR_SEARCH` (default `true`): meaning-based search on embeddings.
- `FEATURE_KEYWORD_SEARCH` (default `true`): word-based search ([BM25](../../../glossary.md) in memory, Lucene full-text in Neo4j).
- `FEATURE_CONTEXT_BOOST` (default `true`): lessons that match the user's context (stage, topic...) get a small extra score.
- `SCORE_W_CONTEXT` (default `0.05`): size of that context boost.
- `SCORE_W_RELATED` (default `0.15`): boost for lessons linked to the same or a comparable project (context-source item).
- `CONFIDENCE_MIN_SIMILARITY` (default `0.45`): below this vector similarity a hit is never more than "low" confidence. Tuned for bge-m3 with the eval.
- `FEATURE_AUTO_RESOLVE_CONTEXT` (default `true`): search maps loose values ("commissioning phase") to the values in the data ("Commissioning").

### Neo4j (optional graph)
- `FEATURE_NEO4J` (default `false`): on: ingest also builds the graph and the chat gets "related lessons".
- `NEO4J_URI` (default none; `.env.example`: `bolt://localhost:7687`).
- `NEO4J_USER` (default none; `.env.example`: `neo4j`).
- `NEO4J_PASSWORD` (default none): secret.
- `NEO4J_DATABASE` (default `neo4j`).
- `NEO4J_FULLTEXT_ANALYZER` (default `english`): Lucene analyzer for keyword search; match the language of the lesson texts.

### SPARQL knowledge graph (optional, read-only source)
- `FEATURE_SPARQL_SOURCE` (default `false`): needed for `DATA_SOURCE=sparql`.
- `SPARQL_ENDPOINT` (default none): the SPARQL URL.
- `SPARQL_TOKEN` (default none): Bearer token. Or use:
- `SPARQL_USER`, `SPARQL_PASSWORD` (default none): basic auth.

### Agents as separate services
Empty means the agent runs inside the app's process. A URL means the app calls it over HTTP (start it with `python -m app.cli serve <agent>`). See [agents flow](../../../flows/agents.md).
- `AGENT_EMBEDDING_URL`, `AGENT_RETRIEVAL_URL`, `AGENT_GRAPH_URL`, `AGENT_SPARQL_URL`, `AGENT_GRADER_URL` (default none).

### Answer behaviour and checks
- `FEATURE_CLARIFYING_QUESTIONS` (default `true`): a too-vague first question ("help") gets a question back instead of a search.
- `FEATURE_GROUNDING_CHECKS` (default `true`): code checks after the model answers: a cited id was really retrieved, the quote is really in the text, the reasons match the data.
- `FEATURE_SCORE_ORDER` (default `true`): lessons are listed in search-score order, not the model's order.
- `FEATURE_REASONS_IN_CODE` (default `true`): "why relevant" is built from the search results, not written by the model.
- `TOOL_TEXT_CHARS` (default `600`): lesson text sent to the model per hit; the full text is kept for the checks.

### Evidence grader agent
- `FEATURE_EVIDENCE_GRADING` (default `false`): a second, smaller model checks each found lesson before the answer is written; if none fit, the bot says so.
- `GRADER_PROVIDER` (default none = use `LLM_PROVIDER`): `ollama` or `bedrock`.
- `GRADER_MODEL_ID` (default none = use `LLM_MODEL_ID`).
- `GRADER_MAX_CANDIDATES` (default `8`): how many lessons the grader sees.
- `FEATURE_PARALLEL_GRADING` (default `true`): the grader runs at the same time as the final answer; its grades are applied afterwards.

### Speed (latency)
- `FEATURE_ANSWER_CACHE` (default `true`): the same question on the same index and settings returns the stored answer (per container).
- `ANSWER_CACHE_TTL_SECONDS` (default `900`), `ANSWER_CACHE_SIZE` (default `500`).
- `FEATURE_STOP_RULE` (default `true`): a search with a clear good result goes straight to the final answer, skipping one model round.

### Feedback and ranking from users
- `FEATURE_FEEDBACK` (default `true`): thumbs up/down in the UI and `/api/feedback`.
- `FEEDBACK_STORE` (default `file`): `file` (`data/feedback.jsonl`) or `s3` (needs `STORAGE=s3`).
- `FEATURE_FEEDBACK_BOOST` (default `true`): votes on a lesson nudge it up or down for similar questions.
- `SCORE_W_FEEDBACK` (default `0.1`): largest effect of feedback on a score.
- `FEEDBACK_MIN_SIMILARITY` (default `0.6`): a vote only counts for questions at least this similar.
- `FEEDBACK_HALF_LIFE_DAYS` (default `180`): votes lose half their weight after this many days.
- `EVAL_QUESTIONS`, `EVAL_DATASET` (default none): the question set and its dataset mapping for `app.cli eval`; both needed to run an eval.
- `APP_NAME` (default none): the app's name in the UI and the API title; overrides `app_name` in `config/assistant.yaml`.
- `USER_HEADER` (default none): HTTP header with the signed-in user from SSO, used as the voter id.

### Load limits
- `MAX_CONCURRENT_ANSWERS` (default `8`): answers at the same time per container; more wait, then get "busy".
- `BUSY_WAIT_SECONDS` (default `20`).

### Admin upload and UI
- `FEATURE_UPLOAD_UI` (default `false`): the admin page and its API.
- `ADMIN_TOKEN` (default none): required when uploads are on.
- `UPLOAD_MAX_MB` (default `20`), `UPLOAD_MAX_ROWS` (default `20000`).
- `FEATURE_STREAMING` (default `true`): the chat page shows steps while the answer is made.
- `FEATURE_DEBUG_PANEL` (default `false`): the chat page shows the tool trace.

### Combinations the startup check rejects
| Combination | Message |
|---|---|
| `SEARCH_STORE=pgvector` | planned but not built yet |
| `SEARCH_STORE` not memory/neo4j | must be memory or neo4j |
| `SEARCH_STORE=neo4j` without `FEATURE_NEO4J=true` and `NEO4J_URI` | needs both |
| `DATA_SOURCE=sparql` without `FEATURE_SPARQL_SOURCE=true` and an endpoint | needs both |
| `LLM_PROVIDER` / `GRADER_PROVIDER` not ollama/bedrock | must be ollama or bedrock |
| `EMBEDDING_PROVIDER` not ollama/bedrock/local | must be one of these |
| `STORAGE` not local/s3, or `s3` without `S3_BUCKET` | |
| `FEEDBACK_STORE` not file/s3, or `s3` without `STORAGE=s3` | |
| `FEATURE_UPLOAD_UI=true` without `ADMIN_TOKEN` | |

## Dependencies
- **Used by:** almost every file; the entry points are [api.py](api.md) and [cli.py](cli.md), which call `get_settings()`. Agents get the settings object passed in. [evaluation.py](evaluation.md) and `cli bench` make changed copies with `model_copy(update=...)`.
- **Uses:** nothing in the project; reads `backend/.env`.

## Example
```env
LLM_PROVIDER=bedrock
LLM_MODEL_ID=us.amazon.nova-2-lite-v1:0
SEARCH_STORE=neo4j
FEATURE_NEO4J=false
```
Start-up stops with: `SEARCH_STORE=neo4j needs FEATURE_NEO4J=true and NEO4J_URI`. Set `FEATURE_NEO4J=true` and `NEO4J_URI=bolt://localhost:7687` and it starts.

## Known limitations and improvements
- Relative paths (`DATA_DIR=./data`, `DATASET_CONFIG=./config/dataset.yaml` in `.env.example`) depend on the folder you start the app from (`.env.example` says so: start from `backend/`), while the code defaults are absolute. Idea: resolve relative paths against `BACKEND_DIR`.
- Because empty means "unset", there is no way to set a text setting to an empty string on purpose (not needed by any setting today).
- `LLM_MODEL_ID` has no default; a missing value is only noticed when the answer agent is first built (`make_llm` raises "LLM_MODEL_ID is not set"), which the API does on the first question.
- `DATA_SOURCE` and `FEEDBACK_STORE` values beyond the listed ones are only partly checked (`DATA_SOURCE` is not checked at all).
- Settings made with `model_copy(update=...)` skip the startup check.
