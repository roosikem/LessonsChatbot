# What to improve

> Honest limits of today's system and the ideas to fix them, ranked.
> Back to the [overview](README.md).

## Already fixed

- Empty answer when the grader and the model disagreed → cards are now built from the lessons the grader kept.
- Votes counted as evidence → no longer.
- Loose context matching ("Decommissioning" → "Commissioning") → whole-word / prefix / close-typo matching only;
  ambiguous words go back to the model.
- Feedback slowed searches → embeddings stored with votes, S3 loaded in the background, one vote per person.
- No load protection → per-container limit, Bedrock retries, timeouts, cut-off replies detected.
- Ambiguous names guessed ("line" → one of Line 4 / Line 5) → kept as typed and returned with the candidates;
  `comparable_items` asks which one instead of picking.
- A failed or cut-off final model reply failed the question → the answer is built from the checked lessons and marked degraded.
- "No hits" counted as a grader failure → the grader is skipped when the search found nothing.
- Tool loop ran one round more than `LLM_MAX_TOOL_ROUNDS` → capped at exactly that number.
- Empty values in `.env` (`GRADER_PROVIDER=`) broke the start → they now mean "use the default".
- Uploads silently ignored with `DATA_SOURCE=sparql` → the upload routes answer 409.

## Next, ranked by value

| # | Idea | Why | Effort | Status |
|---|---|---|---|---|
| 1 | **Search-first fast path** | answers in ~1.5–2.5 s instead of ~3.0 s; first cards in < 0.5 s | ~1 day | proposed |
| 2 | **Production test set** (100+ questions, expert labels) as an automatic quality gate | every other change becomes measurable | needs data + an expert | proposed |
| 3 | **Fargate test run** in a test AWS account with S3 and 2 containers | proves the deployment before going live | ~half a day | proposed |
| 4 | **MCP tool**: other AI agents use our search (platform: MCP Server on Fargate / AgentCore MCP) | reuse of the search by other systems | ~half a day | proposed |
| 5 | **Lesson cards at load time** (one-line learning + tags per lesson) | component questions without a component column; less writing per question | medium | future plan |
| 6 | **Several searches in parallel** for broad questions | fewer missed lessons | small | proposed |
| 7 | **Recurring-issue themes** precomputed at load time | instant "what keeps coming back" | medium, needs 5 | idea |
| 8 | Upload context-source files on the admin page | no config editing for projects/suppliers | small | proposed |
| 9 | Votes and logs in a database (DynamoDB / Aurora) | many containers, many votes | medium | later |
| 10 | AgentCore Guardrails on input | off-topic and prompt-injection protection | small | later |

## Decided against (for now)

- **Project picker / "Brief me" button**: rejected; users ask in their own words (a named project in the question
  already brings in comparable projects).
- **Semantic answer cache**: risky ("Line 4" vs "Line 5" questions look alike) and small gain.
- **Google Vertex AI Search for the lessons list**: would replace only the cheapest part (search) and move data out of
  AWS; maybe later for long documents.
- **Reranker model (Cohere Rerank)**: the grader already does this job; test only if real lessons are long.
