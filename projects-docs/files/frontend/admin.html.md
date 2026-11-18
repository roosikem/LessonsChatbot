# `frontend/admin.html`

> The admin page skeleton: token box, current-index info, upload form, column-mapping table and result box.

**Part of:** [Admin upload](../../flows/admin-upload.md) · [Load data](../../flows/load-data.md)  ·  **Layer:** UI

## Purpose
The lessons list changes. An admin needs to upload a new extract (CSV or Excel), say what each column means, and rebuild the search index without touching code. Example: a new file has a "Supplier" column; on this page the admin gives it the role "context" and it becomes a new filter dimension. This file holds the HTML; [`admin.js`](admin.js.md) does the work.

## How it works
1. The API serves it at `/admin` ([`api.py`](../backend/app/api.md)).
2. The admin types the admin token in the header. `admin.js` then loads "Current index".
3. Step 1 "Upload": pick a `.csv`, `.xlsx` or `.xlsm` file, optional sheet name and header row (default 1), click "Upload & preview".
4. Step 2 "Map the columns" (hidden until an upload): a table with one row per column and a "Build index" button.
5. Step 3 "Result" (hidden until a build starts): the outcome.

## Key components
- Header: `#token` (password field, "Admin token"), link "Open chat" to `/`.
- `#current`: `#current-info` (version, lesson count, context sources, embedding model) and `#current-dims` (chips of the dimensions).
- `#upload-form`: `#file`, `#sheet`, `#header-row`, submit button; `#upload-error`.
- `#mapping-card`: `#profile-info`, a help text explaining roles (`context`, `ranking`, personal data defaults to `ignore`, title optional), `table#mapping` with columns Column, Filled, Distinct, Examples, Role, Dimension, Split by; `#filters` (checkboxes for filter columns); `#mapping-error`; `#ingest-btn` "Build index".
- `#result-card` with `#result`.

## Configuration
- `FEATURE_UPLOAD_UI` (default false): when false, every `/api/admin/*` call returns 404, so the page loads but cannot do anything.
- `DATA_SOURCE=sparql`: every `/api/admin/*` call returns 409 "uploads are off while DATA_SOURCE=sparql" (lessons then come from SPARQL source, so an uploaded file would be ignored). The page shows that message instead of the current index.
- `ADMIN_TOKEN`: the value to type in the token box. The settings refuse to start with the upload UI on and no token.
- `UPLOAD_MAX_MB` (default 20), `UPLOAD_MAX_ROWS` (default 20000): server limits for the upload.

## Dependencies
- **Used by:** [`backend/app/api.py`](../backend/app/api.md) serves it at `/admin`.
- **Uses:** [`style.css`](style.css.md), [`admin.css`](admin.css.md), [`admin.js`](admin.js.md).

## Example
The admin uploads `sample-data/made-up/overall_list_v2.xlsx` with sheet "Overall List" and header row 3. The table shows 32 rows; "Supplier" is suggested as `context` with dimension `supplier`; "Contact person" is suggested as `ignore`.

## Known limitations and improvements
- The page is reachable without the token; only the API calls are protected. That is fine because it contains no data, but it shows the admin UI exists.
- The header-row input uses an inline `style` (`width:4em`) instead of a class in [`admin.css`](admin.css.md). Small inconsistency.
