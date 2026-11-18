# `backend/config/dataset.sparql.yaml`

> The same dataset mapping as `dataset.yaml`, but the rows come from SPARQL queries against a knowledge graph instead of CSV files.

**Part of:** [Load data](../../../flows/load-data.md) · [Agents](../../../flows/agents.md)  ·  **Layer:** Config

## Purpose
The lessons-learned data may live in a knowledge graph that answers [SPARQL](../../../glossary.md) queries (SPARQL is the query language for RDF graphs, like SQL for tables). This file keeps the queries in YAML, so pointing at another graph means rewriting two queries, not code. The local stand-in is an Apache Jena Fuseki server loaded with the made-up data (converted from the CSVs to RDF; vocabulary prefix `ll:`).

## How it works
1. With `DATA_SOURCE=sparql` and `DATASET_CONFIG` left at its default, [settings.py](../app/settings.md) switches to this file.
2. The [SPARQL source agent](../app/agents/sparql_source.md) runs `lessons.sparql`. Each result row is a dict of SPARQL variable names -> values.
3. The roles below (`id`, `text`, `context`...) then work exactly as in [dataset.yaml](dataset.yaml.md), with the **SPARQL variable names** in place of CSV column names.
4. For the `project` source, the query returns one `(subject, key, value)` triple per property. `shape: key_value` tells the agent to pivot these into one row per project (`pivot` in `app/sparql.py`); repeated keys are joined with `;`.

## Key components

### `lessons`
- `sparql`: one row per lesson. Single-valued fields use `SAMPLE(...)`, multi-valued ones (stage, departments, topics, projects) use `GROUP_CONCAT(DISTINCT ...; separator=";")`. Everything except the id is `OPTIONAL`, so a lesson with a missing field is still returned. Projects are reached through the link `ll:affects/ll:project_name`.
- `id: id`, `title: title`, `text: [learning]`: variable names from the query.
- `context`: the same seven dimensions as `dataset.yaml` (`department`, `product_group`, `process`, `topic`, `location`, `stage`, `project`), mapped to the variables `departments`, `product_group`, `process`, `topics`, `location`, `stage`, `projects`.
- `ranking`: `impact` (weight 0.05), `user_rating` (0), `recency` from `created` (0); same meaning as in `dataset.yaml`.
- `filter: {status: [Approved]}`: only approved lessons.
- `multi_value`: `stage`, `departments`, `topics`, `projects` split on `;` (matching the `GROUP_CONCAT` separator).
- No `ignore` list; personal fields are simply not selected by the query.

### `context_sources.project`
- `shape: key_value`: pivot `(subject, key, value)` rows into one row per project. The key is the part of the property URI after `#` (for example `ll:project_name` -> `project_name`). An optional `join` key (not set here) changes the `;` used for repeated keys.
- `sparql`: every literal property of every `ll:Project`.
- `id: project_id`, `name: project_name`, `lesson_column: project`, `match_on: name`, `text: [description, special_features]`, `compare: {...}`: same as in `dataset.yaml`.

## Configuration
- `DATA_SOURCE=sparql`: use this source (and, with the default `DATASET_CONFIG`, this file).
- `FEATURE_SPARQL_SOURCE=true` and `SPARQL_ENDPOINT`: required, else start-up stops.
- `SPARQL_TOKEN` or `SPARQL_USER` / `SPARQL_PASSWORD`: authentication.
- `AGENT_SPARQL_URL`: run the SPARQL source agent as its own service.

## Dependencies
- **Used by:** [agents/sparql_source.py](../app/agents/sparql_source.md) (runs the queries), [agents/ingest.py](../app/agents/ingest.md) and [dataset.py](../app/dataset.md) (apply the roles to the rows).
- **Uses:** a SPARQL endpoint (Fuseki locally, SPARQL source on the platform).

## Example
Lesson 1001 in the stand-in graph has two departments. The query returns one row:
```
id=1001  title="Door controller firmware updated without regression test"
departments="Engineering;Quality"  projects="Valoria Metro Line 4"  status="Approved"  ...
```
`multi_value: {departments: ";"}` splits it into `department: [Engineering, Quality]`, just as the CSV path does with `Departments: "Engineering; Quality"`.

## Known limitations and improvements
- The `ll:` vocabulary is our own stand-in. The target graph has its own ontology; both queries must be rewritten against it (keep the variable names, then nothing else changes).
- No `supplier` or `platform` sources and no `references` here, unlike the evaluation mapping.
- `SAMPLE(...)` picks any one value if the graph holds several titles or statuses for one lesson; that would go unnoticed.
- Admin uploads are switched off in this mode: the upload routes in [api.py](../app/api.md) return 409 "uploads are off while DATA_SOURCE=sparql".
- A source block without `sparql` makes `fetch` raise `ValueError` ("no SPARQL query configured for table ..."), so a missing query shows up as a clear error at ingest.
