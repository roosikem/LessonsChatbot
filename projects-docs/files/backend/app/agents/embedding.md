# `backend/app/agents/embedding.py`

> The embedding agent: a thin wrapper that turns texts into vectors with the configured embedding model and returns them as plain JSON lists.

**Part of:** [Agents](../../../../flows/agents.md) · [Load data](../../../../flows/load-data.md) · [Ask a question](../../../../flows/ask-a-question.md)  ·  **Layer:** Models

## Purpose

Both loading data (embedding every lesson) and answering (embedding the question) need the same embedding model. Putting it behind one agent means it can run in-process or as its own service (`AGENT_EMBEDDING_URL`), and everyone uses the same model. An [embedding](../../../../glossary.md) is a list of numbers that stands for the meaning of a text.

## How it works

1. On start it builds an embedder with `make_embedder(settings)` from [`embeddings.py`](../embeddings.md), unless one is passed in (tests pass a fake).
2. `embed` calls the embedder and turns the numpy array into a list of lists, so it can be sent as JSON.

## Key components

- `EmbeddingAgent(settings, embedder=None)`: `name = "embedding"`, `methods = ("info", "embed")`.
- `info()`: `{"model_id": <embedding model id>}`.
- `embed(texts, kind="document")`: one list of floats per text. `kind` is "document" or "query".

## Configuration

None read here directly. The embedding provider and model are chosen in [`embeddings.py`](../embeddings.md) (see [`settings.py`](../settings.md)). `AGENT_EMBEDDING_URL` (in [`__init__.py`](__init__.md)) decides whether this agent runs in-process or as a service.

## Dependencies

- **Used by:** [`__init__.py`](__init__.md) (`embedding_client`, `make_agent("embedding")`), callers then go through [`clients.py`](clients.md) (`EmbeddingProxy`).
- **Uses:** [`embeddings.py`](../embeddings.md) (`make_embedder`).

## Example

```python
LocalClient(EmbeddingAgent(settings)).call("embed", texts=["door fault after hotfix"], kind="query")
# -> [[0.012, -0.044, ...]]   (one vector; length depends on the model)
```

## Known limitations and improvements

- Vectors are sent as JSON lists of floats, which is large over HTTP. Idea: a binary format if the embedding agent is split out and uploads are big.
