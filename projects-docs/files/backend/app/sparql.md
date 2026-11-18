# `backend/app/sparql.py`

> A minimal SPARQL client: it sends SELECT and ASK queries over HTTP and returns plain Python rows.

**Part of:** [Load data](../../../flows/load-data.md)  ·  **Layer:** Search & data

## Purpose
The [SPARQL source agent](agents/sparql_source.md) must read lessons from a SPARQL endpoint (SPARQL is the query language for RDF knowledge graphs, see the [glossary](../../../glossary.md)). A full SPARQL library is not needed for two kinds of query, so this file does it with the Python standard library only. It also has `pivot`, which turns "one row per property" results into "one row per item", the shape the rest of the code expects.

## How it works
1. The client is built with an endpoint URL and optional auth: a token gives `Authorization: Bearer ...`; otherwise a user (and password) gives Basic auth.
2. Each query is sent as an HTTP POST form field `query=...`, asking for `application/sparql-results+json`.
3. `select` reads the variable names from `head.vars` and returns one dict per binding. A variable with no value becomes `""`.
4. `ask` returns the `boolean` field.
5. Errors become a `SparqlError`:
   - an HTTP error: the status code and the first 300 characters of the response, for example `401 from https://.../sparql: ...`;
   - an endpoint that cannot be reached (connection refused, DNS, TLS) or a timeout: `cannot reach <endpoint>: <reason>`.

## Key components
- `SparqlClient(endpoint, token=None, user=None, password=None, timeout=120)`.
- `SparqlClient.select(query)`: list of `{variable: value}` dicts (all values as text).
- `SparqlClient.ask(query="ASK { ?s ?p ?o }")`: true or false; the default query is used as a ping.
- `SparqlError`: raised on HTTP errors, unreachable endpoints and timeouts.
- `pivot(rows, subject="subject", key="key", value="value", sep=";")`: groups `(subject, key, value)` rows into one dict per subject. A key seen again with a new value is joined with `sep`; a repeated identical value is not added twice.

## Configuration
None directly. The [SPARQL source agent](agents/sparql_source.md) passes `SPARQL_ENDPOINT`, `SPARQL_TOKEN`, `SPARQL_USER`, `SPARQL_PASSWORD`.

## Dependencies
- **Used by:** [agents/sparql_source.py](agents/sparql_source.md).
- **Uses:** Python standard library only (`urllib`, `json`, `base64`).

## Example
`pivot` with made-up project triples:
```python
rows = [{"subject": "P002", "key": "project_name", "value": "Valoria Metro Line 5"},
        {"subject": "P002", "key": "special_features", "value": "Driverless"},
        {"subject": "P002", "key": "special_features", "value": "reuse of Line 4 design"}]
pivot(rows)
# [{"project_name": "Valoria Metro Line 5",
#   "special_features": "Driverless;reuse of Line 4 design"}]
```

## Known limitations and improvements
- A reply that is not valid JSON (for example an HTML login page with status 200) raises `SparqlError("... did not return SPARQL JSON ...")`, like HTTP errors and unreachable endpoints.
- The subject itself is not added to the pivoted row; the item id must come from a property (for example `project_id`).
- `pivot` checks for duplicates by splitting on `sep`, so a value that itself contains `;` can be added twice.
- All values come back as text; typed literals (numbers, dates) lose their type. That matches the CSV path, which is also text.
