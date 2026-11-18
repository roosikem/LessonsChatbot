# `backend/app/dataset.py`

> Reads the lessons and context files (CSV, Excel or rows from SPARQL) using the dataset mapping, and turns them into `Lesson` and `ContextItem` records plus a load report.

**Part of:** [Load data](../../../flows/load-data.md) · [Admin upload](../../../flows/admin-upload.md)  ·  **Layer:** Search & data

## Purpose
The code does not assume a database schema. It only knows *roles* (id, title, text, context, ranking, filter); the column names live in the mapping (`config/dataset.yaml`, see [dataset.yaml](../config/dataset.yaml.md)). This file applies that mapping. For example, the column "Project stage" becomes the context dimension `stage`, and "Projects" with value "Valoria Metro Line 4; Valoria Metro Line 5" becomes two `project` values.

## How it works
1. `load_mapping` reads the YAML mapping.
2. `read_rows` reads a file: Excel through `openpyxl`, otherwise text. Text is decoded as UTF-8 (BOM removed) or, if that fails, as cp1252 (what Excel on Windows writes). The delimiter is taken from the mapping or guessed from the header line (`,` `;` tab `|`).
3. `load_lessons` walks the rows. A row is skipped, with a reason, in this order: no id ("missing id"); a filter column has a value not in the allowed list ("filtered out by <column>", for example "filtered out by Status" when it is not `Approved`); the id was seen before ("duplicate id"); the text is empty ("empty lesson text").
4. For each kept row it builds the text (joined text columns), the context (multi-value columns split by their separator and sorted), the title (or a short title from the text) and the ranking signal values.
5. `load_context_sources` reads each context source (for example `projects.csv`) into `ContextItem`s.
6. `load_all` does both and records lesson values that point to no known item (`unknown_links`).

## Key components
- `Lesson(id, title, text, context, signals)`: one lesson. `embed_text()` gives "title, text, then `dim: values; ...`", the text that is embedded and keyword-searched.
- `ContextItem(source, id, name, attrs, text)`: one row of a context source. `key(match_on)` returns the id or the name.
- `LoadReport`: `rows`, `loaded`, `skipped` (id, reason), `unknown_links`; `summary()` prints it.
- `load_mapping(path)`: YAML to dict.
- `read_rows(path, delimiter, sheet, header_row, encoding)`: list of `{column: text}` dicts. Paths are relative to the repo root; absolute paths (uploads) stay as they are.
- `read_excel(path, sheet, header_row)` and `cell_text(value)`: every cell as text; `1001.0` becomes `"1001"`, dates become ISO text.
- `detect_csv(path)`: encoding and delimiter, so the upload page can save them in the mapping.
- `sniff_delimiter(header)`: the most frequent of `, ; \t |`, default `,`.
- `split_values(value, sep)`: split and trim; empty parts dropped.
- `short_title(text, limit=80)`: the first sentence of the text, cut at a word, for data without a title.
- `load_lessons(mapping, report=None, rows=None)`, `load_context_sources(mapping, fetch=None)`, `load_all(mapping, fetch=None)`: as above. `fetch(table)` replaces file reading (used for SPARQL source).

## Configuration
No .env settings. Mapping keys under `lessons`: `file`, `delimiter`, `encoding`, `sheet`, `header_row` (default 1), `id`, `title` (optional), `text` (list), `context` (dimension to column), `multi_value` (column to separator), `filter` (column to allowed values), `ranking` (see [ranking.py](ranking.md)). Under each `context_sources.<name>`: `file`, `id`, `name`, `text`, `lesson_column`, `match_on`, plus the keys used by [context_sources.py](context_sources.md).

## Dependencies
- **Used by:** [agents/ingest.py](agents/ingest.md), [agents/retrieval.py](agents/retrieval.md), [agents/graph.py](agents/graph.md), [agents/sparql_source.py](agents/sparql_source.md), [search/memory.py](search/memory.md), [upload.py](upload.md), [api.py](api.md), [evaluation.py](evaluation.md), [agents/answer.py](agents/answer.md) (`short_title`).
- **Uses:** [ranking.py](ranking.md), `yaml`, `openpyxl` (only for Excel).

## Example
Row from `sample-data/made-up/overall_list.csv`:
```
ID=1003, Title=Door software change again not regression tested, Departments=Quality,
Project stage=Commissioning, Projects=Valoria Airport Shuttle,
Impact (0-5)=5, Status=Approved, ...
```
becomes
```python
Lesson(id="1003", title="Door software change again not regression tested",
       text="A hotfix to the door control software was deployed on site without the regression suite ...",
       context={"department": ["Quality"], "product_group": ["Metro"], "process": ["Software release"],
                "topic": ["Doors"], "location": ["Aldmoor-North"], "stage": ["Commissioning"],
                "project": ["Valoria Airport Shuttle"]},
       signals={"impact": 5.0, "user_rating": 4.8, "recency": "2023-09-01"})
```
On the whole file (checked offline with `load_all`): 30 rows, 27 loaded, 1026 and 1030 "filtered out by Status", 1027 "empty lesson text", 10 context items.

## Known limitations and improvements
- When several filter columns fail, only the first one is named in the reason.
- A row with no id is reported as `data row N` (N counts data rows after the header), not as a spreadsheet line number.
- The `ignore` list in the mapping is not read here; ignored columns are simply never used (the upload page uses `ignore`).
- Idea: report rows whose filter column is empty separately from rows with a wrong status, so admins can fix data.
