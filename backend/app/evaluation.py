"""Eval: does search find the labelled lessons, and does the chatbot answer with them?

Runs on its own copy of the data (the mapping in EVAL_DATASET) in data/eval, so uploads
and the dev index don't change the numbers. The questions come from EVAL_QUESTIONS.
"""
import json
import os
import time
from datetime import datetime
from pathlib import Path

import yaml

from app import agents
from app.dataset import load_all, load_mapping
from app.search.memory import build_index

# what each variant switches on; "context" also passes the ideal context/project from the question
VARIANTS = {
    "keyword": {"settings": {"feature_vector_search": False, "feature_context_boost": False}, "context": False},
    "vector": {"settings": {"feature_keyword_search": False, "feature_context_boost": False}, "context": False},
    "hybrid": {"settings": {"feature_context_boost": False}, "context": False},
    "hybrid+context": {"settings": {}, "context": True},
}


def eval_paths(settings):
    """The question set and its data mapping come from EVAL_QUESTIONS / EVAL_DATASET; they are not shipped."""
    if not (settings.eval_questions and settings.eval_dataset):
        raise SystemExit("set EVAL_QUESTIONS (questions YAML) and EVAL_DATASET (its dataset mapping) to run an eval")
    return settings.eval_questions, settings.eval_dataset


def load_questions(path):
    return yaml.safe_load(open(path, encoding="utf-8"))


def recall_at(ranked, expected, k):
    # capped: a question with 8 relevant lessons can still score 1.0 at k=5
    return len(set(ranked[:k]) & set(expected)) / min(k, len(expected))


def reciprocal_rank(ranked, expected):
    for i, lid in enumerate(ranked, 1):
        if lid in expected:
            return 1 / i
    return 0.0


RUN_ID = f"{datetime.now():%Y%m%d-%H%M%S}-{os.getpid()}"


def eval_settings(settings, **overrides):
    # each run gets its own folder, so two eval runs at the same time don't swap each other's index;
    # retrieval and graph always run in-process here, a remote service wouldn't have the eval index
    return settings.model_copy(update={
        "data_dir": Path(settings.data_dir) / "eval" / "runs" / RUN_ID,
        "dataset_config": eval_paths(settings)[1],
        "agent_retrieval_url": None,
        "agent_graph_url": None,
        "storage": "local",  # never write eval indexes to the shared S3 data
        "feature_answer_cache": False,  # every run must really answer
        "feedback_store": "file",
        **overrides,
    })


def build_eval_index(settings):
    """Index the eval dataset with the configured embedding model. Returns the embedding client."""
    s = eval_settings(settings)
    # the embedding cache lives in data/eval, shared between runs, so re-running costs nothing
    embedding = agents.embedding_client(settings.model_copy(update={"data_dir": Path(settings.data_dir) / "eval"}))
    mapping = load_mapping(s.dataset_config)
    lessons, items, _ = load_all(mapping)
    build_index(lessons, items, agents.embedder(s, embedding), s.data_dir, mapping)
    return embedding


def store_settings(settings, store, **overrides):
    if store == "neo4j":
        return eval_settings(settings, search_store="neo4j", feature_neo4j=True, **overrides)
    return eval_settings(settings, search_store="memory", **overrides)


def retrieval_client(settings, embedding, store, variant):
    return agents.retrieval_client(store_settings(settings, store, **VARIANTS[variant]["settings"]), embedding)


def build_eval_graph(settings, embedding):
    agents.graph_client(store_settings(settings, "neo4j"), embedding).call("build")


def restore_dev_graph(settings):
    # Community edition has one database: the eval graph replaced the dev graph, so rebuild it
    agents.graph_client(settings.model_copy(update={"feature_neo4j": True})).call("build")


def run_retrieval(settings, stores=("memory",), k=5, questions=None):
    questions = questions or load_questions(eval_paths(settings)[0])
    embedding = build_eval_index(settings)
    rows = []
    try:
        for store in stores:
            if store == "neo4j":
                build_eval_graph(settings, embedding)
            for variant, spec in VARIANTS.items():
                client = retrieval_client(settings, embedding, store, variant)
                for q in questions:
                    if "search" in q:
                        rows.append(score_search(client, q, spec, store, variant, k))
    finally:
        if "neo4j" in stores:
            restore_dev_graph(settings)
    return {"kind": "retrieval", "k": k, "embedding": f"{settings.embedding_provider}:{settings.embedding_model_id}",
            "rows": rows, "summary": summarize_retrieval(rows)}


def score_search(client, q, spec, store, variant, k):
    args = {"query": q["search"]["query"], "k": 10}
    if spec["context"]:
        args.update({key: q["search"][key] for key in ("context", "related_to") if key in q["search"]})
    hits = client.call("search", **args)["hits"]
    ranked = [h["id"] for h in hits]
    row = {"store": store, "variant": variant, "id": q["id"], "type": q["type"], "ranked": ranked[:k],
           "top_similarity": hits[0]["similarity"] if hits else 0.0}
    if q.get("expected"):
        row["recall"] = recall_at(ranked, q["expected"], k)
        row["mrr"] = reciprocal_rank(ranked, q["expected"])
        row["missed"] = [e for e in q["expected"][:k] if e not in ranked[:k]]
    return row


def summarize_retrieval(rows):
    out = {}
    for r in rows:
        key = f"{r['store']}/{r['variant']}"
        agg = out.setdefault(key, {"recall": [], "mrr": [], "answerable_sim": [], "no_answer_sim": []})
        if "recall" in r:
            agg["recall"].append(r["recall"])
            agg["mrr"].append(r["mrr"])
            agg["answerable_sim"].append(r["top_similarity"])
        elif r["type"] == "no_answer":
            agg["no_answer_sim"].append(r["top_similarity"])
    mean = lambda xs: round(sum(xs) / len(xs), 3) if xs else None
    return {key: {
        "recall@k": mean(a["recall"]),
        "mrr": mean(a["mrr"]),
        "questions": len(a["recall"]),
        # how well "nothing relevant" can be told apart from a real hit by similarity alone
        "lowest_answerable_sim": round(min(a["answerable_sim"]), 3) if a["answerable_sim"] else None,
        "highest_no_answer_sim": round(max(a["no_answer_sim"]), 3) if a["no_answer_sim"] else None,
    } for key, a in out.items()}


def run_answers(settings, store="memory", ids=None, limit=None, questions=None, llm=None):
    questions = questions or load_questions(eval_paths(settings)[0])
    if ids:
        questions = [q for q in questions if q["id"] in ids]
    if limit:
        questions = questions[:limit]
    embedding = build_eval_index(settings)
    rows = []
    try:
        if store == "neo4j":
            build_eval_graph(settings, embedding)
        retrieval = retrieval_client(settings, embedding, store, "hybrid+context")
        agent = agents.make_answer_agent(store_settings(settings, store), retrieval=retrieval, llm=llm)
        rows = [score_answer(agent, q) for q in questions]
    finally:
        if store == "neo4j":
            restore_dev_graph(settings)
    return {"kind": "answers", "store": store, "llm": f"{settings.llm_provider}:{settings.llm_model_id}",
            "features": {"evidence_grading": settings.feature_evidence_grading,
                         "grader": settings.grader_model_id or settings.llm_model_id,
                         "clarifying_questions": settings.feature_clarifying_questions,
                         "grounding_checks": settings.feature_grounding_checks},
            "embedding": f"{settings.embedding_provider}:{settings.embedding_model_id}",
            "rows": rows, "summary": summarize_answers(rows)}


def score_answer(agent, q):
    start = time.time()
    try:
        result, error = agent.ask(q["question"]), None
    except Exception as e:
        result, error = {"answer": {"lessons": []}, "issues": [], "trace": []}, f"{type(e).__name__}: {e}"
    a = result["answer"]
    cited = [l["id"] for l in a.get("lessons", [])]
    row = {"id": q["id"], "type": q["type"], "seconds": round(time.time() - start, 1), "cited": cited,
           "clarify": a.get("clarifying_question", ""), "issues": len(result["issues"]),
           "tools": [t["tool"] for t in result["trace"]], "error": error}
    row["passed"] = False  # a question without expected lessons or an expect rule can't pass
    if q.get("expected"):
        found = set(cited) & set(q["expected"])
        row["recall"] = min(1.0, len(found) / min(5, len(q["expected"])))
        row["precision"] = len(found) / len(cited) if cited else 0.0
        row["passed"] = row["recall"] >= 0.5
    elif q.get("expect") == "clarify":
        row["passed"] = bool(row["clarify"])
    elif q.get("expect") == "none":
        # passing: nothing cited, or lessons clearly shown as "related, not a direct match"
        row["passed"] = not cited or bool(a.get("related_only"))
    row["related_only"] = bool(a.get("related_only"))
    row["passed"] = row["passed"] and error is None  # a crash never counts as a pass
    return row


def summarize_answers(rows):
    def avg(values):
        values = list(values)
        return round(sum(values) / len(values), 3) if values else None

    by_type = {}
    for r in rows:
        by_type.setdefault(r["type"], []).append(r)
    scored = [r for r in rows if "recall" in r]
    return {
        "passed": f"{sum(r['passed'] for r in rows)}/{len(rows)}",
        "cited_recall": avg(r["recall"] for r in scored),
        "cited_precision": avg(r["precision"] for r in scored),
        "avg_seconds": avg(r["seconds"] for r in rows),
        "grounding_issues": sum(r["issues"] for r in rows),
        "errors": sum(1 for r in rows if r["error"]),
        "by_type": {t: f"{sum(r['passed'] for r in rs)}/{len(rs)}" for t, rs in by_type.items()},
    }


def save_report(result, data_dir):
    out = Path(data_dir) / "eval" / "reports"
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    base = out / f"{result['kind']}-{stamp}"
    base.with_suffix(".json").write_text(json.dumps(result, indent=2, ensure_ascii=False))
    base.with_suffix(".md").write_text(to_markdown(result))
    return base.with_suffix(".md")


def to_markdown(result):
    lines = [f"# Eval: {result['kind']} ({datetime.now():%Y-%m-%d %H:%M})", ""]
    if result["kind"] == "retrieval":
        lines += [f"Embedding: `{result['embedding']}`, k = {result['k']}", "",
                  "| store/variant | recall@k | MRR | lowest answerable sim | highest no-answer sim |",
                  "|---|---|---|---|---|"]
        for key, s in result["summary"].items():
            lines.append(f"| {key} | {s['recall@k']} | {s['mrr']} | {s['lowest_answerable_sim']} | {s['highest_no_answer_sim']} |")
        lines += ["", "## Misses (best variant per store)", ""]
        best = {}
        for key, s in result["summary"].items():
            store = key.split("/")[0]
            if store not in best or (s["recall@k"] or 0) > (result["summary"][best[store]]["recall@k"] or 0):
                best[store] = key
        for key in best.values():
            store, variant = key.split("/")
            for r in result["rows"]:
                if r["store"] == store and r["variant"] == variant and r.get("missed"):
                    lines.append(f"- {key} {r['id']} ({r['type']}): missed {r['missed']}, got {r['ranked']}")
    else:
        s = result["summary"]
        lines += [f"LLM: `{result['llm']}`, embedding: `{result['embedding']}`, store: {result['store']}",
                  f"Features: {result.get('features', {})}", "",
                  f"- passed: **{s['passed']}**",
                  f"- cited recall: {s['cited_recall']} · cited precision (vs labels): {s['cited_precision']}",
                  f"- avg seconds per answer: {s['avg_seconds']} · grounding issues removed: {s['grounding_issues']} · errors: {s['errors']}",
                  f"- by type: {s['by_type']}", "",
                  "| id | type | passed | cited | recall | issues | seconds | tools |", "|---|---|---|---|---|---|---|---|"]
        for r in result["rows"]:
            lines.append(f"| {r['id']} | {r['type']} | {'✅' if r['passed'] else '❌'} | {', '.join(r['cited']) or (r['clarify'][:40] + '…' if r['clarify'] else '-')} | "
                         f"{r.get('recall', '')} | {r['issues']} | {r['seconds']} | {' → '.join(r['tools'])} |")
    return "\n".join(lines) + "\n"
