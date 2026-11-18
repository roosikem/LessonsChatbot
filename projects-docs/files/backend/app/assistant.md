# `backend/app/assistant.py`

> Loads `config/assistant.yaml`: the wording, example questions and word lists of this deployment, so they can change without a code change.

**Part of:** [Ask a question](../../../flows/ask-a-question.md) · [Admin upload](../../../flows/admin-upload.md)  ·  **Layer:** Config

## Purpose

The chatbot should work for another domain or data set by editing a file, not code. So the app name, the prompt intro, the clarifying and "no match" texts, the example questions in the chat page, the filler words for the vague-question check and the stopwords for keyword search all live in `config/assistant.yaml`. This small module reads that file once and prepares it for the code.

Example: `filler_words` contains "hi", "help", "lessons", "tell", ... so a first question "Any lessons for me?" is answered with the `clarify_question` text instead of a search.

## How it works

1. `load(path)` reads the YAML file and caches the result per path (`lru_cache`), so the file is read once per process.
2. It adds `hash`: the first 16 hex characters of the SHA-256 of the raw file. The [answer agent](agents/answer.md) puts this hash into the [answer cache](../../../glossary.md) key, so changing the wording never serves an old answer.
3. It turns the space-separated `filler_words` and `stopwords` strings into Python sets.
4. It sets empty defaults for `examples`, `personal_column_hints` and `keep_status_values`.
5. `public(cfg)` picks only what the browser needs.

## Key components

- `load(path)`: the parsed config dict with `hash`, `filler_words` (set), `stopwords` (set) and defaults.
- `for_settings(settings)`: `load(str(settings.assistant_config))`, with `app_name` taken from `APP_NAME` in `.env` when set (else the YAML value, else "Talk to Lessons Learned").
- `public(cfg)`: `app_name`, `tagline`, `placeholder`, `examples`, `keep_status_values`, `related_only_text`. Served to the UI through `/api/config`.

Keys used elsewhere (from `config/assistant.yaml`): `intro`, `situation`, `clarify_question`, `no_match_text`, `related_only_text`, `filtered_summary_text` (answer agent); `stopwords` (memory search); `personal_column_hints`, `keep_status_values` (upload page).

## Configuration

| Setting | Default | Effect |
|---|---|---|
| `ASSISTANT_CONFIG` | `backend/config/assistant.yaml` | Which wording file to load. |
| `APP_NAME` | none | The app's name in the UI and the API title; overrides `app_name` in the YAML. |

## Dependencies

- **Used by:** [`agents/answer.py`](agents/answer.md), [`api.py`](api.md), [`search/memory.py`](search/memory.md).
- **Uses:** `yaml`, `hashlib`; reads [`config/assistant.yaml`](../config/assistant.yaml.md).

## Example

```yaml
app_name: Talk to Lessons Learned
no_match_text: I couldn't find a lesson in the data that clearly matches this question.
filler_words: >-
  a an and any ... lessons learn learned ...
```

```python
cfg = assistant.for_settings(settings)
cfg["filler_words"]   # {"a", "an", "and", "any", ..., "lessons", ...}
cfg["hash"]           # e.g. "3f9c0a1b2d4e5f60" (changes when the file changes)
assistant.public(cfg) # {"app_name": "Talk to Lessons Learned", "tagline": ..., "examples": [...], ...}
```

## Known limitations and improvements

- The file is cached per path for the life of the process (`lru_cache`), so edits to `assistant.yaml` need a restart.
- No check that required keys exist; a missing `clarify_question` would give `None` / `KeyError` later. Not visible in the code where it would fail first. Idea: validate the keys at start.
- Word lists are single English lists; another language needs its own lists.
