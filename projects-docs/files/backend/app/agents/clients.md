# `backend/app/agents/clients.py`

> Helpers for code that calls an agent; today one class, `EmbeddingProxy`, which looks like a normal embedder but sends the work to the embedding agent.

**Part of:** [Agents](../../../../flows/agents.md) · [Load data](../../../../flows/load-data.md)  ·  **Layer:** Agent

## Purpose

Several parts (building the index, the retrieval agent, the graph agent, ingest) need "something with `.embed()` and `.model_id`". They should not talk to the embedding model directly, because the embedding agent may run as its own service. `EmbeddingProxy` gives them that familiar shape and forwards each call through the embedding client (local or HTTP).

An [embedding](../../../../glossary.md) is a list of numbers that stands for the meaning of a text, so similar texts get similar numbers.

## How it works

- `model_id` asks the embedding agent once (`call("info")`) and remembers the answer.
- `embed(texts)` sends the texts in batches of 64 (`call("embed", texts=..., kind=...)`), joins the results and returns one numpy array of float32. Batches keep each call well inside its timeout.

## Key components

- `EmbeddingProxy(client)`: wraps an embedding client from [`transport.py`](transport.md).
- `EmbeddingProxy.model_id`: the embedding model's ID, fetched once.
- `EmbeddingProxy.embed(texts, kind="document", batch=64)`: returns an array with one row per text. `kind` is "document" or "query" (passed on to the embedder).

## Configuration

None. The batch size 64 is fixed in the code (a parameter with a default).

## Dependencies

- **Used by:** [`__init__.py`](__init__.md) (`embedder`), [`ingest.py`](ingest.md), [`retrieval.py`](retrieval.md), [`graph.py`](graph.md). Agent modules may import this file; code outside `app/agents/` goes through the wiring instead.
- **Uses:** an embedding client that calls [`embedding.py`](embedding.md).

## Example

```python
proxy = EmbeddingProxy(embedding_client(settings))
vecs = proxy.embed(["Door software change again not regression tested"] * 130)
# 3 calls to the embedding agent (64 + 64 + 2 texts); vecs.shape == (130, <model dimension>)
```

## Known limitations and improvements

- An empty list of texts returns an empty array with no shape for the vector size; not visible in the code whether callers rely on that.
- Batches run one after the other; idea: run them in parallel for big uploads against a remote embedding agent.
