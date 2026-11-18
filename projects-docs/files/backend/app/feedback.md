# `backend/app/feedback.py`

> Stores thumbs up/down votes (file or S3) and turns votes on similar earlier questions into a small score boost per lesson.

**Part of:** [Feedback](../../../flows/feedback.md) · [Ask a question](../../../flows/ask-a-question.md) · [Storage and versions](../../../flows/storage-and-versions.md)  ·  **Layer:** Search & data

## Purpose
Users mark lessons as helpful or not. The search should learn a little from that: if three people liked lesson 1013 for "door faults on driverless metros", it should rank a bit higher for similar questions, but not for "HVAC sizing", and a few votes must never take over the ranking. A thumbs-down lowers a lesson but never removes it. The *feedback boost* is explained in the [glossary](../../../glossary.md).

## How it works
**Storing** (`FeedbackStore.write`): each vote gets a UTC time stamp and is stored as one JSON line in `data/feedback.jsonl`, or with `FEEDBACK_STORE=s3` as one S3 object `feedback/<YYYY-MM-DD>/<HHMMSS>-<8 digits of the nanosecond clock>.json`, for example `feedback/2026-01-31/101500-12345678.json` (S3 cannot append, and several containers would overwrite one file). When the vote names a lesson and `FEATURE_FEEDBACK_BOOST` is on, the API ([api.py](api.md)) adds the question's embedding (`question_vector`) and the embedding model id to the vote before writing it, so search never has to embed old votes. If that embedding fails, the vote is still stored and search embeds the question later.

**Reading** (`FeedbackStore.votes`): the file is re-read only when it changed. S3 votes are loaded in a background thread at most every `INDEX_POLL_SECONDS`, and only keys after the last one seen, so a search never waits for S3.

**Scoring** (`FeedbackBoost.scores(query_vector)`):
1. Keep only the latest vote per voter, lesson and question (so clicking ten times counts once).
2. For each vote, compute the cosine similarity between its question and the current question.
3. Skip it if the similarity is below `FEEDBACK_MIN_SIMILARITY` (0.6).
4. Add `+1` (up) or `-1` (down) x similarity x age decay, where decay = `0.5 ** (age_days / FEEDBACK_HALF_LIFE_DAYS)`.
5. Per lesson, squash the total with `tanh`, so it stays between -1 and 1.

Search then adds `SCORE_W_FEEDBACK x score` (at most +-0.1 by default) and, when ups are more than downs, the reason `["feedback", ups, downs]`, which the chat page shows as "helpful for similar questions" ([app.js](../../frontend/app.js.md)).

## Key components
- `FeedbackStore(settings, index_store=None)`: `write(row)` returns the stored row; `votes()` returns all votes so far.
- `FeedbackBoost(store, embedder, settings)`: `scores(query_vector, today=None)` returns `{lesson_id: (score -1..1, ups, downs)}`. A vote without a stored vector (or from another embedding model) is embedded once and kept in memory.
- `feedback_reason(ups, downs)`: `["feedback", ups, downs]` when `ups > downs`, else `None`.
- `latest_per_voter(votes)`: one vote per (voter or "anonymous", lesson, normalized question).

## Configuration
| Setting | Default | Effect |
|---|---|---|
| `FEATURE_FEEDBACK` | true | Feedback buttons and endpoint (used in the API) |
| `FEATURE_FEEDBACK_BOOST` | true | Search uses `FeedbackBoost` |
| `FEEDBACK_STORE` | file | `file` or `s3` (needs `STORAGE=s3`) |
| `SCORE_W_FEEDBACK` | 0.1 | Weight of the -1..1 score in the search score |
| `FEEDBACK_MIN_SIMILARITY` | 0.6 | A vote counts only for questions at least this similar |
| `FEEDBACK_HALF_LIFE_DAYS` | 180 | Votes lose half their weight every 180 days |
| `INDEX_POLL_SECONDS` | 30 | How often S3 votes are refreshed |
| `USER_HEADER` | none | Header with the signed-in user, used as the voter id (set in the API) |
| `DATA_DIR` | `backend/data` | Location of `feedback.jsonl` |

## Dependencies
- **Used by:** [api.py](api.md) (`FeedbackStore.write` for `/api/feedback`), [agents/retrieval.py](agents/retrieval.md) and [agents/graph.py](agents/graph.md) (`FeedbackBoost`), [search/memory.py](search/memory.md) (`feedback_reason`).
- **Uses:** [index_files.py](index_files.md) (the shared `S3Remote`), numpy.

## Example
Votes on lesson 1013, current question "door faults on a driverless metro":

| Voter | Vote | Question similarity | Age | Contribution |
|---|---|---|---|---|
| a | up | 0.9 | 0 days | +0.90 |
| b | up | 0.8 | 180 days | +0.8 x 0.5 = +0.40 |
| c | down | 0.5 | 0 days | skipped (below 0.6) |

Total 1.30, `tanh(1.30) = 0.86`, so the search score rises by `0.1 x 0.86 = 0.086`, and the card shows the reason (2 up, 0 down). Votes counted here are only those that passed the similarity check, so voter c's thumbs-down is not counted at all.

## Known limitations and improvements
- The API and the search agents keep separate `FeedbackStore` objects; with S3, a vote reaches search only after the poll interval (also stated in the file's docstring).
- The first S3 read happens in the background, so the first searches after a restart see no votes.
- With S3 every vote is one object, and all are kept in memory; idea: DynamoDB or Aurora for votes in production.
- The answer cache does not include votes. A thumbs-down removes that one answer from the cache (in [api.py](api.md)), but other cached answers do not see new votes until they expire (`ANSWER_CACHE_TTL_SECONDS`, default 900 s = 15 minutes).
- Without SSO the voter id comes from the browser, so one person can vote again from another browser. `USER_HEADER` fixes this once SSO is in place.
- The 0.6 similarity threshold is not verified on production data.
