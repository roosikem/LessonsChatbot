# `backend/config/assistant.yaml`

> The chatbot's wording and word lists: app name, prompt intro, fixed reply texts, example questions, and the word lists for vague questions, keyword search and the upload page.

**Part of:** [Ask a question](../../../flows/ask-a-question.md) · [Admin upload](../../../flows/admin-upload.md)  ·  **Layer:** Config

## Purpose
The same code should work for another domain or data set (for example a different company's lessons) without code changes. Everything a person would want to re-word lives here. Dimension names and project names are never written here; they always come from the data.

## How it works
1. [assistant.py](../app/assistant.md) loads the file once (cached) from `ASSISTANT_CONFIG`.
2. It turns `filler_words` and `stopwords` from one long string into sets of words.
3. It adds a short hash of the file content. This hash is part of the [answer cache](../../../glossary.md) key, so changing the wording means old cached answers are not reused.
4. Only some keys go to the browser (`assistant.public`): `app_name`, `tagline`, `placeholder`, `examples`, `keep_status_values`, `related_only_text`. The rest stays on the server.

## Key components
| Key | Used by | What it does |
|---|---|---|
| `app_name` | chat and admin pages, API title | Page title and header: "Talk to Lessons Learned". `APP_NAME` in `.env` overrides it without editing this file. |
| `tagline` | chat page | Line under the title |
| `intro` | answer prompt | First line of the system prompt for the answer model |
| `situation` | answer prompt | What a user's situation is made of ("role, project, component, phase, problem"); used in the prompt and the clarifying rules |
| `clarify_question` | answer agent | Fixed reply to a too-vague first question |
| `no_match_text` | answer agent | Summary when the grader finds nothing that fits |
| `related_only_text` | answer agent, chat page | Summary / note when only related (not direct) lessons were found |
| `filtered_summary_text` | answer agent | Summary used after grading removes lessons |
| `placeholder` | chat page | Hint text in the input box |
| `examples` | chat page | Example question buttons: `label` + `question`. They cover the three main question types (comparable project, component, problem) plus "Recurring issues" |
| `filler_words` | answer agent (`is_vague`) | If a first question is made only of these words (words of 1-2 letters also count as filler) ("help", "Any lessons for me?"), it is too vague to search and the bot asks `clarify_question` instead (when `FEATURE_CLARIFYING_QUESTIONS=true`) |
| `stopwords` | in-memory keyword search ([search/memory.py](../app/search/memory.md)) | Words ignored by BM25 keyword search. Neo4j keyword search uses its Lucene analyzer instead |
| `personal_column_hints` | upload ([upload.py](../app/upload.md)) | Column names containing these words (person, contact, email...) get the default role `ignore` |
| `keep_status_values` | admin page | Filter values ticked by default for a status column (approved, closed, released, final) |

## Configuration
- `ASSISTANT_CONFIG` (default `backend/config/assistant.yaml`): which wording file to load.
- `FEATURE_CLARIFYING_QUESTIONS` (default `true`): off: `filler_words` and `clarify_question` are not used for the vague-question check.

## Dependencies
- **Used by:** [assistant.py](../app/assistant.md), which is called by [api.py](../app/api.md), [agents/answer.py](../app/agents/answer.md) and [search/memory.py](../app/search/memory.md); the browser gets the public part through `/api/config` ([frontend/app.js](../../frontend/app.js.md)).
- **Uses:** nothing.

## Example
```yaml
filler_words: >-
  a an and any ... lesson lessons learn learned ... me my ... for ...
clarify_question: >-
  Could you tell me a bit more about your situation: the project, the component or phase
  you're working on, or the problem you're facing?
```
The first question "Any lessons for me?" contains only filler words, so the bot answers with the clarifying question and does not search (eval question q24 checks this). "Which lessons exist for HVAC?" contains "exist" and "HVAC", which are not filler words, so it is searched.

## Known limitations and improvements
- The file is cached for the life of the process (`lru_cache`); a change needs a restart.
- `filler_words` is a fixed English list; a question in another language is never treated as vague. Idea: a small per-language list, or let the model decide.
- `stopwords` only affects the in-memory keyword search, not Neo4j.
- No check that required keys are present; a missing `intro` gives an empty first prompt line.
