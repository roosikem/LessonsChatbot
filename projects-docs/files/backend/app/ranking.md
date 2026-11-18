# `backend/app/ranking.py`

> Turns data columns such as impact rating or created date into small, weighted score bonuses for search, as declared in the mapping.

**Part of:** [Ask a question](../../../flows/ask-a-question.md) · [Load data](../../../flows/load-data.md)  ·  **Layer:** Search & data

## Purpose
Two lessons can match a question equally well, but one has impact 5 and the other impact 2. A *ranking signal* (see the [glossary](../../../glossary.md)) lets the higher-impact one come first, without hard-coding column names. Any number of signals can be declared in the mapping; a weight of 0 keeps the value for display but does not change the ranking.

## How it works
1. `config(mapping)` reads `lessons.ranking` from the mapping. Each signal gets a `column`, a `kind` (`number` by default) and a `weight` (0 by default). A plain string is taken as a number column.
2. At load time `read(row, signals)` stores the raw value of each signal on the lesson: a float for numbers, the first 10 characters (an ISO date) for dates, `None` when missing or not a number.
3. At search time `score(values, signals)` adds up `weight x normalized value`:
   - number: `value / max`, clipped to 0..1 (`max` defaults to 1);
   - date: `0.5 ** (age_in_days / half_life_days)`, so a lesson exactly one half-life old counts half (`half_life_days` defaults to 365);
   - missing or bad value: 0.

## Key components
- `config(mapping)`: `{signal_name: spec}` with defaults filled in.
- `read(row, signals)`: `{signal_name: raw value or None}` for one data row.
- `normalized(name, value, spec, today=None)`: one signal as 0..1.
- `score(values, signals, today=None)`: the weighted sum; 0 when no signal is configured.

## Configuration
No .env settings. Mapping, under `lessons.ranking`, for example in [dataset.yaml](../config/dataset.yaml.md):
```yaml
ranking:
  impact: {column: Impact (0-5), kind: number, max: 5, weight: 0.05}
  user_rating: {column: User rating, kind: number, max: 5, weight: 0}
  recency: {column: Created, kind: date, half_life_days: 1095, weight: 0}
```
Only `impact` changes the ranking in the shipped mapping.

## Dependencies
- **Used by:** [dataset.py](dataset.md) (`config`, `read` at load time), [search/memory.py](search/memory.md) and [agents/graph.py](agents/graph.md) (`config`, `score` at search time).
- **Uses:** nothing from the project.

## Example
Lesson 1003 has impact 5 and lesson 1002 has impact 4. With the mapping above:
- 1003: `0.05 x 5/5 = 0.05`
- 1002: `0.05 x 4/5 = 0.04`

If `recency` had weight 0.02, a lesson created 1095 days ago would add `0.02 x 0.5 = 0.01`.

## Known limitations and improvements
- `normalized` takes a `name` argument it does not use.
- Numbers below 0 or above `max` are clipped; there is no other scaling (for example log scale).
- Dates in other formats than ISO (`YYYY-MM-DD...`) score 0. Excel dates are converted to ISO in [dataset.py](dataset.md); CSV dates must already be ISO.
- Idea: tune the weights with the retrieval eval (evaluation flow) instead of fixed values.
