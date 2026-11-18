# `backend/app/llm.py`

> One small chat interface over two model backends, Ollama (local development) and Amazon Bedrock Converse (live), so the agents do not care which one runs.

**Part of:** [Ask a question](../../../flows/ask-a-question.md) · [Agents](../../../flows/agents.md) · [Deployment](../../../flows/deployment.md)  ·  **Layer:** Models

## Purpose

The project develops with local models (Ollama) and runs live with Claude or other models on Amazon Bedrock. The two speak different message formats. This file gives the [answer agent](agents/answer.md) and the [grader](agents/grader.md) one method, `chat(system, messages, tools, schema)`, and one reply shape, `Reply`. Switching is one setting: `LLM_PROVIDER=ollama` or `bedrock`.

It also builds the Bedrock client (retries, connection pool, timeouts, optional cross-account role), which [`embeddings.py`](embeddings.md) reuses. Terms like [tool call](../../../glossary.md), [structured output / JSON schema](../../../glossary.md) and [Bedrock](../../../glossary.md) are in the [glossary](../../../glossary.md).

## How it works

**Neutral message shape** (used by the agents):
- `{"role": "user" | "assistant", "content": str, "tool_calls": [...]}`
- `{"role": "tool", "tool_call_id": str, "name": str, "content": dict}`
- a tool call is `{"id", "name", "input"}`.

**Ollama** (`OllamaLLM.chat`):
1. Sends `POST /api/chat` with `stream: false`, `think: false`, the temperature, the system prompt as the first message, and the converted messages.
2. Tools are sent in Ollama's "function" format; a JSON schema is sent as `format`.
3. Tool calls get a random 8-character ID if Ollama gives none. With a schema, the reply text is parsed as JSON into `reply.data`.

**Bedrock** (`BedrockLLM.chat`):
1. Tools become Converse `toolSpec`s with `toolChoice: auto`.
2. Converse has no JSON mode, so when a schema is asked for, the code offers a single tool called `answer` with that schema and forces the model to call it. The tool input becomes `reply.data`.
3. `_to_converse` converts messages. Converse wants user and assistant turns to alternate and no turn to be empty, so tool results are sent as `toolResult` blocks in a user turn, empty texts are skipped, neighbouring turns of the same role are merged, and leading non-user turns are dropped.
4. If the reply stops at the token limit (`stopReason == "max_tokens"`), it tries once more with twice the room (2000 -> 4000 tokens). If that is cut off too, it raises `CutOff`, because a cut-off tool input or answer could look valid but miss parts.
5. Usage (input/output tokens, model latency in ms) is copied into `reply.usage`.

**Bedrock client** (`bedrock_client`): adaptive retries, a connection pool and a read timeout from the settings, connect timeout 5 s. With `BEDROCK_ROLE_ARN` it assumes that role (Bedrock in another AWS account), with credentials that renew themselves before they expire (1-hour sessions).

## Key components

- `Reply`: `text`, `tool_calls`, `data` (filled when a schema was requested), `usage`.
- `OllamaLLM(model, url, timeout=600, temperature=0.1)`: `.chat(...)`.
- `BedrockLLM(model_id, profile, region, temperature=0.1, settings)`: `.chat(...)`; `max_tokens = 2000`.
- `CutOff`: raised when a Bedrock reply hit the token limit twice.
- `bedrock_client(profile, region, settings)`: a `bedrock-runtime` boto3 client.
- `assumed_session(base, role_arn, region)`: a boto3 session on another account's role with auto-renewing credentials.
- `make_llm(settings, provider=None, model_id=None, temperature=0.1)`: the main chat model, or another one (the grader passes its own provider, model and temperature 0). Raises `ValueError` if no model ID is set.

## Configuration

| Setting | Default | Effect |
|---|---|---|
| `LLM_PROVIDER` | ollama | `ollama` or `bedrock`. |
| `LLM_MODEL_ID` | none (required) | Model name or Bedrock model ID. |
| `OLLAMA_URL` | http://localhost:11434 | Ollama server. |
| `BEDROCK_AWS_PROFILE` | none in settings (`.env.example`: default) | AWS profile for Bedrock calls. |
| `BEDROCK_REGION` | us-east-1 | Bedrock region. |
| `BEDROCK_ROLE_ARN` | none | Assume this role for Bedrock in another account. |
| `BEDROCK_MAX_ATTEMPTS` | 4 | botocore retry `max_attempts` (adaptive mode). |
| `BEDROCK_MAX_CONNECTIONS` | 32 | Connection pool size per client. |
| `BEDROCK_READ_TIMEOUT` | 60 | Read timeout in seconds. |
| `GRADER_PROVIDER`, `GRADER_MODEL_ID` | empty | Passed in by the grader to `make_llm`. |

The temperature (0.1, grader 0), the token limit (2000) and the Ollama timeout (600 s) are fixed in the code.

## Dependencies

- **Used by:** [`agents/__init__.py`](agents/__init__.md) (`make_answer_agent`), [`agents/grader.py`](agents/grader.md), [`embeddings.py`](embeddings.md) (`bedrock_client`), [`evaluation.py`](evaluation.md) and [`cli.py`](cli.md) indirectly through the wiring.
- **Uses:** Ollama over HTTP (`urllib`), `boto3` / `botocore` for Bedrock and STS.

## Example

```python
llm = make_llm(settings)          # LLM_PROVIDER=bedrock
r = llm.chat("You help engineers ...", [{"role": "user", "content": "door software keeps failing"}],
             tools=[{"name": "search_lessons", "description": "...", "schema": {...}}])
r.tool_calls  # [{"id": "tooluse_...", "name": "search_lessons", "input": {"query": "door software failing"}}]

r = llm.chat("...", messages, schema={"type": "object", ...})
r.data        # {"clarifying_question": "", "summary": "...", "lessons": [...]}, from the forced "answer" tool
```

## Known limitations and improvements

- `OllamaLLM` has no cut-off check, and with a schema it parses the reply text with `json.loads`, which raises if the model returns invalid JSON (caught by the answer agent for the final call; for the grader it becomes "evidence check unavailable").
- In `BedrockLLM`, if the model does not call the forced `answer` tool, the code falls back to `json.loads(reply.text)`, which can also raise. The answer agent catches such errors from the final call (`_final` in [answer.py](agents/answer.md)): the answer is then built from the checked lessons and marked degraded.
- `assumed_session` sets `core._credentials`, a private botocore attribute; a botocore update could break it.
- Temperature and token limit are not settings. Idea: make them settings if a model needs more room.
- Idea: an LLM gateway as another provider here (tool use and structured output would need checking).
