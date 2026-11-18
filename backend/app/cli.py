import argparse
import json
import sys

from app import agents
from app.settings import get_settings


def cmd_ingest(args, settings):
    result = agents.make_ingest_agent(settings).ingest(dry_run=args.dry_run)
    print(f"source: {result['source']}  rows: {result['rows']}, loaded: {result['loaded']}, skipped: {len(result['skipped'])}")
    for s in result["skipped"]:
        print(f"  skipped {s['id']}: {s['reason']}")
    for source, values in result["unknown_links"].items():
        print(f"  lessons point to unknown {source}: {values}")
    if result["version"]:
        items = ", ".join(f"{n} {source}" for source, n in result["context_items"].items()) or "no context sources"
        print(f"index {result['version']}: {result['loaded']} lessons; {items}")
    if result.get("graph"):
        print(f"graph: {result['graph']}")


def cmd_graph(args, settings):
    graph = agents.graph_client(settings)
    if graph is None:
        sys.exit("FEATURE_NEO4J is off")
    if args.action == "build":
        print(graph.call("build"))
    elif args.action == "stats":
        print(graph.call("stats"))
    elif args.action == "related":
        if not args.id:
            sys.exit("usage: graph related <lesson id>")
        for r in graph.call("related_lessons", id=args.id)["related"]:
            print(f"  {r['weight']:.1f}  [{r['id']}] {r['title']}")
            for why in r["why"]:
                print(f"        {why}")


def parse_context(pairs):
    context = {}
    for pair in pairs or []:
        dim, _, value = pair.partition("=")
        context.setdefault(dim.strip(), []).append(value.strip())
    return context


def cmd_search(args, settings):
    retrieval = agents.retrieval_client(settings)
    related = parse_context(args.related)
    related = {source: values[0] for source, values in related.items()}
    for source, name in related.items():
        cmp = retrieval.call("comparable_items", source=source, name=name)
        if "error" in cmp:
            sys.exit(cmp["error"])
        print(f"comparable to {source} {cmp['item']}:")
        for c in cmp["comparable"]:
            print(f"  {c['score']:.2f}  {c['name']}  {c['shared']}")
        print()
    result = retrieval.call("search", query=args.query, context=parse_context(args.context),
                            related_to=related, k=args.k)
    for h in result["hits"]:
        print(f"{h['score']:.3f}  [{h['id']}] {h['title']}")
        shown = "  ".join(f"{dim}={', '.join(vals)}" for dim, vals in list(h["context"].items())[:4] if vals)
        print(f"       {shown}")
        for r in h["reasons"]:
            print(f"       why: {r}")


def cmd_ask(args, settings):
    result = agents.make_answer_agent(settings).ask(args.question)
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return
    a = result["answer"]
    if a.get("clarifying_question"):
        print(f"? {a['clarifying_question']}")
    print(a.get("summary", ""))
    for l in a["lessons"]:
        print(f"\n[{l['id']}] {l['title']}  ({l['confidence']})")
        print(f"  {l['learning']}")
        for r in l["why_relevant"]:
            dim = f"{r.get('dimension')}=" if r.get("dimension") else ""
            print(f"  why: {r['type']} {dim}{r['value']}")
        if l["quote"]:
            print(f"  \"{l['quote']}\"")
    if result["not_found"]:
        print("\n(no matching lessons)")
    if args.trace:
        print("\ntools:", *[f"  {t}" for t in result["trace"]], sep="\n")
        print("checks:", *[f"  {i}" for i in result["issues"]] or ["  ok"], sep="\n")


def cmd_eval(args, settings):
    from app import evaluation
    if args.kind == "retrieval":
        stores = ["memory", "neo4j"] if args.store == "both" else [args.store]
        result = evaluation.run_retrieval(settings, stores, k=args.k)
        for key, s in result["summary"].items():
            if s["recall@k"] is None:
                print(f"{key:24} no labelled questions")
                continue
            print(f"{key:24} recall@{args.k}={s['recall@k']:.3f}  mrr={s['mrr']:.3f}  "
                  f"sim: lowest answerable={s['lowest_answerable_sim']}  highest no-answer={s['highest_no_answer_sim']}")
    else:
        if args.store == "both":
            sys.exit("eval answers runs on one store: --store memory or --store neo4j")
        ids = args.ids.split(",") if args.ids else None
        result = evaluation.run_answers(settings, args.store, ids=ids, limit=args.limit)
        for r in result["rows"]:
            print(f"{r['id']} {r['type']:10} {'PASS' if r['passed'] else 'FAIL'}  cited={r['cited']}  "
                  f"recall={r.get('recall', '-')}  {r['seconds']}s  {r['error'] or ''}")
        print(result["summary"])
    print(f"report: {evaluation.save_report(result, settings.data_dir)}")


def cmd_bench(args, settings):
    """Ask the same question n times; median seconds and tokens per step (answer cache must be off)."""
    import statistics
    import time
    agent = agents.make_answer_agent(settings.model_copy(update={"feature_answer_cache": False}))
    totals, steps = [], {}
    for _ in range(args.n):
        start = time.time()
        result = agent.ask(args.question)
        totals.append(time.time() - start)
        for t in result.get("timings", []):
            row = steps.setdefault(t["step"], {"seconds": [], "output_tokens": [], "input_tokens": [], "count": 0})
            row["count"] += 1
            for key in ("seconds", "output_tokens", "input_tokens"):
                if t.get(key) is not None:
                    row[key].append(t[key])
    med = lambda xs: statistics.median(xs) if xs else 0
    print(f"{args.question[:70]}\n  total: median {med(totals):.1f}s (min {min(totals):.1f}, max {max(totals):.1f}) over {args.n} runs")
    for step, row in steps.items():
        print(f"  {step:13} {row['count'] / args.n:.1f}x per answer  median {med(row['seconds']):.2f}s  "
              f"in {med(row['input_tokens']):.0f} tok  out {med(row['output_tokens']):.0f} tok")


def cmd_serve(args, settings):
    server = agents.serve(args.agent, settings, args.host, args.port)
    print(f"{args.agent} agent on http://{args.host}:{args.port}")
    server.serve_forever()


def main(argv=None):
    parser = argparse.ArgumentParser(prog="lessons")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("ingest", help="load the dataset and build a new index")
    p.add_argument("--dry-run", action="store_true")

    p = sub.add_parser("search", help="search the current index")
    p.add_argument("query")
    p.add_argument("--context", "-c", action="append", help="dim=value, e.g. stage=Commissioning")
    p.add_argument("--related", "-r", action="append", help="source=name, e.g. project=Valoria Metro Line 5")
    p.add_argument("-k", type=int, default=5)

    p = sub.add_parser("ask", help="ask the chatbot")
    p.add_argument("question")
    p.add_argument("--trace", action="store_true", help="show tool calls and check results")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("graph", help="Neo4j graph: build, stats, related <id>")
    p.add_argument("action", choices=["build", "stats", "related"])
    p.add_argument("id", nargs="?")

    p = sub.add_parser("eval", help="score retrieval or full answers against the question set in EVAL_QUESTIONS")
    p.add_argument("kind", choices=["retrieval", "answers"])
    p.add_argument("--store", choices=["memory", "neo4j", "both"], default="memory",
                   help="answers: memory or neo4j (both only for retrieval)")
    p.add_argument("-k", type=int, default=5)
    p.add_argument("--ids", help="comma-separated question ids, e.g. q01,q05")
    p.add_argument("--limit", type=int)

    p = sub.add_parser("bench", help="median latency and tokens per step for one question")
    p.add_argument("question")
    p.add_argument("-n", type=int, default=5, choices=range(1, 51), metavar="1..50")

    p = sub.add_parser("serve", help="run one agent as its own HTTP service")
    p.add_argument("agent", choices=agents.SERVABLE)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8100)

    args = parser.parse_args(argv)
    settings = get_settings()
    {"ingest": cmd_ingest, "search": cmd_search, "ask": cmd_ask, "graph": cmd_graph, "eval": cmd_eval, "bench": cmd_bench, "serve": cmd_serve}[args.cmd](args, settings)


if __name__ == "__main__":
    main()
