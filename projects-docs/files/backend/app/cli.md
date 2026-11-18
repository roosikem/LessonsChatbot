# `backend/app/cli.py`

> The terminal tool: load data, search, ask, build the graph, run the eval, measure speed and start one agent as a service.

**Part of:** [Load data](../../../flows/load-data.md) · [Ask a question](../../../flows/ask-a-question.md) · Evaluation · [Agents](../../../flows/agents.md)  ·  **Layer:** Tooling

## Purpose
Developers need to do everything without the browser: build the first index, check what search returns for "door faults", or ask a question and see every tool step. This file gives one command, `python -m app.cli`, with sub-commands for each job. It reads the same `.env` as the web server, so what you see here is what the chat page does.

## How it works
1. `main()` reads the arguments with Python's `argparse` and loads the settings once.
2. It calls the matching `cmd_*` function.
3. Each function gets its agent from the wiring in [agents/__init__.py](agents/__init__.md) and prints a short text result.

Run all commands from `backend/` (the paths in `.env` such as `DATA_DIR=./data` are relative to the current folder).

## Key components

### Commands (copy-paste examples)
All examples assume `cd backend` first.

- **`ingest [--dry-run]`**: loads the data set from `DATASET_CONFIG` (or SPARQL source), builds a new [index version](../../../glossary.md), and rebuilds the Neo4j graph if `FEATURE_NEO4J=true`. `--dry-run` only reads and checks the rows, nothing is written.
  ```bash
  .venv/bin/python -m app.cli ingest --dry-run
  .venv/bin/python -m app.cli ingest
  ```
  Prints rows, loaded, skipped (with reasons such as "filtered out by Status", "missing id" or "duplicate id"), lesson values that point to unknown projects, the new version and the graph result.

- **`search QUERY [-c dim=value]... [-r source=name]... [-k N]`**: searches the current index directly, no language model. `-c` adds a context value, `-r` names a context-source item (for example a project) to boost comparable lessons; `-r` also prints the comparable items first. `-k` is the number of hits (default 5).
  ```bash
  .venv/bin/python -m app.cli search "door faults" -r project="Valoria Metro Line 5" -c stage=Commissioning
  ```
  Prints `score [id] title`, up to four context values, and the "why" reasons per hit.

- **`ask QUESTION [--trace] [--json]`**: the full chatbot answer in the terminal. `--trace` also prints the tool calls and the result of the code checks. `--json` prints the raw result.
  ```bash
  .venv/bin/python -m app.cli ask "I am responsible for the door system. Which lessons learned should I consider?" --trace
  ```
  Prints a clarifying question if there is one, the summary, and per lesson: `[id] title (confidence)`, the learning, the reasons and the quote.

- **`graph build | stats | related ID`**: works on the Neo4j graph. Stops with "FEATURE_NEO4J is off" if the flag is off.
  ```bash
  .venv/bin/python -m app.cli graph build
  .venv/bin/python -m app.cli graph stats
  .venv/bin/python -m app.cli graph related 1003
  ```
  `related` prints the weight, id and title of each related lesson and why it is related. Without an id it stops with "usage: graph related <lesson id>".

- **`eval retrieval|answers [--store memory|neo4j|both] [-k N] [--ids q01,q05] [--limit N]`**: scores search or full answers against your own question set (`EVAL_QUESTIONS` / `EVAL_DATASET`). See [evaluation.py](evaluation.md). `--store both` only works for `retrieval` (`eval answers --store both` stops with "eval answers runs on one store: --store memory or --store neo4j"); `--ids` and `--limit` only for `answers`. In the retrieval summary, a group with no labelled questions prints "no labelled questions" instead of numbers.
  ```bash
  .venv/bin/python -m app.cli eval retrieval --store both
  .venv/bin/python -m app.cli eval answers --store memory --ids q01,q05,q24
  ```
  Prints a summary line per store/variant (retrieval) or a PASS/FAIL line per question (answers), then the path of the saved report.

- **`bench QUESTION [-n N]`**: asks the same question N times (default 5, allowed 1 to 50) with the answer cache switched off, and prints the median total time and the median seconds and tokens per step.
  ```bash
  .venv/bin/python -m app.cli bench "Which lessons exist for HVAC?" -n 3
  ```

- **`serve AGENT [--host H] [--port P]`**: runs one agent as its own small HTTP service. `AGENT` is one of `embedding`, `retrieval`, `graph`, `sparql`, `grader`. Defaults: `127.0.0.1:8100`. The main app then reaches it by setting the matching `AGENT_*_URL`.
  ```bash
  .venv/bin/python -m app.cli serve grader --port 8105
  # in the app's .env: AGENT_GRADER_URL=http://127.0.0.1:8105
  ```

### Functions
- `main(argv=None)`: builds the parser, loads settings, runs the command.
- `parse_context(pairs)`: turns `["stage=Commissioning", "topic=Doors"]` into `{"stage": ["Commissioning"], "topic": ["Doors"]}`. A repeated dimension collects several values.
- `cmd_ingest`, `cmd_search`, `cmd_ask`, `cmd_graph`, `cmd_eval`, `cmd_bench`, `cmd_serve`: one per command, as above.

## Configuration
The CLI has no settings of its own. It uses all of [settings.py](settings.md). The ones that matter most:
- `DATASET_CONFIG`, `DATA_SOURCE` for `ingest`.
- `SEARCH_STORE`, `FEATURE_NEO4J` for `search`, `graph`, `ask`.
- `LLM_PROVIDER`, `LLM_MODEL_ID`, `FEATURE_EVIDENCE_GRADING` for `ask`, `bench`, `eval answers`.
- `bench` forces `FEATURE_ANSWER_CACHE=false` for its own run.

Any setting can be changed for one run with an environment variable, for example `LLM_MODEL_ID=gemma4:12b .venv/bin/python -m app.cli ask "..."`.

## Dependencies
- **Used by:** developers in the terminal; the [README](../../../README.md) and the [deployment flow](../../../flows/deployment.md) use `python -m app.cli ingest` for the first data load.
- **Uses:** [agents/__init__.py](agents/__init__.md) (`make_ingest_agent`, `retrieval_client`, `graph_client`, `make_answer_agent`, `serve`, `SERVABLE`), [evaluation.py](evaluation.md), [settings.py](settings.md).

## Example
```bash
.venv/bin/python -m app.cli ingest
```
Output on the made-up data with `config/dataset.yaml` (counts checked by loading the file; the version name is set at run time):
```
source: file  rows: 30, loaded: 27, skipped: 3
  skipped 1026: filtered out by Status
  skipped 1027: empty lesson text
  skipped 1030: filtered out by Status
index <version>: 27 lessons; 10 project
```
With `FEATURE_NEO4J=true` a `graph: {...}` line follows.

## Known limitations and improvements
- `search -r` keeps only the first value per source (`values[0]`) if the same source is given twice.
- Idea: a `--version` / `status` command that prints the live index version and the settings in use.
