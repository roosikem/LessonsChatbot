# `backend/app/context.py`

> Small helpers that clean context filters and map a user's loose words (with typos) to the exact context values in the data.

**Part of:** [Ask a question](../../../flows/ask-a-question.md)  ·  **Layer:** Search & data

## Purpose
A *context* is a filter-like hint such as `{"stage": ["Commissioning"]}` (see the [glossary](../../../glossary.md)). It comes from the model or the user and is often messy: "comissioning" with a typo, a single string instead of a list, or a dimension name the data doesn't have ("phase" instead of "stage"). Search only boosts exact values, so these helpers fix the input first, without guessing when the match is unclear.

## How it works
1. `normalize` turns any input into `{dimension: [values]}`, drops empty values and non-dict input.
2. `match_score(term, value)` scores how well a word fits a data value, 0..1:
   - exact (case-insensitive): 1.0;
   - every word of the term starts a word of the value, and the term has 4+ letters: 0.85;
   - same first 3 letters and string similarity at least 0.85: that similarity (a typo);
   - otherwise 0.
3. `resolve` scores a term against every known value and returns the best 5.
4. `align` maps a whole context. It only changes a value when the match is clear, and never guesses:
   - known dimension (the data has it, for example `project`): the value is replaced only by a *clear* match in that dimension. Clear means exactly one exact match, or exactly one match at all, or (with no exact match) a top score strictly higher than the second. Otherwise, if there were candidates, the value is kept as typed and reported as *unresolved* with its `candidates`, so the model can ask or choose. Example: project "line" fits "Valoria Metro Line 4" and "Valoria Metro Line 5" equally (0.85 each), so it stays "line" and both are listed.
   - unknown dimension (for example "phase" or "client"): the value moves to another dimension only if there is exactly one exact match or exactly one match at all; with several candidates it is kept as typed and reported as *unresolved*.
   - no match at all: the value is kept as typed and not reported.
5. `matches` returns the `(dimension, value)` pairs a lesson really has, for the context boost and its "why relevant" reason.

## Key components
- `normalize(context)`: clean `{dim: [values]}`.
- `matches(lesson_context, wanted)`: list of `(dim, value)` the lesson has. Case-insensitive, exact values.
- `match_score(term, value)`: 0..1 as above.
- `resolve(term, dimensions, dimension=None, limit=5)`: `{"term", "matches": [{dimension, value, score}]}`.
- `align(context, dimensions)`: `(context, changes, unresolved)`; `changes` are strings like `"stage=comissioning -> stage=Commissioning"`; each `unresolved` entry is `{term, dimension, candidates}`, with candidates as `"dimension=value"` strings.

## Configuration
- `FEATURE_AUTO_RESOLVE_CONTEXT` (default true): the search agents call `align` inside `search`.
- `FEATURE_CONTEXT_BOOST` (default true) and `SCORE_W_CONTEXT` (0.05): how much each `matches` pair adds to a score (applied in [memory.py](search/memory.md) and [graph.py](agents/graph.md)).

## Dependencies
- **Used by:** [agents/retrieval.py](agents/retrieval.md), [agents/graph.py](agents/graph.md), [search/memory.py](search/memory.md), [agents/answer.py](agents/answer.md) (`normalize` when cleaning tool arguments, `matches` in the answer checks). `align` and `resolve` are called by the retrieval and graph agents.
- **Uses:** Python standard library only (`difflib`, `re`).

## Example
With the made-up data's dimensions:
```python
match_score("comissioning", "Commissioning")   # about 0.96 (typo)
match_score("Decommissioning", "Commissioning") # 0 (first letters differ)
align({"phase": ["comissioning"]}, dims)
# ({"stage": ["Commissioning"]}, ["phase=comissioning -> stage=Commissioning"], [])
align({"project": ["Line 5"]}, dims)
# ({"project": ["Valoria Metro Line 5"]}, ["project=Line 5 -> project=Valoria Metro Line 5"], [])
align({"project": ["line"]}, dims)
# ({"project": ["line"]}, [],
#  [{"term": "line", "dimension": "project",
#    "candidates": ["project=Valoria Metro Line 4", "project=Valoria Metro Line 5"]}])
align({"client": ["Valoria"]}, dims)
# kept as {"client": ["Valoria"]}; unresolved, candidates: Valoria Airport Shuttle, Valoria Metro Line 4, Valoria Metro Line 5
```
(Recomputed offline with the dimensions of `sample-data/made-up/overall_list.csv`.)

## Known limitations and improvements
- A clear match can still be a weak one: in a known dimension a single 0.85 word-start match is taken (for example "Line 5" for "Valoria Metro Line 5"). That is the intended behaviour, but a typed value that happens to start one word of one value will be mapped to it.
- An unresolved value is kept as typed, so it gives no context boost until the model or the user picks one of the candidates.
- No synonyms: "hotfix" will not map to "Software release". Idea: a small synonym list in `config/assistant.yaml`, or lesson enrichment tags (future plan).
- `matches` needs exact values, so a context value that was not aligned gives no boost.
