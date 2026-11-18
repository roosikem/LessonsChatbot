# Glossary

Every technical word used in these docs, in plain language. Back to the [overview](README.md).

**Agent**
: A part of the backend with a few named methods (e.g. the retrieval agent has `search`, `get_lesson`).
  Here it does *not* mean "an autonomous AI"; only the [answer agent](files/backend/app/agents/answer.md) uses a language model to plan.
  See [flows/agents.md](flows/agents.md).

**Abstain**
: The bot says "no lesson clearly matches" instead of stretching loose matches. Happens when the grader marks every
  found lesson "not". [answer.py](files/backend/app/agents/answer.md)

**Answer cache**
: A memory of recent answers. The same question on the same data and settings is answered instantly.
  An entry is dropped after its **TTL** (time to live, 15 minutes by default), on a 👎, or when the cache is full
  (the least recently used entry goes first, **LRU**). New data gives a new key, so old answers are never reused.
  [cache.py](files/backend/app/cache.md)

**Bedrock (Amazon Bedrock)**
: AWS service to call language and embedding models in the cloud. We use **Nova 2 Lite** for answers and grading.

**BM25**
: A classic keyword-search score: a lesson scores higher when it contains the question's rare words often.
  Finds exact terms like "HVAC" or "regression" that meaning-search can miss. [search/memory.py](files/backend/app/search/memory.md)

**Client**
: The small object other code uses to reach an agent: `call(method, **arguments)`. A `LocalClient` calls it in the
  same process, an `HttpClient` over HTTP. [transport.py](files/backend/app/agents/transport.md)

**Chunk / row**
: Here one **lesson = one row** of the spreadsheet. Lessons are short, so they are not split into chunks.

**Comparable item**
: Another project (or supplier…) that shares important attributes with the one you named, e.g. same platform,
  same vehicle type. Scored 0..1 by weighted overlap. [context_sources.py](files/backend/app/context_sources.md)

**Confidence (high / medium / low)**
: A label on each lesson card, computed **in code** from the search signals and the grader, never from the
  model's own opinion. [answer.py](files/backend/app/agents/answer.md)

**Context / dimension**
: The columns that describe a lesson's situation: stage (e.g. *Commissioning*), topic (*Doors*), department,
  product group, location… Each column is a **dimension**, each cell a **context value**.

**Context source**
: An extra table a lesson links to, e.g. `projects.csv`, `suppliers.csv`. Its columns are **attributes** used to
  find comparable items. Any number can be configured. [dataset.yaml](files/backend/config/dataset.yaml.md)

**Cosine similarity**
: How close two vectors point in the same direction, 0..1 here. 1 = same meaning, ~0.4 = unrelated.

**Degraded answer**
: An answer made without a usable grader verdict, with a failed final model reply, or after a tool error. It is shown
  (with an issue note) but never cached, so the next ask tries again. [answer.py](files/backend/app/agents/answer.md)

**Embedding / vector**
: A list of numbers (1024 here) that represents the **meaning** of a text. Texts with similar meaning get similar vectors.
  Made by an embedding model (bge-m3 locally, Titan or Cohere on Bedrock). [embeddings.py](files/backend/app/embeddings.md)

**Evaluation (eval)**
: Running a fixed list of questions with known correct lessons and measuring how well the system does
  ([evaluation.py](files/backend/app/evaluation.md)).

**Feedback boost**
: 👍/👎 votes on a lesson move it slightly up/down **for questions similar to the voted one**. [feedback.py](files/backend/app/feedback.md)

**FastAPI**
: The Python web library the API is built with: each function becomes a web address (route). [api.py](files/backend/app/api.md)

**Flag (feature flag)**
: An on/off setting in `backend/.env`, e.g. `FEATURE_NEO4J=true`. [settings.py](files/backend/app/settings.md)

**Grader (evidence grader)**
: A second, strict model call that looks at the top found lessons and says for each: **relevant**, **partial**
  or **not**. Lessons graded "not" are never shown. [grader.py](files/backend/app/agents/grader.md)

**Graph / Neo4j**
: A database that stores **things and their connections** (lesson → project → platform). Good for "what is
  related to this?" questions. [graph.py](files/backend/app/agents/graph.md)

**SPARQL source**
: A company knowledge-graph platform (RDF, queried with SPARQL). Here it is an optional **data source**.
  [sparql_source.py](files/backend/app/agents/sparql_source.md)

**GraphRAG**
: RAG (below) that also uses a graph's connections, e.g. lessons of **comparable projects**.

**Grounding checks**
: Code that checks the model's answer against the data: every lesson ID must have been found, every quote must
  be in the lesson text, every reason must come from the search. Anything else is removed.

**Hybrid search**
: Meaning-search (embeddings) **plus** keyword-search (BM25 / Lucene), merged with RRF.

**Index / index version**
: Everything search needs (lessons, vectors, mapping), saved as one folder per version. A `CURRENT` file names
  the live one. [flows/storage-and-versions.md](flows/storage-and-versions.md)

**Ingest**
: Loading the data, computing embeddings and publishing a new index version. [flows/load-data.md](flows/load-data.md)

**JSON / JSON schema (structured output)**
: JSON is a plain text format for data (`{"id": "1003"}`). A JSON schema describes the shape a reply must have; the
  final answer is requested in that shape so code can check it. [llm.py](files/backend/app/llm.md)

**Language model (LLM)**
: The model that reads and writes text (Nova 2 Lite on Bedrock, or a local model via Ollama).

**Lucene**
: The keyword-search engine inside Neo4j (its full-text index), with an English analyzer (handles plurals, etc.).

**Mapping**
: The YAML file that says which column means what (id, title, text, context, ranking, ignore).
  It makes the system work with **any** spreadsheet layout. [dataset.yaml](files/backend/config/dataset.yaml.md)

**MCP (Model Context Protocol)**
: A standard "plug" that lets AI agents call tools from other systems. An idea for later ([improvements](improvements.md)).

**Ollama**
: A program that runs models on your own computer. Used for development: free, private, slower.

**RAG (retrieval-augmented generation)**
: First **find** relevant documents, then let a model **write** an answer using only them.

**Ranking signals**
: Numbers in the data that make a lesson more important: impact rating, user rating, recency.
  [ranking.py](files/backend/app/ranking.md)

**Pydantic-settings**
: A Python library that reads settings from environment variables and `.env` into a typed class.
  [settings.py](files/backend/app/settings.md)

**Recall / precision / MRR**
: *Recall*: of the correct lessons, how many were found. *Precision*: of the shown lessons, how many were correct.
  *MRR*: how high the first correct lesson is ranked (1.0 = always first).

**Role**
: What a column is for in the mapping: `id`, `title`, `text`, `context`, `ranking`, `filter` or `ignore`.
  [upload.py](files/backend/app/upload.md)

**RRF (reciprocal rank fusion)**
: A simple way to merge two ranked lists: each lesson gets `1 / (60 + rank)` from each list it appears in; the sum is
  then rescaled so the best lesson gets 1.0.
  [search/fusion.py](files/backend/app/search/fusion.md)

**S3**
: AWS file storage. Used to share the index and feedback between several containers.

**SPARQL**
: The query language for RDF knowledge graphs such as SPARQL source. [sparql.py](files/backend/app/sparql.md)

**SSE (server-sent events)**
: A way for the server to send live updates to the browser ("searching…", "checking 8 lessons…") while the answer is being made.

**Stop rule**
: If the first search clearly found good matches, stop planning and write the answer right away (saves one model call).

**Tool round**
: One model call that may ask for tools, plus running those tools. The answer agent allows at most
  `LLM_MAX_TOOL_ROUNDS` (default 2); then it asks for the final answer.

**Unresolved context**
: A context word the search could not map to exactly one value (project "line" fits Line 4 and Line 5). It is
  kept as typed and sent back with the candidates, so the model can ask or choose. [context.py](files/backend/app/context.md)

**Tool / tool call**
: A function the language model may ask the code to run, e.g. `search_lessons(query, context)`. The code runs it
  and gives the result back to the model.
