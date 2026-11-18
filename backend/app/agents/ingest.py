from app.agents.clients import EmbeddingProxy
from app.dataset import load_all, load_mapping
from app.index_files import store_for
from app.search.memory import build_index


class IngestAgent:
    name = "ingest"
    methods = ("ingest",)

    def __init__(self, settings, embedding_client, graph_client=None, source_client=None):
        self.settings = settings
        self.embedder = EmbeddingProxy(embedding_client)
        self.graph = graph_client
        self.source = source_client  # e.g. SPARQL source; None = CSV files from the mapping

    def ingest(self, dry_run=False, mapping=None):
        """`mapping` overrides the configured dataset mapping (used by the upload page)."""
        mapping = mapping or load_mapping(self.settings.dataset_config)
        fetch = (lambda table: self.source.call("fetch", table=table)["rows"]) if self.source else None
        lessons, items, report = load_all(mapping, fetch)
        counts = {}
        for item in items:
            counts[item.source] = counts.get(item.source, 0) + 1
        result = {
            "rows": report.rows,
            "loaded": report.loaded,
            "skipped": [{"id": rid, "reason": why} for rid, why in report.skipped],
            "unknown_links": {source: sorted(values) for source, values in report.unknown_links.items()},
            "context_items": counts,
            "version": None,
            "graph": None,
            "source": self.settings.data_source,
        }
        if dry_run:
            return result
        result["version"] = build_index(lessons, items, self.embedder, store_for(self.settings), mapping)
        if self.graph:
            # the graph mirrors the index; if it fails, the new index is still live and the old graph stays
            try:
                result["graph"] = self.graph.call("build")
            except Exception as e:
                result["graph"] = {"error": f"graph not rebuilt ({type(e).__name__}); it still shows the previous index"}
        return result
