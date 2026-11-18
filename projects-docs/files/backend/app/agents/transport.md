# `backend/app/agents/transport.py`

> How agents talk to each other: the same `call(method, **kwargs)` works in the same process (`LocalClient`) or over HTTP (`HttpClient` plus `make_server`).

**Part of:** [Agents](../../../../flows/agents.md) · [Deployment](../../../../flows/deployment.md)  ·  **Layer:** Agent

## Purpose

The agents should be easy to split into separate services later without changing the code that uses them. So every agent call goes through a small client with one method, `call`. Arguments and results are plain JSON, so the same call works locally and remotely.

For example, the answer agent runs `retrieval.call("search", query="door software")`. It does not know if the retrieval agent is in the same process or on another container. See the [glossary](../../../../glossary.md) for "agent", "client" and "JSON".

## How it works

- An **agent** is any object with a `name` and a `methods` tuple, e.g. `name = "grader"`, `methods = ("info", "grade")`.
- `LocalClient.call` checks the method is listed, calls it, and then turns the result into JSON and back. That way anything that would not survive HTTP (e.g. a numpy array or a tuple) fails or changes in local runs too, not only in production.
- `HttpClient.call` sends `POST <base_url>/<method>` with the arguments as a JSON body and returns the JSON reply.
- `make_server` wraps an agent in a small threaded HTTP server: `GET /health` lists the agent's name and methods; `POST /<method>` runs the method through a `LocalClient`.

## Key components

- `AgentError`: raised for an unknown method, an HTTP error reply, or an unreachable service.
- `LocalClient(agent)`: `.call(method, **kwargs)`; `.name` is the agent's name.
- `HttpClient(name, base_url, timeout=300)`: `.call(method, **kwargs)`. HTTP errors become `AgentError("<name>.<method>: <code> <first 300 chars of the body>")`; connection errors and timeouts become `AgentError("... cannot reach <url> ...")`.
- `make_server(agent, host="127.0.0.1", port=8100)`: returns a `ThreadingHTTPServer`. Status codes: 200 OK, 404 for unknown paths or methods (`AgentError`), 500 for any other exception, with `{"error": "..."}`. Request logging is switched off.

## Configuration

None directly. The `AGENT_*_URL` settings in [`__init__.py`](__init__.md) decide whether a `LocalClient` or an `HttpClient` is used. The HTTP timeout (300 s) is fixed in the code.

## Dependencies

- **Used by:** [`__init__.py`](__init__.md) (all clients and `serve`); tests build clients directly.
- **Uses:** only the Python standard library (`json`, `urllib`, `http.server`).

## Example

```python
server = make_server(GraderAgent(settings), port=8100)   # in one process
# in another process:
HttpClient("grader", "http://127.0.0.1:8100").call("info")   # -> {"model": "..."}
HttpClient("grader", "http://127.0.0.1:8100").call("delete") # -> AgentError: grader.delete: 404 {"error": "grader has no method delete"}
```

`GET http://127.0.0.1:8100/health` -> `{"agent": "grader", "methods": ["info", "grade"]}`.

## Known limitations and improvements

- No authentication on the agent HTTP server. It binds to `127.0.0.1` by default; if it is bound to another address, anyone who can reach the port can call it. Idea: a shared token header, or keep agents on a private network.
- No retries in `HttpClient`; one failed call fails the caller (the answer agent catches tool and grader errors).
- Wrong argument names on a POST raise a `TypeError`, which comes back as 500, not as a clear 400.
- The whole JSON round-trip in `LocalClient` costs a little time for large results (e.g. embeddings).
