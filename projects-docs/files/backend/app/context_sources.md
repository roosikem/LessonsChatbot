# `backend/app/context_sources.py`

> Holds the extra tables linked to lessons (projects, suppliers...) and answers "which item is this?", "which items are comparable?" and "how close is this lesson to the target item?".

**Part of:** [Ask a question](../../../flows/ask-a-question.md) · [Load data](../../../flows/load-data.md)  ·  **Layer:** Search & data

## Purpose
Questions like "we start Valoria Metro Line 5, what should we know?" need more than text search. Line 5 has few lessons, but Valoria Metro Line 4 is very similar (same platform, vehicle type, GoA level, customer). A *context source* (see the [glossary](../../../glossary.md)) is any table linked to lessons through a lesson column, for example `projects.csv` through `Projects`. This file finds items, scores how *comparable* two items are, and gives search a boost with a reason such as "same project" or "comparable project: Valoria Metro Line 4".

## How it works
1. `Sources(items, mapping)` groups the `ContextItem`s by source, and indexes them by the key lessons use (`match_on: name` or `id`).
2. `find` looks an item up by exact id or name (case-insensitive). If there is none, it accepts a part of a name, but only when that part fits exactly one item: "Line 5" finds "Valoria Metro Line 5", while "Valoria Metro" fits Line 4 and Line 5 and gives `None` (no guess). `candidates` lists the items whose name contains the text.
3. `similarity(a, b, weights)` compares two items over the weighted `compare` attributes:
   - an attribute missing on either side is skipped;
   - an attribute negative on both sides ("false", "no", "0", "n") is skipped, because both lacking a feature is not a real match;
   - otherwise its weight counts in the total, and in the score if the values are equal;
   - result = score / total, 0..1, plus the matched attributes.
4. `boost(lesson_context, targets)` for each target item: 1.0 if the lesson links to the same item; otherwise the best `similarity` of the items it links to. The average over targets is returned with reasons.
5. `comparable` ranks all other items of a source by `similarity`.

## Key components
- `Sources(items, mapping)`: the container. `names()`, `lesson_column(source)`, `weights(source)`.
- `find(source, name_or_id)`: one `ContextItem` or `None` (also `None` when a partial name fits several items).
- `candidates(source, name_or_id)`: all items of the source whose name contains the text (case-insensitive); empty text gives `[]`.
- `resolve(related_to)`: `{source: name or id}` to `{source: item}`; unknown sources or names are left out.
- `linked_items(lesson_context, source)`: the items a lesson points to.
- `boost(lesson_context, targets)`: `(0..1, reasons)`; reasons are `("same_item", source, name)` or `("comparable_item", source, name, matched_attrs)`.
- `comparable(source, target, limit=5)`: `[(item, score, matched)]`, best first, score above 0.
- `describe()`: short summary per source for prompts.
- `similarity(a, b, weights)`: `(0..1, matches)`.
- `comparable_result(sources, source, name, limit=5)`: the `comparable_items` tool answer, shared by the memory and graph agents. It returns one of:
  - `{"source", "item", "attributes", "comparable": [{name, score, shared}]}` when the item is found;
  - `{"error": "Valoria Metro fits several project items; ask which one", "candidates": [...]}` (up to 20) when a partial name fits several items, so the model asks the user instead of guessing;
  - `{"error": "no project called ...", "known": [...]}` (up to 50 names) when nothing fits;
  - `{"error": "unknown context source ...", "sources": [...]}` for an unknown source.
- `NEGATIVE`: `{"false", "no", "0", "n"}`.

## Configuration
- `SCORE_W_RELATED` (default 0.15): how much the `boost` value adds to a search score (applied in [memory.py](search/memory.md) and [graph.py](agents/graph.md)).
- Mapping keys per source under `context_sources`: `lesson_column` (without it the source is reference-only), `match_on` (`name` or `id`), `compare` (attribute to weight), `references` (column to another source).

## Dependencies
- **Used by:** [search/memory.py](search/memory.md), [agents/retrieval.py](agents/retrieval.md), [agents/graph.py](agents/graph.md).
- **Uses:** nothing from the project (works on `ContextItem` from [dataset.py](dataset.md)).

## Example
Compare weights from [dataset.yaml](../config/dataset.yaml.md): platform 3, vehicle_type 3, goa_level 2, customer 2, operator 1, is_new_design 1, complexity 1, country 1, multi_supplier 1, international 1 (total 16).

Valoria Metro Line 5 vs Valoria Metro Line 4:
- `multi_supplier` and `international` are false on both: skipped, total becomes 14.
- `is_new_design` is false vs true: counts in the total but does not match.
- The other 7 attributes match: 3 + 3 + 2 + 2 + 1 + 1 + 1 = 13.
- similarity = 13 / 14 = 0.93.

(Recomputed offline: `similarity` gives 0.9286.) `comparable_result(sources, "project", "Line 5")` lists Line 4 (0.93), Valoria Airport Shuttle (0.5), Lisvale Metro Refurbishment (0.43), then two at 0.06.

A lesson linked to Line 4, searched with `related_to={"project": "Valoria Metro Line 5"}`, gets `0.15 x 0.93 = 0.14` extra and the reason "comparable project: Valoria Metro Line 4". A lesson linked to Line 5 itself gets `0.15 x 1.0` and "same project".

## Known limitations and improvements
- `resolve(related_to)` leaves out an ambiguous or unknown name, so a search with `related_to={"project": "Valoria Metro"}` gets no related-item boost. The search result then lists the source under `unknown` and, via `not_found(related_to, targets)`, the candidate names under `related_candidates` (e.g. Line 4 and Line 5), which the answer agent passes to the model as `related_not_found` so it can ask which one.
- The partial match only looks at names, not ids.
- Only equal values match; "GoA4" vs "GoA3" scores the same as "GoA4" vs "GoA1". Idea: ordered or numeric attributes.
- The graph agent scores comparability differently (no negatives stored, unweighted share in `related_lessons`); see [graph.py](agents/graph.md).
