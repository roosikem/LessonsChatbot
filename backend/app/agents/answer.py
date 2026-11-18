import re
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

from app import assistant
from app.cache import AnswerCache, make_key, normalize_question
from app.llm import Reply
from app import context as ctx

TOOLS = [
    {
        "name": "search_lessons",
        "description": "Hybrid search over lessons learned. Use it for every question. Put the user's problem or "
                       "topic in `query`. Use `context` for known values of the context dimensions, and "
                       "`related_to` ({source: name}) when the user names an item of a context source, so lessons "
                       "linked to the same or comparable items are boosted.",
        "schema": {"type": "object", "properties": {
            "query": {"type": "string"},
            "context": {"type": "object", "additionalProperties": {"type": "array", "items": {"type": "string"}}},
            "related_to": {"type": "object", "additionalProperties": {"type": "string"}},
        }, "required": ["query"]},
    },
    {
        "name": "resolve_context",
        "description": "Map a word from the user to the exact values used in the data before passing it as context.",
        "schema": {"type": "object", "properties": {
            "term": {"type": "string"}, "dimension": {"type": "string"}}, "required": ["term"]},
    },
    {
        "name": "comparable_items",
        "description": "List items of a context source comparable to a given item (shared weighted attributes).",
        "schema": {"type": "object", "properties": {
            "source": {"type": "string"}, "name": {"type": "string"}}, "required": ["source", "name"]},
    },
    {
        "name": "count_by",
        "description": "Count lessons per value of a context dimension, optionally only among lessons matching a "
                       "query. Use for recurring issues or 'which value comes up most'.",
        "schema": {"type": "object", "properties": {
            "dimension": {"type": "string"}, "query": {"type": "string"}}, "required": ["dimension"]},
    },
]

RELATED_TOOL = {
    "name": "related_lessons",
    "description": "Graph lookup: lessons connected to a given lesson through shared context, the same context item "
                   "or comparable items. Use it to widen a good hit or to show recurring issues.",
    "schema": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
}

REASON_TYPES = ["context_match", "same_item", "comparable_item", "similar_problem"]

ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "clarifying_question": {"type": "string", "description": "Empty unless one question is needed first."},
        "summary": {"type": "string"},
        "lessons": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "learning": {"type": "string"},
                "why_relevant": {"type": "array", "items": {
                    "type": "object",
                    "properties": {
                        "type": {"type": "string", "enum": REASON_TYPES},
                        "dimension": {"type": "string", "description": "context_match: the dimension"},
                        "source": {"type": "string", "description": "same_item / comparable_item: the context source"},
                        "value": {"type": "string"},
                    },
                    "required": ["type", "value"],
                }},
                "quote": {"type": "string"},
            },
            "required": ["id", "learning", "why_relevant", "quote"],
        }},
    },
    "required": ["clarifying_question", "summary", "lessons"],
}

# used with FEATURE_REASONS_IN_CODE: context / item reasons come from the search, the model only says
# whether the problem itself is similar, which keeps the answer (and its latency) short
COMPACT_SCHEMA = {
    "type": "object",
    "properties": {
        "clarifying_question": {"type": "string", "description": "Empty unless one question is needed first."},
        "summary": {"type": "string"},
        "lessons": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "learning": {"type": "string"},
                "problem_match": {"type": "string", "description": "How the lesson's problem resembles the user's; empty if it doesn't"},
                "quote": {"type": "string"},
            },
            "required": ["id", "learning", "quote"],
        }},
    },
    "required": ["clarifying_question", "summary", "lessons"],
}

SYSTEM = """{intro}

Work like this: understand the user's situation ({situation}), search the lessons with the tools, then explain what was learned and why it applies.

Rules:
- Only use lessons returned by the tools. Never invent lessons, IDs, projects or quotes.
- Context dimensions in the data: {dimensions}. {context_hint}
- Make all the tool calls you need in one step where you can (e.g. comparable_items and search_lessons together).
- Context sources (linked tables): {sources}. If the user names one of their items, pass it in `related_to`.
- search_lessons returns a `signal`: "ok", "weak" (nothing clearly matched) or "none". On "weak" or "none", say plainly that no clearly matching lesson was found instead of stretching loose matches.
{clarify_rules}- Answer in the user's language. Quotes stay in the original language of the lesson.
"""

CLARIFY_RULES = """- If the request is too vague to search at all (nothing about the situation: {situation}), ask one short clarifying question instead of answering.
- If you found relevant lessons but one detail of the situation would sharpen the answer, give the lessons anyway and add that one question as a follow-up.
"""

FINAL = """Now write the final answer as JSON.
- lessons: up to 5 of the most useful lessons from the tool results, best first. Fewer is fine; leave out lessons that don't really help.
- learning: the transferable learning in one or two sentences, phrased as advice.
{reason_rules}
- quote: a short exact quote copied from the lesson text (at least a few words).
- If nothing relevant was found, return no lessons and say so in summary.
{clarify_final}"""

CLARIFY_FINAL = ("- clarifying_question: empty, or one short question. If relevant lessons were found, still return them "
                 "and use the question only to offer a sharper follow-up. Leave lessons empty only when the request was "
                 "too vague to search.")
NO_CLARIFY_FINAL = "- clarifying_question: always empty."

MODEL_REASONS = ("- why_relevant: concrete reasons. context_match needs `dimension` and `value` exactly as in the lesson's "
                 "context; same_item / comparable_item need `source` and the item name as `value`; similar_problem when "
                 "the problem described is similar.")
CODE_REASONS = ("- learning: one sentence.\n- problem_match: if the lesson's problem resembles the user's, a short phrase "
                "saying how; otherwise empty. (Shared context is added automatically.)")
CONTEXT_BY_SEARCH = "search_lessons maps loose values to these itself; pass the user's words as context."
CONTEXT_BY_TOOL = "Use resolve_context to map the user's words to real values."

NOT_SUPPORTED = "None of the lessons found in the data clearly support an answer to this question."

# what the model may pass to each tool, and the type it has to be
TOOL_ARGS = {
    "search_lessons": {"query": str, "context": dict, "related_to": dict},
    "resolve_context": {"term": str, "dimension": str},
    "comparable_items": {"source": str, "name": str},
    "count_by": {"dimension": str, "query": str},
    "related_lessons": {"id": str},
}
REQUIRED = {"search_lessons": "query", "resolve_context": "term", "comparable_items": "name",
            "count_by": "dimension", "related_lessons": "id"}
MIN_QUOTE_CHARS = 15

def is_vague(question, filler):
    """A first question made only of filler words (from config/assistant.yaml) can't be searched meaningfully."""
    words = re.findall(r"\w+", question.lower())
    return sum(1 for w in words if w not in filler and len(w) > 2) == 0


def clean_args(name, args):
    """Keep known arguments of the right type; returns (args, error)."""
    spec = TOOL_ARGS.get(name)
    if spec is None:
        return None, f"unknown tool {name}"
    out = {}
    for key, value in (args or {}).items():
        if key not in spec or value in (None, "", {}, []):
            continue
        if spec[key] is str and isinstance(value, (int, float)):
            value = str(value)
        if key == "context":
            value = ctx.normalize(value)
        elif key == "related_to":
            value = {str(k): str(v) for k, v in value.items() if v} if isinstance(value, dict) else {}
        if spec[key] is dict and not value:
            continue
        if not isinstance(value, spec[key]):
            continue
        out[key] = value
    if REQUIRED[name] not in out:
        return None, f"{name} needs `{REQUIRED[name]}`"
    return out, None


def normalize(text):
    return re.sub(r"\s+", " ", text or "").strip().lower()


def check_answer(answer, retrieved, min_similarity=0.0, reasons_from_code=False):
    """Keep only what the retrieved lessons support. Returns (answer, issues).
    reasons_from_code: build "why relevant" from the search results instead of checking the model's."""
    issues, kept = [], []
    question = (answer.get("clarifying_question") or "").strip()
    if question.lower().strip(".") in ("none", "null", "n/a", "no"):
        question = ""
    answer = {**answer, "clarifying_question": question}
    for item in answer.get("lessons", []):
        lid = str(item.get("id", "")).strip()
        hit = retrieved.get(lid)
        if hit is None:
            issues.append(f"dropped {lid}: not in retrieved lessons")
            continue

        source = normalize(hit["title"] + " " + hit["text"])
        quote = (item.get("quote") or "").strip()
        bare = normalize(quote).strip(" .\"'“”")
        if quote and (len(bare) < MIN_QUOTE_CHARS or bare not in source):
            issues.append(f"{lid}: quote too short or not in lesson text, removed")
            quote = ""

        if reasons_from_code:
            reasons = code_reasons(hit, item.get("problem_match"), quote)
            kept.append({**item, "id": lid, "quote": quote, "why_relevant": reasons,
                         "title": hit["title"], "text": hit["text"], "context": hit["context"],
                         "confidence": confidence(hit, min_similarity)})
            continue

        # item reasons must be ones the search itself produced: (kind, source, name, ...)
        search_items = {(r[1].casefold(), r[2].casefold()) for r in hit["reasons"] if r[0] in ("same_item", "comparable_item")}
        reasons = []
        for r in item.get("why_relevant", []):
            kind, value = r.get("type"), (r.get("value") or "").strip()
            if kind == "context_match":
                ok = bool(ctx.matches(hit["context"], {r.get("dimension", ""): [value]}))
            elif kind in ("same_item", "comparable_item"):
                source = (r.get("source") or "").casefold()
                ok = (source, value.casefold()) in search_items or (
                    not source and value.casefold() in {name for _, name in search_items})
            elif kind == "similar_problem":
                ok = bool(quote)
            else:
                ok = False
            if ok:
                reasons.append(r)
            else:
                issues.append(f"{lid}: reason {kind}={value} not supported, removed")

        kept.append({**item, "id": lid, "quote": quote, "why_relevant": reasons,
                     "title": hit["title"], "text": hit["text"], "context": hit["context"],
                     "confidence": confidence(hit, min_similarity)})

    if answer.get("lessons") and not kept and not question:
        # everything the model cited was dropped, so its summary describes lessons we no longer show
        answer["summary"] = NOT_SUPPORTED
    return {**answer, "lessons": kept}, issues


def code_reasons(hit, problem_match, quote):
    """Reasons the search already established, plus "similar problem" when the model says so and quotes it."""
    out = []
    for r in hit["reasons"]:
        if r[0] == "context_match":
            out.append({"type": "context_match", "dimension": r[1], "value": r[2]})
        elif r[0] in ("same_item", "comparable_item"):
            out.append({"type": r[0], "source": r[1], "value": r[2]})
        elif r[0] == "feedback":
            out.append({"type": "feedback", "value": f"{r[1]} up, {r[2]} down"})
    if problem_match and quote:
        out.append({"type": "similar_problem", "value": problem_match.strip()})
    return out


def evidence(reasons):
    """Reasons that say something about the content. User votes rank, but don't prove relevance."""
    return [r for r in reasons if r[0] != "feedback"]


def confidence(hit, min_similarity=0.0):
    # from retrieval signals and the separate evidence check, never from the answer model's opinion of itself
    if hit["similarity"] < min_similarity:
        return "low"
    grade = hit.get("grade")
    reasons = evidence(hit["reasons"])
    strong = hit["rank"] <= 3 and hit["similarity"] >= 0.9 * hit["top_similarity"]
    if strong and (reasons or grade == "relevant") and grade != "partial":
        return "high"
    if hit["similarity"] < 0.75 * hit["top_similarity"] and not reasons and grade != "relevant":
        return "low"
    return "medium"


def search_signal(hits, min_similarity=0.0):
    if not hits:
        return "none"
    sims = sorted((h["similarity"] for h in hits), reverse=True)
    backed = any(evidence(h["reasons"]) for h in hits)
    if sims[0] < min_similarity and not backed:
        return "weak"
    flat = len(sims) >= 5 and sims[0] - sims[4] < 0.02
    return "weak" if flat and not backed else "ok"


class AnswerAgent:
    name = "answer"
    methods = ("ask", "forget")

    def __init__(self, settings, llm, retrieval_client, graph_client=None, grader_client=None):
        self.settings = settings
        self.llm = llm
        self.retrieval = retrieval_client
        self.graph = graph_client
        self.grader = grader_client
        self.tools = TOOLS + ([RELATED_TOOL] if graph_client else [])
        self.min_similarity = settings.confidence_min_similarity
        self.wording = assistant.for_settings(settings)
        self.cache = (AnswerCache(settings.answer_cache_ttl_seconds, settings.answer_cache_size)
                      if settings.feature_answer_cache else None)

    def ask(self, question, history=None, on_event=None):
        # on_event only works in-process (the API uses it to stream progress)
        emit = on_event or (lambda event: None)
        if self.settings.feature_clarifying_questions and not history and is_vague(question, self.wording["filler_words"]):
            # decided in code, so it doesn't depend on how a given model behaves (and needs no cache)
            answer = {"clarifying_question": self.wording["clarify_question"], "summary": "", "lessons": []}
            return {"answer": answer, "issues": [], "trace": [], "not_found": False, "degraded": False,
                    "id": uuid.uuid4().hex[:12], "timings": [{"step": "vague check", "seconds": 0.0}]}
        key = self._cache_key(question, history) if self.cache is not None else None
        if key and (cached := self.cache.get(key)):
            emit({"type": "cached"})
            # the key doesn't include feedback votes: a cached answer can lag new votes by up to the TTL
            return {**cached, "cached": True, "timings": [{"step": "cache", "seconds": 0.0}]}
        result = self._answer(question, history, emit)
        result["id"] = uuid.uuid4().hex[:12]
        if key and cacheable(result):
            self.cache.put(key, result)
        return result

    def forget(self, answer_id):
        """Called on a thumbs-down: the next identical question gets a fresh answer."""
        return {"forgotten": bool(self.cache and self.cache.forget(answer_id))}

    def _cache_key(self, question, history):
        s = self.settings
        # everything that changes the answer: the data version, models, flags, ranking, wording
        relevant = {k: v for k, v in s.model_dump(mode="json").items()
                    if k.startswith(("feature_", "llm_", "grader_", "top_k", "score_w", "tool_text", "confidence_"))}
        return make_key(normalize_question(question), [(m.get("role"), m.get("content")) for m in history or []],
                        self.retrieval.call("version"), relevant, self.wording.get("hash"))

    def _answer(self, question, history, emit):
        clarify = self.settings.feature_clarifying_questions
        messages = list(history or []) + [{"role": "user", "content": question}]
        retrieved, trace = {}, []
        # read per question: an upload can add new context dimensions
        sources = self.retrieval.call("sources")
        source_text = "; ".join(f"{name} (linked through `{info['lesson_column']}`)" for name, info in sources.items()
                                if info["lesson_column"])
        situation = self.wording.get("situation", "")
        s = self.settings
        system = SYSTEM.format(intro=self.wording.get("intro", ""), situation=situation,
                               dimensions=", ".join(self.retrieval.call("dimensions")), sources=source_text or "none",
                               context_hint=CONTEXT_BY_SEARCH if s.feature_auto_resolve_context else CONTEXT_BY_TOOL,
                               clarify_rules=CLARIFY_RULES.format(situation=situation) if clarify else "")
        final_prompt = FINAL.format(clarify_final=CLARIFY_FINAL if clarify else NO_CLARIFY_FINAL,
                                    reason_rules=CODE_REASONS if s.feature_reasons_in_code else MODEL_REASONS)
        timings = []

        for _ in range(s.llm_max_tool_rounds):  # at most this many tool rounds; then the final answer
            reply = self._chat(timings, "tool step", system, messages, tools=self.tools)
            if not reply.tool_calls:
                break
            messages.append({"role": "assistant", "content": reply.text, "tool_calls": reply.tool_calls})
            good_search = False
            for call in reply.tool_calls:
                emit({"type": "tool", "tool": call["name"], "input": call["input"]})
                result = self._run_tool(call["name"], call["input"], retrieved)
                trace.append({"tool": call["name"], "input": call["input"], **({"error": result["error"]}
                                                                               if "error" in result else {})})
                messages.append({"role": "tool", "tool_call_id": call["id"], "name": call["name"], "content": result})
                if call["name"] == "search_lessons":
                    emit_candidates(emit, result)
                good_search = good_search or (call["name"] == "search_lessons" and result.get("signal") == "ok")
            if s.feature_stop_rule and good_search:
                # a search that found clear matches: answer now instead of asking the model what to do next
                break

        if not retrieved:
            # the model answered without searching; search anyway so the answer stays grounded
            call = {"id": "auto-search", "name": "search_lessons", "input": {"query": question}}
            emit({"type": "tool", "tool": "search_lessons", "input": call["input"]})
            messages.append({"role": "assistant", "content": "", "tool_calls": [call]})
            result = self._run_tool(call["name"], call["input"], retrieved)
            emit_candidates(emit, result)
            trace.append({"tool": "search_lessons", "input": call["input"], "auto": True})
            messages.append({"role": "tool", "tool_call_id": call["id"], "name": call["name"], "content": result})

        pre_issues, graded = [], None
        top = sorted(retrieved.values(), key=lambda h: h["rank"])[:s.grader_max_candidates]
        gq = grader_question(question, history, trace)
        schema = COMPACT_SCHEMA if s.feature_reasons_in_code else ANSWER_SCHEMA
        final_messages = messages + [{"role": "user", "content": final_prompt}]

        grader = self.grader if top else None  # nothing found: nothing to grade, the answer says so
        if grader and not s.feature_parallel_grading:
            # grade first, then steer the final answer with the result (slower, one call after the other)
            graded = self._grade(gq, top, retrieved, emit, pre_issues, timings)
            if graded and graded["mode"] == "none":
                return self._abstain(graded, pre_issues, trace, timings)
            if graded:
                final_messages[-1] = {"role": "user", "content": evidence_note(retrieved, graded) + "\n\n" + final_prompt}
            emit({"type": "writing", "lessons_found": len(retrieved)})
            final = self._final(timings, system, final_messages, schema, pre_issues)
        elif grader:
            # grade and write at the same time; the grades are applied to the finished answer in code
            emit({"type": "grading", "candidates": len(top)})
            emit({"type": "writing", "lessons_found": len(retrieved)})
            with ThreadPoolExecutor(max_workers=1) as pool:
                pending = pool.submit(self._call_grader, gq, top, pre_issues, timings)
                final = self._final(timings, system, final_messages, schema, pre_issues)
                result = pending.result()
            if result:
                if len(retrieved) > len(top):
                    pre_issues.append(f"{len(retrieved) - len(top)} lower-ranked lessons were not graded and left out")
                graded = decide(top, result)
                if graded["mode"] == "none":
                    return self._abstain(graded, pre_issues, trace, timings)
                apply_grades(retrieved, graded)
        else:
            emit({"type": "writing", "lessons_found": len(retrieved)})
            final = self._final(timings, system, final_messages, schema, pre_issues)

        answer = final.data or {"clarifying_question": "", "summary": "", "lessons": []}
        if final.data is None and retrieved:
            # the model's answer failed: still show the best checked lessons, built from the data
            keep = graded["keep"] if graded else [h["id"] for h in top[:3]]
            answer = {"clarifying_question": "", "summary": self.wording.get("filtered_summary_text", ""),
                      "lessons": cards_from_data(retrieved, keep[:3])}
        dropped = []
        if graded and s.feature_parallel_grading:
            answer, dropped = drop_ungraded(answer, retrieved)
            pre_issues += [f"{lid}: left out by the evidence check" for lid in dropped]
            if dropped and not answer["lessons"]:
                # the model cited only lessons the check removed: show the ones it kept, built from the data
                answer["lessons"] = cards_from_data(retrieved, graded["keep"][:3])
                pre_issues.append("answer cards built from the checked lessons (the model cited other ones)")
        if s.feature_grounding_checks:
            answer, issues = check_answer(answer, retrieved, self.min_similarity, s.feature_reasons_in_code)
        else:
            answer, issues = attach_lessons(answer, retrieved, self.min_similarity), []
        if not clarify:
            answer["clarifying_question"] = ""
        if s.feature_score_order:
            # the search's ranking (text match, context, related items, signals, feedback), not the model's order
            answer["lessons"].sort(key=lambda l: (retrieved[l["id"]]["rank"], -retrieved[l["id"]]["score"]))
        if graded:
            label_with_grades(answer, retrieved, graded, self.wording, summary_from_code=bool(dropped)
                              or graded["mode"] == "related_only" and s.feature_parallel_grading)
        issues = pre_issues + issues
        # degraded: the evidence check didn't run or a tool failed. Shown as is, but never cached.
        degraded = ((grader is not None and graded is None) or final.data is None
                    or any("error" in t for t in trace))
        return {"answer": answer, "issues": issues, "trace": trace, "timings": timings, "degraded": degraded,
                "not_found": not answer["lessons"] and not answer.get("clarifying_question")}

    def _abstain(self, graded, issues, trace, timings):
        answer = abstain_answer(graded["result"], self.wording.get("no_match_text", ""))
        return {"answer": answer, "issues": issues, "trace": trace, "not_found": True, "timings": timings}

    def _chat(self, timings, step, system, messages, tools=None, schema=None):
        start = time.time()
        reply = self.llm.chat(system, messages, tools=tools, schema=schema)
        timings.append({"step": step, "seconds": round(time.time() - start, 2), **(reply.usage or {})})
        return reply

    def _final(self, timings, system, messages, schema, issues):
        """The final answer call; a failure (cut-off or broken reply, timeout) is noted, not raised."""
        try:
            reply = self._chat(timings, "final answer", system, messages, schema=schema)
            if reply.data is not None:
                return reply
            issues.append("final answer had no usable content; showing the checked lessons")
        except Exception as e:
            issues.append(f"final answer failed ({type(e).__name__}); showing the checked lessons")
        return Reply()

    def _call_grader(self, question, top, issues, timings):
        """The grader agent's verdict on the top candidates, or None if it failed or answered badly."""
        start = time.time()
        try:
            result = self.grader.call("grade", question=question, candidates=[
                {"id": h["id"], "title": h["title"], "text": h["text"], "context": h["context"]} for h in top])
        except Exception as e:  # grading is a safety net; never let it break the answer
            issues.append(f"evidence check unavailable ({type(e).__name__}); answered without it")
            return None
        timings.append({"step": "grader", "seconds": round(time.time() - start, 2), **(result.get("usage") or {})})
        if result.get("valid", len(top)) < max(1, len(top) // 2):
            issues.append("evidence check reply was unusable; answered without it")
            return None
        return result

    def _grade(self, question, top, retrieved, emit, issues, timings):
        emit({"type": "grading", "candidates": len(top)})
        result = self._call_grader(question, top, issues, timings)
        if result is None:
            return None
        if len(retrieved) > len(top):
            issues.append(f"{len(retrieved) - len(top)} lower-ranked lessons were not graded and left out")
        graded = decide(top, result)
        apply_grades(retrieved, graded)
        return graded

    def _run_tool(self, name, args, retrieved):
        if name == "related_lessons" and not self.graph:
            return {"error": "related_lessons needs the graph, which is switched off"}
        args, error = clean_args(name, args)
        if error:
            return {"error": error}
        try:
            if name == "search_lessons":
                result = self.retrieval.call("search", **args)
                remember_hits(retrieved, result["hits"])  # full hits stay here for the checks
                return for_model(result, search_signal(result["hits"], self.min_similarity),
                                 self.settings.tool_text_chars)
            if name == "related_lessons":
                return self.graph.call("related_lessons", **args)
            method = {"resolve_context": "resolve_context", "comparable_items": "comparable_items",
                      "count_by": "count_by"}[name]
            return self.retrieval.call(method, **args)
        except Exception as e:  # tell the model, don't kill the answer
            return {"error": f"{name} failed: {type(e).__name__}"}


def emit_candidates(emit, result, limit=5):
    """Let the UI show what the search found right away, before the (slower) answer is written."""
    hits = result.get("hits") or []
    if hits:
        emit({"type": "candidates", "lessons": [{"id": h["id"], "title": h["title"]} for h in hits[:limit]]})


def for_model(result, signal, text_chars):
    """What the model needs from a search: less text and no scores, so each later call reads fewer tokens."""
    return {
        "signal": signal,
        "related_to": result.get("related_to", {}),
        "context_used": result.get("context_used", {}),
        # ambiguous words the search didn't map: the model can ask or pick one in a follow-up search
        "context_unresolved": result.get("context_unresolved", []),
        # a named project/supplier that wasn't found: several candidates -> ask which one; none -> say so
        "related_not_found": result.get("related_candidates", {}),
        "hits": [{"id": h["id"], "title": h["title"], "text": h["text"][:text_chars], "context": h["context"],
                  "reasons": h["reasons"]} for h in result["hits"]],
    }


def remember_hits(retrieved, hits):
    """Collect hits across searches; a later, better search improves rank and adds reasons."""
    top = max((h["similarity"] for h in hits), default=0)
    for rank, h in enumerate(hits, 1):
        old = retrieved.get(h["id"])
        if old is None:
            retrieved[h["id"]] = {**h, "rank": rank, "top_similarity": top}
            continue
        if rank < old["rank"]:
            old.update(rank=rank, top_similarity=top, score=h.get("score", old.get("score")),
                       similarity=max(old["similarity"], h["similarity"]))
        for r in h["reasons"]:
            if r not in old["reasons"]:
                old["reasons"].append(r)


def attach_lessons(answer, retrieved, min_similarity):
    # grounding checks switched off: still drop unknown IDs, since there's nothing to show for them
    kept = []
    for item in answer.get("lessons", []):
        lid = str(item.get("id", "")).strip()
        if lid in retrieved:
            hit = retrieved[lid]
            kept.append({**item, "id": lid, "title": hit["title"], "text": hit["text"], "context": hit["context"],
                         "confidence": confidence(hit, min_similarity)})
    return {**answer, "lessons": kept}


def cacheable(result):
    """Only full answers: never ones made without the evidence check or with errors."""
    return not result.get("degraded") and bool(result.get("answer"))


def decide(top, result):
    """Which graded lessons to keep: relevant ones (partial only to fill up to 3), or up to 3 partial ones
    as "related", or none. Returns {"result", "mode", "grades", "keep"}."""
    grades = {h["id"]: result["grades"].get(h["id"], "partial") for h in top}
    relevant = [h["id"] for h in top if grades[h["id"]] == "relevant"]
    partial = [h["id"] for h in top if grades[h["id"]] == "partial"]
    if relevant:
        keep, mode = relevant + partial[:max(0, 3 - len(relevant))], "answer"
    elif partial:
        keep, mode = partial[:3], "related_only"
    else:
        keep, mode = [], "none"
    return {"result": result, "mode": mode, "grades": grades, "keep": keep}


def apply_grades(retrieved, graded):
    for lid in list(retrieved):
        if lid in graded["keep"]:
            retrieved[lid]["grade"] = graded["grades"][lid]
        else:
            del retrieved[lid]


def cards_from_data(retrieved, ids):
    """Answer cards without the model: the start of the lesson text as the learning, reasons from the search."""
    from app.dataset import short_title
    return [{"id": lid, "learning": short_title(retrieved[lid]["text"], 200), "quote": "", "why_relevant": [],
             "problem_match": ""} for lid in ids if lid in retrieved]


def drop_ungraded(answer, retrieved):
    """With parallel grading the answer was written before the grades: drop what the check left out."""
    kept = [l for l in answer.get("lessons", []) if str(l.get("id", "")).strip() in retrieved]
    dropped = [str(l.get("id", "")).strip() for l in answer.get("lessons", []) if l not in kept]
    return {**answer, "lessons": kept}, dropped


def label_with_grades(answer, retrieved, graded, wording, summary_from_code=False):
    """Mark partial fits and what's missing in code, so the labels never depend on the model's prose."""
    for lesson in answer["lessons"]:
        grade = retrieved.get(lesson["id"], {}).get("grade")
        if grade == "partial":
            lesson["fit"] = "partial"
    missing = graded["result"].get("missing")
    if missing:
        answer["missing"] = missing
    if graded["mode"] == "related_only":
        answer["related_only"] = True
        for lesson in answer["lessons"]:
            lesson["confidence"] = "low"
    if summary_from_code and answer["lessons"]:
        # the model's summary may describe lessons we no longer show, so use a fixed text
        key = "related_only_text" if graded["mode"] == "related_only" else "filtered_summary_text"
        answer["summary"] = wording.get(key) or answer.get("summary", "")


def grader_question(question, history, trace):
    """The question plus what the grader needs to read a short follow-up like "Commissioning"."""
    earlier = [m["content"] for m in history or [] if m.get("role") == "user"][-2:]
    queries = [t["input"].get("query") for t in trace if t["tool"] == "search_lessons" and t["input"].get("query")]
    text = question
    if earlier:
        text += "\n(Earlier in the conversation: " + " / ".join(earlier) + ")"
    if queries:
        text += "\n(Searched for: " + " / ".join(queries) + ")"
    return text


def evidence_note(retrieved, graded):
    """Tell the answer model which lessons are left after the check (never ones the code removed)."""
    relevant = [lid for lid, h in retrieved.items() if h.get("grade") == "relevant"]
    partial = [lid for lid, h in retrieved.items() if h.get("grade") == "partial"]
    if graded["mode"] == "related_only":
        note = (f"Evidence check: no lesson matches the question directly. Related lessons: {', '.join(partial)}. "
                "Present them as related experience, not as a direct answer, and say so in the summary.")
    else:
        note = (f"Evidence check: directly relevant lessons: {', '.join(relevant)}; "
                f"partly relevant: {', '.join(partial) or 'none'}. Cite only these, best first; "
                "say clearly when a lesson only partly fits.")
    missing = graded["result"].get("missing")
    if missing:
        note += f" Not covered by any lesson: {missing} - say so."
    return note


def abstain_answer(graded, no_match_text):
    summary = no_match_text
    if graded.get("missing"):
        summary += f" Not covered: {graded['missing']}"
    return {"clarifying_question": "", "summary": summary, "next_step": graded.get("next_step", ""), "lessons": []}
