# `backend/app/agents/sparql_source.py`

> A read-only source agent that fetches lessons and context rows from a knowledge graph (any SPARQL endpoint) instead of CSV files.

**Part of:** [Load data](../../../../flows/load-data.md) · [Agents](../../../../flows/agents.md)  ·  **Layer:** Agent

## Purpose
The lessons-learned data may live in a knowledge graph that is queried with SPARQL (a query language for RDF graphs, see the [glossary](../../../../glossary.md)). The rest of the pipeline expects simple rows like a CSV file gives. This agent runs the SPARQL queries written in the mapping and returns rows of the same shape, so the ingest step does not care where the data came from. Pointing at another graph means editing YAML (`config/dataset.sparql.yaml`), not code.

## How it works
1. On start it loads the dataset mapping and makes a [SparqlClient](../sparql.md) with the endpoint and either a token or a user and password.
2. `fetch("lessons")` reads `lessons.sparql` from the mapping; `fetch("project")` reads `context_sources.project.sparql`.
3. It runs the query and gets one dict per result row (variable name to value).
4. If the source has `shape: key_value`, the rows are `(subject, key, value)` triples and are turned into one row per subject with [`pivot`](../sparql.md).
5. An unknown table, or a table without a `sparql` entry, raises `ValueError` ("no SPARQL query configured for table ...; check the SPARQL source mapping"), so a config mistake is not hidden as "0 rows".
6. If the endpoint cannot be reached or times out, [sparql.py](../sparql.md) raises `SparqlError("cannot reach <endpoint>: ...")`.

## Key components
- `SparqlSourceAgent(settings, client=None)`: builds the agent; tests can pass their own client.
- `info()`: the endpoint and the table names it can fetch (`lessons` plus every context source).
- `ping()`: `{"ok": true}` if a trivial `ASK` query succeeds.
- `fetch(table)`: `{"table": table, "rows": [...]}`; `ValueError` for an unknown table or a missing query.

## Configuration
| Setting | Default | Effect |
|---|---|---|
| `DATA_SOURCE` | file | `sparql` makes ingest read from this agent; settings then switch the mapping to `dataset.sparql.yaml` when `DATASET_CONFIG` is the default |
| `FEATURE_SPARQL_SOURCE` | false | Must be true with `DATA_SOURCE=sparql` |
| `SPARQL_ENDPOINT` | none | SPARQL endpoint URL (required) |
| `SPARQL_TOKEN` | none | Bearer token; used first if set |
| `SPARQL_USER`, `SPARQL_PASSWORD` | none | Basic auth, used when no token is set |
| `AGENT_SPARQL_URL` | empty | Call the agent over HTTP instead of in-process |

Mapping keys per table: `sparql` (the query), `shape: key_value` (pivot), `join` (separator for repeated keys, default `;`).

## Dependencies
- **Used by:** [agents/\_\_init\_\_.py](__init__.md) (`sparql_client`, `make_agent`), which passes it to the [ingest agent](ingest.md) as `source_client`.
- **Uses:** [sparql.py](../sparql.md), [dataset.py](../dataset.md) (`load_mapping`).

## Example
With the local SPARQL stand-in loaded from the made-up CSVs (converted from the CSVs to RDF):
```python
agent.fetch("lessons")["rows"][0]
# {"id": "1001", "title": "Door controller firmware updated without regression test",
#  "learning": "A late firmware update ...", "status": "Approved",
#  "projects": "Valoria Metro Line 4", ...}
```

## Known limitations and improvements
- The `ll:` vocabulary in the shipped mapping is a stand-in. The queries must be rewritten for the target graph's ontology.
- No paging: one query returns all rows. Fine for thousands of lessons; idea: `LIMIT/OFFSET` paging for large graphs.
