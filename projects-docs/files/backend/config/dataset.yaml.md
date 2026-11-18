# `backend/config/dataset.yaml`

> The dataset mapping: tells the code which column of the lessons file plays which role, and which extra tables (projects) are linked to it.

**Part of:** [Load data](../../../flows/load-data.md) · [Ask a question](../../../flows/ask-a-question.md) · [Admin upload](../../../flows/admin-upload.md)  ·  **Layer:** Config

## Purpose
The code does not assume a database schema; names are kept in config. It only knows [roles](../../../glossary.md) (id, title, text, context, ranking, filter). The column names, such as `Lesson` or `Project stage`, live only here. When a data file uses other names, you change this file (or use the admin upload page, which writes a new mapping), not the code.

## How it works
1. `DATASET_CONFIG` points to this file (default). `ingest` reads it with `load_mapping`.
2. [dataset.py](../app/dataset.md) reads the lessons file row by row and applies the roles. Rows are checked in this order and skipped with a reason: no id ("missing id"), a value not allowed by a filter ("filtered out by <column>"), a duplicate id ("duplicate id"), no text ("empty lesson text").
3. Each `context_sources` block loads one extra table and links its rows to the lessons through one context dimension.
4. The mapping is saved with each [index version](../../../glossary.md). After an upload, the live version's mapping wins over this file (`active_mapping()` in [api.py](../app/api.md)).

Paths in this file are relative to the repo root.

## Key components

### `lessons` (the main table)
- `file`: the lessons file. Here `sample-data/made-up/overall_list.csv`. CSV, `.xlsx` or `.xlsm`.
- `delimiter`: CSV separator. Here `","`. If left out, it is guessed from the header line.
- Optional, not used here: `encoding` (else UTF-8, then cp1252), `sheet` (Excel sheet, else the first), `header_row` (else 1). The upload page writes these.
- `id`: column with the unique lesson id. Here `ID` (for example `1003`).
- `title`: column with the title. Here `Title` ("Door software change again not regression tested"). Optional; without it the first sentence of the text is used (cut at 80 characters).
- `text`: list of columns joined into the lesson text that is searched and quoted. Here only `Lesson`.
- `context`: `dimension name: column`. Each [dimension](../../../glossary.md) is a way to narrow or boost results (stage, topic...). Its values are also added to the text that is embedded. The dimension names are what the model and the API use:
  - `department: Departments`
  - `product_group: Product group`
  - `process: Process`
  - `topic: Topic`
  - `location: Location`
  - `stage: Project stage`
  - `project: Projects`
- `ranking`: any number of named signals from the data that can lift a lesson's score. Each has:
  - `column`: where the value is.
  - `kind`: `number` (scaled by `max` to 0..1) or `date` (newer is higher; the value halves every `half_life_days`).
  - `max`: top of a number scale.
  - `half_life_days`: for dates. Here 1095 days (3 years).
  - `weight`: how much it adds to the score. `0` = kept and shown but does not change the ranking.
  - Here: `impact` (`Impact (0-5)`, weight 0.05), `user_rating` (weight 0), `recency` (Created, weight 0).
  - A plain string (`impact: Rating`) is accepted as a number signal with weight 0.
- `filter`: `column: [allowed values]`. A row whose value is not in the list is skipped with the reason "filtered out by Status" (the column name). Here only `Status: [Approved]` rows load. Filtered lessons never reach the index.
- `multi_value`: `column: separator` for cells that hold several values. Here `Departments`, `Topic` and `Projects` are split on `;`, so "Engineering; Quality" becomes two departments.
- `ignore`: columns to leave out on purpose (here personal data such as `Contact person`, `Rated by`, and `Main project`). The loader only reads columns named in the other keys, so unnamed columns are never used anyway; `ignore` is read by the upload page so a later upload of the same file suggests "ignore" again.

### `context_sources` (linked tables)
Any number of blocks, or none. Each block name is the source name (here `project`).
- `file`: the table. Here `sample-data/made-up/projects.csv` (10 made-up projects).
- `id`: id column (`project_id`, for example `P002`).
- `name`: display name column (`project_name`, for example "Valoria Metro Line 5").
- `lesson_column`: the lesson **dimension** (not the CSV column) whose values name these items. Here `project`, which is `Projects`. A source without `lesson_column` is reference-only.
- `match_on`: what the lesson values contain: `name` or `id`. Here `name`, so a lesson with "Valoria Metro Line 4" links to project P001. Values with no matching item are listed at ingest as "lessons point to unknown project".
- `text`: item columns joined into the item's description (`description`, `special_features`).
- `compare`: `attribute: weight` used to find **comparable** items. Two projects are compared on the listed attributes; the score is the weighted share of attributes with the same value. Empty values are skipped, and two "false/no/0" values do not count as a match. Here `platform` and `vehicle_type` weigh 3, `goa_level` and `customer` 2, the rest 1. So Valoria Metro Line 5 and Line 4 (same platform Urbano, vehicle type Metro, GoA4, customer) score high. Leave `compare` out for a plain reference list.
- `references` (commented out here): `column: other source`, for hierarchies, for example a project's `platform` column pointing to a `platform` source. Used by the Neo4j graph (`REFERS_TO` links).

## Configuration
- `DATASET_CONFIG` (default this file): which mapping to load.
- `DATA_SOURCE=sparql` switches the default to [dataset.sparql.yaml](dataset.sparql.yaml.md).
- `FEATURE_CONTEXT_BOOST`, `SCORE_W_CONTEXT`: how much a matching context value helps.
- `SCORE_W_RELATED`: how much a lesson linked to the same or a comparable project helps.

## Dependencies
- **Used by:** [dataset.py](../app/dataset.md) (loading), [ranking.py](../app/ranking.md) (`ranking`), [context_sources.py](../app/context_sources.md) (`context_sources`, `compare`), [agents/graph.py](../app/agents/graph.md) (`references`), [upload.py](../app/upload.md) (known roles), [api.py](../app/api.md) (fallback mapping), [agents/ingest.py](../app/agents/ingest.md).
- **Uses:** the files in `sample-data/made-up/`.

## Example
```yaml
lessons:
  context:
    stage: Project stage
  filter:
    Status: [Approved]
  multi_value:
    Projects: ";"
```
Row 1003 has `Project stage = Commissioning`, `Status = Approved`, `Projects = Valoria Airport Shuttle`. It loads, gets `stage: [Commissioning]` and `project: [Valoria Airport Shuttle]`, and is linked to that project's row in `projects.csv`. A search with `-c stage=Commissioning` gives it the context boost and a "why relevant" reason for the stage match.

With this file, the made-up data loads 27 of 30 rows: 1026 and 1030 are "filtered out by Status", 1027 has an "empty lesson text".

## Known limitations and improvements
- The file is not checked against a schema. A typo in a key (for example `multi-value`) is silently ignored. Idea: validate the mapping at ingest and list unknown keys.
- A `filter` compares the exact text (after trimming); "approved" in lower case would be filtered out.
- `match_on: name` needs exact names; "Valoria Metro Line 5 " with other spelling shows up only as an "unknown" link at ingest.
