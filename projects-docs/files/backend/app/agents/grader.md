# `backend/app/agents/grader.py`

> The evidence grader: a second, strict model call that marks each found lesson as "relevant", "partial" or "not" for the user's question, before the answer is trusted.

**Part of:** [Ask a question](../../../../flows/ask-a-question.md) · [Agents](../../../../flows/agents.md)  ·  **Layer:** Agent

## Purpose

Search always returns something, even when no lesson really fits. For a question like "What did we learn about battery-powered trains?" the search may still return door lessons that share a generic word. The grader reads the top hits and says which ones really help. If none do, the [answer agent](answer.md) abstains instead of stretching loose matches.

It is a separate agent so it can use a smaller model, run as its own service, or be switched off with `FEATURE_EVIDENCE_GRADING`. See the [glossary](../../../../glossary.md) for "evidence grader" and "abstain".

## How it works

1. The answer agent sends the question (with earlier user messages and the search queries) and the top candidates: `{id, title, text, context}`.
2. `describe` turns each candidate into a short block: `[1003] Door software change again not regression tested`, a `Context:` line (e.g. `stage: Commissioning; topic: Doors`), and the first 600 characters of the text.
3. One model call with the `SYSTEM` prompt and the JSON `SCHEMA`. The model is told to be strict, to treat the context line as important as the text, and to give only grades, no explanations. It also fills `missing` (what none of the lessons cover) and `next_step` (one suggestion if nothing is relevant), in the user's language.
4. The reply is cleaned: IDs are trimmed (also `[1003]` becomes `1003`), unknown IDs and unknown grades are ignored.
5. Any candidate the model skipped gets "partial" (kept, but not fully trusted). `valid` counts only the grades the model really gave, so the answer agent can tell a broken reply from a real verdict.

The model runs at temperature 0, so the same candidates should get the same grades.

## Key components

- `GRADES`: `("relevant", "partial", "not")`.
- `SYSTEM`, `SCHEMA`: the grader prompt and the reply shape (`grades: [{id, grade}]`, `missing`, `next_step`).
- `GraderAgent(settings, llm=None)`: builds its own model with `make_llm(settings, provider=GRADER_PROVIDER, model_id=GRADER_MODEL_ID or LLM_MODEL_ID, temperature=0)`. Exposes `info` and `grade`.
- `GraderAgent.info()`: `{"model": <model id>}`.
- `GraderAgent.grade(question, candidates)`: returns `{grades: {id: grade}, valid, usage, missing, next_step}`. With no candidates it returns empty grades and `valid: 0` without a model call.
- `describe(candidate, text_chars)`: the text block for one candidate.

## Configuration

| Setting | Default | Effect |
|---|---|---|
| `FEATURE_EVIDENCE_GRADING` | false | Whether the grader is used at all (checked in [`__init__.py`](__init__.md)). |
| `GRADER_PROVIDER` | empty, means `LLM_PROVIDER` (an empty value in `.env`, `GRADER_PROVIDER=`, also means "use the default") | `ollama` or `bedrock` for the grader model. |
| `GRADER_MODEL_ID` | empty, means `LLM_MODEL_ID` | The grader model; `.env.example` says a small model is enough. |
| `GRADER_MAX_CANDIDATES` | 8 | How many hits are sent (used in [answer.py](answer.md), not here). |
| `AGENT_GRADER_URL` | empty | If set, the grader runs as its own HTTP service. |

The text length per candidate (600 characters) is fixed in the code (`self.text_chars`), not a setting.

## Dependencies

- **Used by:** [`answer.py`](answer.md) through a client built in [`__init__.py`](__init__.md) (`grader_client`, `make_agent("grader")`).
- **Uses:** [`llm.py`](../llm.md) (`make_llm`).

## Example

Input:

```python
grade("door software keeps failing", [
  {"id": "1003", "title": "Door software change again not regression tested", "text": "A hotfix to the door control software ...", "context": {"stage": ["Commissioning"]}},
  {"id": "1002", "title": "Door obstruction detection too sensitive in winter", "text": "Ice on door seals ...", "context": {}}])
```

Model reply: `{"grades": [{"id": "[1003]", "grade": "relevant"}], "missing": "", "next_step": ""}` (it skipped 1002).

Output: `{"grades": {"1003": "relevant", "1002": "partial"}, "valid": 1, "usage": {...}, "missing": "", "next_step": ""}`.

## Known limitations and improvements

- The 600-character cut is fixed and separate from `TOOL_TEXT_CHARS`; long lessons are judged on their start only.
- Grades come without reasons (on purpose, for speed), so a wrong grade is hard to debug from the result.
- `.env.example` records the grader models tried: `us.amazon.nova-2-lite-v1:0` tested good, Nova Micro was too lenient. A new grader model should be checked with the answer eval.
- With no candidates `grade` returns `valid: 0`; the answer agent does not call the grader in that case, so "no hits" is not counted as a grader failure.
- Idea: use logged grader decisions as few-shot examples.
