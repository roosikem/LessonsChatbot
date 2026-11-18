# `backend/app/search/fusion.py`

> Merges the keyword ranking and the vector ranking into one score per lesson, using reciprocal rank fusion (RRF).

**Part of:** [Ask a question](../../../../flows/ask-a-question.md)  ·  **Layer:** Search & data

## Purpose
Search runs two kinds of search at once (*hybrid search*, see the [glossary](../../../../glossary.md)):
- **keyword search** (BM25 in memory, Lucene in Neo4j) finds lessons that use the same words, such as "regression";
- **vector search** (cosine similarity of embeddings) finds lessons with the same meaning in other words.

Their scores are on different scales (BM25 can be 9.4, cosine 0.48), so they cannot simply be added. RRF ignores the raw numbers and only uses each lesson's *rank* in each list. Both the [memory store](memory.md) and the [graph agent](../agents/graph.md) use this file, so they merge results the same way.

## How it works
For each list of scores:
1. Sort the lessons by score, best first, and give each a rank: 0, 1, 2, ...
2. A lesson gets `1 / (k + rank + 1)` from that list, with `k = 60`.
3. A lesson whose score is 0 in that list gets nothing from it. (Without this, lessons with no keyword match at all would still get points in file order. This was a real bug, fixed in review; it raised recall@5 for the memory store with hybrid search and context from 0.939 to 0.983.)

Then add the parts from all lists and divide by the largest total, so the best lesson has exactly 1.0.

`fuse` chooses the lists from the flags: the vector list when `FEATURE_VECTOR_SEARCH` is on (or when keyword search is off, so there is always at least one list), the keyword list when `FEATURE_KEYWORD_SEARCH` is on.

## Key components
- `rrf(*score_lists, k=60)`: one numpy array of fused scores, 0..1, same order as the input.
- `fuse(vec_scores, kw_scores, settings)`: picks the lists from the flags and calls `rrf`.

## Configuration
| Setting | Default | Effect |
|---|---|---|
| `FEATURE_VECTOR_SEARCH` | true | Include the vector ranking |
| `FEATURE_KEYWORD_SEARCH` | true | Include the keyword ranking |

`k = 60` is fixed in the code.

## Dependencies
- **Used by:** [search/memory.py](memory.md), [agents/graph.py](../agents/graph.md).
- **Uses:** numpy.

## Example
Four lessons, made-up scores for the question "door software regression test":

| Lesson | Vector score | Vector rank | Keyword score | Keyword rank |
|---|---|---|---|---|
| 1007 HVAC capacity | 0.9 | 0 | 0 | (no match) |
| 1003 Door software change | 0.1 | 2 | 8.0 | 0 |
| 1001 Door controller firmware | 0.5 | 1 | 3.0 | 1 |
| 1002 Door obstruction winter | 0.0 | (no match) | 0 | (no match) |

RRF parts (k = 60):
- 1007: `1/61 = 0.016393` + 0 = **0.016393**
- 1003: `1/63 = 0.015873` + `1/61 = 0.016393` = **0.032266**
- 1001: `1/62 = 0.016129` + `1/62 = 0.016129` = **0.032258**
- 1002: 0 + 0 = **0**

Divide by the largest (0.032266):

| Lesson | Fused |
|---|---|
| 1003 | 1.000 |
| 1001 | 0.9997 |
| 1007 | 0.508 |
| 1002 | 0 |

So a lesson that is good in both lists beats one that is best in only one list. Running `rrf(np.array([0.9, 0.1, 0.5, 0.0]), np.array([0.0, 8.0, 3.0, 0.0]))` gives `[0.508, 1.0, 0.9997, 0.0]`.

## Known limitations and improvements
- Only ranks count: a lesson far ahead in one list gets about the same lift as one just ahead. That is by design for RRF.
- After scaling, the gap between rank 1 and rank 2 is tiny (1.0 vs 0.9997 above), so the small boosts in [memory.py](memory.md) (0.05 per context match, up to 0.15 for related items) often decide the final order. Worth knowing when tuning weights.
- Ties in a list keep input order (`stable` sort).
- In the memory store, a negative cosine counts as "no match" (score not above 0) in the vector list.
- Idea: tune `k` or weight the two lists with the retrieval eval (evaluation flow).
