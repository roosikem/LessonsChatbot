# `backend/app/cache.py`

> A small in-memory answer cache with a time limit and a size limit, so a repeated question gets the stored answer in well under a second.

**Part of:** [Ask a question](../../../flows/ask-a-question.md) · [Feedback](../../../flows/feedback.md)  ·  **Layer:** Storage

## Purpose

A new answer needs several model calls (about 3 s per new question). Many users ask the same thing, e.g. the example question "I am starting commissioning on Valoria Metro Line 5...". The [answer agent](agents/answer.md) keeps finished answers here and serves them again when the same question comes in on the same data and settings.

A thumbs-down removes the answer it was given on, so a disliked answer is not served again. See the [glossary](../../../glossary.md) for "cache", "TTL" and "LRU".

## How it works

1. Entries live in an ordered dict: key -> (time stored, result). A lock makes it safe for several threads.
2. `get(key)`: if the entry is older than the TTL (time to live), it is removed and `None` is returned. Otherwise it is moved to the end (most recently used) and a deep copy is returned, so callers cannot change the stored answer.
3. `put(key, result)`: if the key is already stored, the old entry and its answer ID are dropped first (so `forget(old_id)` can never remove the newer answer). Then it stores a deep copy, remembers `result["id"] -> key`, and removes the oldest-used entries while there are more than `max_entries` (least recently used, LRU).
4. `forget(answer_id)`: finds the key for that answer ID and removes it.

The key is built by the answer agent with `make_key(...)`: a SHA-256 of the normalised question, the history, the index version, the relevant settings and the hash of `assistant.yaml`. Because the index version is part of the key, a new data version never gets old answers.

Each process (e.g. each Fargate task) has its own cache; the short TTL keeps them roughly in step.

## Key components

- `AnswerCache(ttl_seconds=900, max_entries=500)`: `.get(key)`, `.put(key, result)`, `.forget(answer_id)` (returns True if something was removed).
- `make_key(*parts)`: SHA-256 hex of the parts as sorted JSON (non-JSON values via `str`).
- `normalize_question(text)`: lowercase, single spaces, trailing `?`, `!`, `.` and spaces removed.

## Configuration

Read by the answer agent and passed in:

| Setting | Default | Effect |
|---|---|---|
| `FEATURE_ANSWER_CACHE` | true | Off: no cache is created. The eval and `cli bench` switch it off. |
| `ANSWER_CACHE_TTL_SECONDS` | 900 | Max age of a cached answer. |
| `ANSWER_CACHE_SIZE` | 500 | Max number of cached answers per process. |

## Dependencies

- **Used by:** [`agents/answer.py`](agents/answer.md) (`ask`, `forget`); `forget` is triggered from [`api.py`](api.md) on a thumbs-down.
- **Uses:** only the Python standard library.

## Example

```python
normalize_question("Door software keeps failing on site?")   # "door software keeps failing on site"
cache = AnswerCache(ttl_seconds=900, max_entries=500)
cache.put(key, {"id": "a1b2c3d4e5f6", "answer": {...}})
cache.get(key)               # a copy of the stored result
cache.forget("a1b2c3d4e5f6") # True; the next ask builds a fresh answer
```

## Known limitations and improvements

- Per process only, not shared between containers; idea: a shared cache (DynamoDB with TTL).
- Exact match only: "door software keeps failing" and "door software fails again" are different keys. A semantic cache was considered risky ("Project A" vs "Project B"); not built.
- The key does not include feedback votes, so an answer can lag new votes by up to the TTL (documented in [answer.py](agents/answer.md)).
