# `backend/app/agents/__init__.py`

> The wiring: the only place that builds agents, either in the same process or as an HTTP client to an agent running elsewhere.

**Part of:** [Agents](../../../../flows/agents.md) · [Ask a question](../../../../flows/ask-a-question.md) · [Load data](../../../../flows/load-data.md) · [Deployment](../../../../flows/deployment.md)  ·  **Layer:** Agent

## Purpose

The project is split into agents (embedding, retrieval, graph, SPARQL source, grader, ingest, answer). Today they usually run in one process, but each can also run as its own service. This file hides that choice: callers ask for "the retrieval client" and get either a `LocalClient` (same process) or an `HttpClient` (another service), depending on whether a URL is set in `.env`.

Code outside `app/agents/` must use only these functions, never the agent modules directly. See the [glossary](../../../../glossary.md) for "agent" and "client".

## How it works

Each `*_client` function follows the same pattern:

1. If the feature is off, return `None` (graph, SPARQL source, grader).
2. If the agent's URL is set (`AGENT_*_URL`), return an `HttpClient` to it.
3. Otherwise import the agent class and wrap it in a `LocalClient`.

Special case: with `SEARCH_STORE=neo4j`, the graph agent also answers the retrieval calls, so `retrieval_client` returns the graph client.

## Key components

- `embedding_client(settings)`: client for the embedding agent.
- `embedder(settings, embedding=None)`: an `EmbeddingProxy` (from [`clients.py`](clients.md)) that looks like a normal embedder (`.embed()`, `.model_id`) but goes through the embedding agent. Used e.g. for `build_index`.
- `graph_client(settings, embedding=None)`: `None` if `FEATURE_NEO4J` is off; else client for the graph agent.
- `retrieval_client(settings, embedding=None)`: graph client with `SEARCH_STORE=neo4j`; else client for the retrieval agent.
- `sparql_client(settings)`: `None` unless `DATA_SOURCE=sparql`.
- `grader_client(settings)`: `None` unless `FEATURE_EVIDENCE_GRADING` is on.
- `make_ingest_agent(settings)`: an `IngestAgent` (plain object, not wrapped) with embedding, graph and SPARQL source clients.
- `make_answer_agent(settings, retrieval=None, graph=None, llm=None)`: an `AnswerAgent` (plain object, not wrapped). If no retrieval client is passed, it builds embedding, retrieval and graph clients itself. Uses `make_llm(settings)` unless an `llm` is passed (tests and eval pass fakes).
- `SERVABLE`: the agents that can run as their own service: `embedding`, `retrieval`, `graph`, `sparql`, `grader`. The answer and ingest agents are not in this list.
- `make_agent(name, settings)`: the bare agent object by name; raises `ValueError` for other names.
- `serve(name, settings, host="127.0.0.1", port=8100)`: an HTTP server for one agent (call `.serve_forever()`), via [`transport.py`](transport.md).

## Configuration

| Setting | Default | Effect |
|---|---|---|
| `AGENT_EMBEDDING_URL` | empty | Set: embedding over HTTP. |
| `AGENT_RETRIEVAL_URL` | empty | Set: retrieval over HTTP (ignored with `SEARCH_STORE=neo4j`). |
| `AGENT_GRAPH_URL` | empty | Set: graph over HTTP. |
| `AGENT_SPARQL_URL` | empty | Set: SPARQL source over HTTP. |
| `AGENT_GRADER_URL` | empty | Set: grader over HTTP. |
| `SEARCH_STORE` | memory | `neo4j`: the graph agent does retrieval. |
| `FEATURE_NEO4J` | false | Off: no graph client. |
| `DATA_SOURCE` | file | `sparql`: build the SPARQL source client. |
| `FEATURE_EVIDENCE_GRADING` | false | Off: no grader client. |

## Dependencies

- **Used by:** [`api.py`](../api.md), [`cli.py`](../cli.md) (including `cli serve <agent>`), [`evaluation.py`](../evaluation.md).
- **Uses:** [`transport.py`](transport.md), [`clients.py`](clients.md), and the agent modules [`embedding.py`](embedding.md), [`retrieval.py`](retrieval.md), [`graph.py`](graph.md), [`sparql_source.py`](sparql_source.md), [`grader.py`](grader.md), [`ingest.py`](ingest.md), [`answer.py`](answer.md); [`llm.py`](../llm.md) (`make_llm`).

## Example

`.env` with `AGENT_GRADER_URL=http://grader:8100` and `FEATURE_EVIDENCE_GRADING=true`:

```python
grader_client(settings)   # -> HttpClient("grader", "http://grader:8100")
```

Same `.env` without the URL: `LocalClient(GraderAgent(settings))`. With `FEATURE_EVIDENCE_GRADING=false`: `None`, and the answer agent skips grading.

Run the grader as its own service: `python -m app.cli serve grader` (from `.env.example`).

## Known limitations and improvements

- Imports are inside the functions, so a missing optional dependency (e.g. the Neo4j driver) only fails when that agent is built.
- Each call to a `*_client` function builds a new agent object; callers that need one shared instance (like [`api.py`](../api.md)) keep it themselves.
- The answer agent cannot be served over HTTP from here (not in `SERVABLE`); it always runs in the API process.
