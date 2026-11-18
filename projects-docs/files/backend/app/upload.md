# `backend/app/upload.py`

> Looks at an uploaded lessons file, guesses what each column is for, and turns the admin's choices into a dataset mapping.

**Part of:** [Admin upload](../../../flows/admin-upload.md) · [Load data](../../../flows/load-data.md)  ·  **Layer:** Search & data

## Purpose
The lessons-learned data may arrive as a new CSV or Excel extract with other or extra columns. Nobody should have to edit YAML for that. This file profiles the file (how full is each column, how many different values, numbers or dates, which separator), suggests a [role](../../../glossary.md) per column, and builds the same kind of [mapping](../config/dataset.yaml.md) as `config/dataset.yaml`. Example: the made-up `overall_list_v2.csv` has a new `Supplier` column; the suggestion makes it a `context` column with dimension `supplier`, and after ingest the chat can filter by supplier.

## How it works
1. **Profile** (`profile`): read the rows (CSV encoding and delimiter are detected; Excel sheet and header row can be chosen). For every column count filled/empty/distinct values, average length, whether all values are numbers or dates (`YYYY-MM-DD...`), the most likely multi-value separator (`;`, `|` or new line), the top 5 values, and the full value list when there are 50 or fewer.
2. **Suggest** (`suggest`): pick a role per column with simple rules, in this order:
   1. Column name already in the current mapping: keep its role (marked `known`).
   2. Name contains a personal-data hint from `assistant.yaml` (for example "contact", "rated by"): `ignore`.
   3. Every row has a different, short value: `id`.
   4. All dates, or a number with at most 20 different values: `ranking` (weight 0 until someone sets one).
   5. Average length over 80 characters: `text`.
   6. At least half of the values name items of a context source (for example project names from `projects.csv`): `context`, linked to that source's lesson column.
   7. Few different values (at most 20, or at most half of the filled rows): `context`.
   8. Anything else: `ignore`.
3. **Build mapping** (`build_mapping`): check the admin's choices, then write a full mapping. The `context_sources` block is copied from the current mapping, so links to projects keep working.

```mermaid
flowchart LR
    F[Uploaded file] --> P[profile]
    P --> S[suggest roles]
    S --> A[Admin edits roles and filters]
    A --> B[build_mapping]
    B --> I[Ingest job]
```

## Key components
- `ROLES`: the allowed roles: `id`, `title`, `text`, `context`, `ranking`, `filter`, `ignore`.
- `profile(path, sheet=None, header_row=1, sample=5)`: in: file path. Out: `{rows, columns: [stats per column], sample: first 5 rows, csv: {encoding, delimiter}}`.
- `suggest(profile_result, current_mapping=None, personal_hints=())`: out: one `{column, role, dimension, separator, known}` per column.
- `build_mapping(base, file_path, roles, filters=None, sheet=None, header_row=1, csv_options=None, profile_result=None)`: in: the current mapping and the admin's `[{column, role, dimension?, separator?}]`. Out: a new mapping dict. Raises `ValueError` listing every problem: unknown role, no `id` or `text` column, more than one `id` or `title`, two ranking or two context columns with the same name.
- `ranking_config(rows, base, profile_result)`: known ranking columns keep their settings (kind, max, weight). New ones become `kind: date` with `half_life_days: 1095`, or `kind: number` with `max` from the profile, both with `weight: 0`.
- `known_roles(mapping)`: column name -> (role, dimension) from an existing mapping. This is the only place where the mapping's `ignore` list is read.
- `keys_by_source(mapping)`, `linked_source(stats, source_keys)`: find which context source a column's values point to.
- `dimension_name(column)`: "Product group" -> `product_group_plan`.

## Configuration
No `.env` settings are read here.
- `personal_column_hints` in [assistant.yaml](../config/assistant.yaml.md): column names that look like personal data; passed in by [api.py](api.md).
- `keep_status_values` in `assistant.yaml`: which filter values the admin page ticks by default (used in the browser, not here).
- `UPLOAD_MAX_MB`, `UPLOAD_MAX_ROWS`: checked in [api.py](api.md), not here.

## Dependencies
- **Used by:** [api.py](api.md) (`/api/admin/uploads` and `/api/admin/uploads/{id}/ingest`).
- **Uses:** [dataset.py](dataset.md) (`detect_csv`, `read_rows`, `context_sources`, `load_context_sources`).

## Example
Admin's choices for the made-up v2 file (shortened):
```json
[{"column": "ID", "role": "id"},
 {"column": "Title", "role": "title"},
 {"column": "Lesson", "role": "text"},
 {"column": "Topic", "role": "context", "dimension": "topic", "separator": ";"},
 {"column": "Supplier", "role": "context", "dimension": "supplier"},
 {"column": "User rating", "role": "ranking", "dimension": "user_rating"},
 {"column": "Status", "role": "filter"},
 {"column": "Contact person", "role": "ignore"}]
```
with filters `{"Status": ["Approved"]}` become:
```yaml
lessons:
  file: <path of the upload>
  id: ID
  title: Title
  text: [Lesson]
  context: {topic: Topic, supplier: Supplier}
  ranking: {user_rating: {column: User rating, kind: number, max: 5, weight: 0}}
  filter: {Status: [Approved]}
  multi_value: {Topic: ";"}
  ignore: [Contact person]
  encoding: utf-8-sig
  delimiter: ","
context_sources: <copied from the current mapping>
```
(`user_rating` keeps its settings because it is a known ranking column.)

## Known limitations and improvements
- The rules are simple thresholds (20 distinct values, 80 characters). A column like a long free-text "Root cause" with short entries could be suggested as `context`. The admin must check the suggestion.
- Separator detection needs the separator in at least 2 values and in 1 of 20 filled values; a rare second value can be missed.
- `build_mapping` replaces the whole `lessons` block. Uploads only make sense with file data: with `DATA_SOURCE=sparql` the [api.py](api.md) admin routes refuse uploads with 409, because ingest would read the lessons from SPARQL source anyway.
- Idea: let the admin preview the first lessons as the chatbot would see them before starting the ingest.
