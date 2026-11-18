# Made-up sample data

Invented data for local development and testing. All projects, customers, places, people and lessons are made up.
The column layout matches what the default mapping (`backend/config/dataset.yaml`) expects; the value formats below
are assumptions and can all be changed in the mapping.

| File | Rows | Content |
|---|---|---|
| `overall_list.csv` | 30 lessons | the lessons-learned list |
| `projects.csv` | 10 projects | project attributes (platform, vehicle type, automation level, customer, ...) |
| `suppliers.csv` | suppliers | supplier attributes, linked from the v2 lessons file |
| `platforms.csv` | platforms | platform attributes, referenced by projects |
| `overall_list_v2.csv` / `.xlsx` | 32 lessons | the lessons plus a `Supplier` column, for trying the admin upload |

## Value formats
- Multi-valued cells (`Departments`, `Topic`, `Projects`) use `; ` as separator.
- `Projects` contains `project_name` values from `projects.csv`. `Main project` = one main project name.
- `ID` = plain number.
- `Impact (0-5)` = integer 0-5; `User rating` = average as a decimal, may be empty.
- `Status` = `Approved` | `Draft` | `Rejected`; only `Approved` is searchable.
- `Contact person` / `Rated by` = placeholders ("Contact 01", "Reviewer 01"), treated as personal data and ignored.
- Language: English. There is no component column; components appear in the title, topic and lesson text.

## Example questions the data supports
- **Project:** Valoria Metro Line 5 (driverless, Urbano platform) is comparable to Line 4 and the Airport Shuttle
  (same platform, GoA4, same customer and operator).
- **Component:** doors (1001, 1002, 1003, 1004, 1025), bogie/wheels (1005, 1006), brakes (1009, 1024), HVAC, TCMS, pantograph.
- **Problem:** "software changes break things on site" finds 1001, 1003, 1025, 1013 (same meaning, different wording).
- **Recurring issue:** door software without regression testing (1001, 1003, 1025).
- **By stage:** lessons per `Project stage` (Tender ... Warranty).
- **Data cleaning:** 1026 = Draft (filtered out), 1027 = empty lesson text (skipped and reported), 1030 = Rejected
  duplicate of 1001 (filtered out).
- **Lessons for several projects:** 1011, 1016.
- **Nothing in the data:** e.g. "battery trains" or "cybersecurity" (the bot should say so).

## Upload example
- `overall_list_v2.csv`: the 30 lessons + a new **Supplier** column + 2 new lessons (1031, 1032) = 32 rows, 18 columns.
- `overall_list_v2.xlsx`: the same data as Excel, sheet "Overall List", with a title row on top so the **header is on
  row 3**; IDs stored as numbers.

Upload v2 on the admin page and map `Supplier` as context: the chat can then use `supplier` as a new dimension, with
no code change.
