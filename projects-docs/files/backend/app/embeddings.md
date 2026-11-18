# `backend/app/embeddings.py`

> Turns texts into embedding vectors with Bedrock (Titan or Cohere), Ollama, or an offline hash stand-in, and keeps document embeddings in a disk cache.

**Part of:** [Load data](../../../flows/load-data.md) · [Ask a question](../../../flows/ask-a-question.md) · [Agents](../../../flows/agents.md)  ·  **Layer:** Models

## Purpose
Vector search needs an *embedding* for each lesson and for each question: a list of numbers where texts with similar meaning are close together (see the [glossary](../../../glossary.md)). The model is chosen in `.env`, so the same code runs on a laptop (Ollama `bge-m3`), on AWS (Bedrock Titan V2 or Cohere Embed), or in tests with no model at all (hash embedder). Re-ingesting the same 27 lessons should not pay for embeddings twice, so document vectors are cached on disk.

## How it works
1. `make_embedder(settings)` picks the inner embedder from `EMBEDDING_PROVIDER` and wraps it in `CachedEmbedder`.
2. `embed(texts, kind)` returns a numpy array, one row per text. `kind` is `"document"` (lessons) or `"query"` (questions); Cohere uses different input types for the two.
3. `CachedEmbedder`:
   - queries always go to the model (never cached);
   - documents are keyed by the SHA-256 of their text; only missing ones are embedded, then the whole cache is written back as JSON. It is written to a temporary file first (`<name>.<process id>.tmp`) and then renamed over the old file, so a crash never leaves half a file behind.
   - The cache file name includes the model id and, if known, the dimension, for example `data/cache/embeddings-ollama_bge-m3.json` (the `:` in `ollama:bge-m3` becomes `_`), so two models never mix.

## Key components
- `BedrockEmbedder(model_id, profile, region, dim, settings)`: Bedrock `invoke_model`.
  - Titan: one call per text, first 20,000 characters, `dimensions = dim`, normalized.
  - Cohere (`model_id` starts with `cohere.embed`): batches of 96 texts, first 2,000 characters each, `search_query` or `search_document`.
- `OllamaEmbedder(model, url)`: `POST /api/embed` in batches of 32, 300 s timeout. `model_id` is `ollama:<model>`.
- `HashEmbedder(dim=256)`: offline stand-in for tests. Each word adds 1 to one of 256 slots chosen by its MD5 hash. It only measures shared words, not meaning.
- `CachedEmbedder(inner, cache_dir)`: disk cache for documents, as above.
- `make_embedder(settings)`: the configured embedder, always cached under `<DATA_DIR>/cache`.

## Configuration
| Setting | Default | Effect |
|---|---|---|
| `EMBEDDING_PROVIDER` | ollama | `ollama`, `bedrock` or `local` (hash) |
| `EMBEDDING_MODEL_ID` | bge-m3 | Model name for Ollama, or Bedrock model id (for example Titan V2 or Cohere Embed) |
| `EMBEDDING_DIM` | 1024 | Titan output size; also part of the Bedrock cache file name |
| `OLLAMA_URL` | http://localhost:11434 | Ollama server |
| `BEDROCK_AWS_PROFILE`, `BEDROCK_REGION` | none, us-east-1 | Bedrock client (built by [llm.py](llm.md) `bedrock_client`, with retries and pool settings) |
| `DATA_DIR` | `backend/data` | Cache folder is `<DATA_DIR>/cache`. A relative path set in `.env` is taken from the folder the app is started in |

## Dependencies
- **Used by:** [agents/embedding.py](agents/embedding.md) (the embedding agent wraps `make_embedder`); tests use `HashEmbedder` and `CachedEmbedder` directly.
- **Uses:** [llm.py](llm.md) (`bedrock_client`), numpy, `urllib` for Ollama.

## Example
```python
e = CachedEmbedder(HashEmbedder(), "data/cache")
v = e.embed(["Door software change again not regression tested"])
v.shape        # (1, 256)
e.model_id     # "local-hash"
# a second call with the same text reads data/cache/embeddings-local-hash-256.json, no new embedding
```

## Known limitations and improvements
- Titan is called once per text; ingesting thousands of lessons means thousands of calls. Idea: run them in parallel within Bedrock limits.
- The cache is one JSON file, rewritten in full after each new batch. The rename makes each write all-or-nothing, but there is no lock: two processes ingesting at once could still drop each other's new entries (the last rename wins). That only costs a re-embed later, not wrong vectors.
- The cache key is only the text, not the dimension or `kind`; the file name holds the model and dimension, so this is fine as long as documents are always embedded with `kind="document"`.
- Cohere truncates at 2,000 characters, Titan at 20,000. Long lessons lose their end with Cohere.
- `HashEmbedder` gives no real meaning; offline test results say nothing about real search quality.
