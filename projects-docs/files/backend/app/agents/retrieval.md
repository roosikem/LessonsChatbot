# `backend/app/agents/retrieval.py`

> The retrieval agent: it answers search and lookup calls from the in-memory index, and switches to a new index version when one is published.

**Part of:** [Ask a question](../../../../flows/ask-a-question.md) · [Agents](../../../../flows/agents.md) · [Storage and versions](../../../../flows/storage-and-versions.md) · [Feedback](../../../../flows/feedback.md)  ·  **Layer:** Agent

## Purpose
The answer agent needs one place to ask "find lessons about X", "show lesson 1003" or "which stages come up most often". This file is that place when `SEARCH_STORE=memory` (the default). It wraps the [in-memory store](../search/memory.md) behind a small list of named methods, so the same calls can run in the same process or over HTTP (see [agents flow](../../../../flows/agents.md)). When `SEARCH_STORE=neo4j`, the [graph agent](graph.md) answers the same calls instead.

An *agent* here is a plain Python class with a list of callable methods; see the [glossary](../../../../glossary.md).

## How it works
1. On start it loads the dataset mapping, opens the index store (local disk or S3 mirror), and loads the current index version into a `MemoryStore`.
2. If `FEATURE_FEEDBACK_BOOST` is on, it also builds a `FeedbackBoost` so thumbs up/down votes can nudge the ranking.
3. Before each call it runs `_refresh()`: it asks the index store for the current version. If that differs from the loaded one (for example after an admin upload), it loads the new version. No restart needed.
4. `search()` cleans the requested context, optionally maps loose values to real ones (`ctx.align`, for example "comissioning" to "Commissioning"; a value is only mapped when there is one clear match, otherwise it is kept as typed and listed in `context_unresolved` with its candidates, e.g. project "line" fits Line 4 and Line 5), resolves `related_to` (for example a project name) to a real context item, runs the store search, and returns plain JSON-like dicts.

## Key components
- `RetrievalAgent(settings, embedding_client, store=None)`: builds the agent. A fixed `store` (used in tests) turns off auto-refresh.
- `methods`: the names other agents may call: `search`, `get_lesson`, `resolve_context`, `comparable_items`, `count_by`, `dimensions`, `sources`, `version`.
- `search(query, context=None, related_to=None, k=None)`: returns `hits` (id, title, text, context, signals, score, similarity, reasons) plus what context was used, mapped, or left unresolved, and any unknown `related_to` sources. `k` defaults to `TOP_K_ANSWER`.
- `get_lesson(id)`: one lesson as a dict, or `{"error": "no lesson <id>"}`.
- `resolve_context(term, dimension=None)`: maps a user word to known values (see [context.py](../context.md)).
- `comparable_items(source, name, limit=5)`: items similar to a named one, for example projects like "Valoria Metro Line 5" (see [context_sources.py](../context_sources.md)).
- `count_by(dimension, query=None)`: counts per value (top 15) over all lessons, or over the top `TOP_K_CANDIDATES` hits for a query. Used for "recurring issues".
- `dimensions()`: every context dimension and its known values, built from the loaded lessons.
- `sources()`: a short description of the context sources, for prompts.
- `version()`: the index version being searched; part of the answer-cache key.

## Configuration
| Setting | Default | Effect |
|---|---|---|
| `TOP_K_ANSWER` | 8 | Hits returned by `search` when `k` is not given |
| `TOP_K_CANDIDATES` | 20 | How many hits `count_by` looks at when a query is given |
| `FEATURE_AUTO_RESOLVE_CONTEXT` | true | Map loose context values to the data's own values inside `search` |
| `FEATURE_FEEDBACK_BOOST` | true | Build the feedback boost and pass it to the store search |
| `DATASET_CONFIG` | `config/dataset.yaml` | Mapping used when the index has no saved mapping |
| `STORAGE`, `INDEX_POLL_SECONDS` | local, 30 | Where the index lives and how often S3 is checked (see [index_files.py](../index_files.md)) |

Other search settings (`FEATURE_VECTOR_SEARCH`, `SCORE_W_*`...) act inside [memory.py](../search/memory.md).

## Dependencies
- **Used by:** [agents/\_\_init\_\_.py](__init__.md) (`retrieval_client`, `make_agent`), which hands it to the [answer agent](answer.md) and the [CLI](../cli.md).
- **Uses:** [search/memory.py](../search/memory.md), [index_files.py](../index_files.md), [feedback.py](../feedback.md), [context.py](../context.md), [context_sources.py](../context_sources.md), [dataset.py](../dataset.md), [agents/clients.py](clients.md) (`EmbeddingProxy`).

## Example
Call:
```python
retrieval.call("search", query="door software regression test",
               context={"stage": ["comissioning"]}, k=2)
```
Result (shortened, offline hash embedder, made-up data):
```json
{"context_used": {"stage": ["Commissioning"]},
 "context_mapped": ["stage=comissioning -> stage=Commissioning"],
 "context_unresolved": [], "related_to": {}, "unknown": [],
 "hits": [{"id": "1003", "title": "Door software change again not regression tested",
           "score": 1.1, "similarity": 0.477,
           "reasons": [["context_match", "stage", "Commissioning"]]}, "..."]}
```

## Known limitations and improvements
- `dimensions()` walks every lesson on every call, and `search` calls it when auto-resolve is on. Fine for a few thousand rows. Idea: compute it once per loaded version.
- `count_by(dimension, query)` counts over the top `TOP_K_CANDIDATES` hits. The memory search always returns that many lessons, even weak matches, so the counts can include unrelated lessons.
- `version`, `sources` and `dimensions` are separate calls per question; idea: one call.
- The store loads the whole index into memory. That fits the hundreds to few thousand rows expected.
