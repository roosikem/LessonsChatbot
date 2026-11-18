from collections import Counter

from app import context as ctx
from app.agents.clients import EmbeddingProxy
from app.context_sources import comparable_result
from app.dataset import load_mapping
from app.feedback import FeedbackBoost, FeedbackStore
from app.index_files import store_for
from app.search.memory import MemoryStore


class RetrievalAgent:
    name = "retrieval"
    methods = ("search", "get_lesson", "resolve_context", "comparable_items", "count_by", "dimensions", "sources",
               "version")

    def __init__(self, settings, embedding_client, store=None):
        self.settings = settings
        self.embedder = EmbeddingProxy(embedding_client)
        self.mapping = load_mapping(settings.dataset_config)
        self.fixed_store = store is not None
        self.index = store_for(settings)
        self.feedback = (FeedbackBoost(FeedbackStore(settings, self.index), self.embedder, settings)
                         if settings.feature_feedback_boost else None)
        self._use(store or MemoryStore.load(self.index, self.embedder, settings, self.mapping))

    def _use(self, store):
        self.store = store
        self.by_id = {l.id: l for l in store.lessons}

    def _refresh(self):
        # pick up a newly published index (e.g. after an upload) without restarting
        if self.fixed_store:
            return
        version = self.index.current_version()
        if version and version != self.store.version:
            self._use(MemoryStore.load(self.index, self.embedder, self.settings, self.mapping))

    def version(self):
        """The index version being searched (part of the answer-cache key)."""
        self._refresh()
        return {"version": self.store.version}

    def sources(self):
        self._refresh()
        return self.store.sources.describe()

    def dimensions(self):
        self._refresh()
        values = {}
        for lesson in self.store.lessons:
            for dim, vals in lesson.context.items():
                values.setdefault(dim, set()).update(vals)
        return {dim: sorted(v) for dim, v in values.items()}

    def search(self, query, context=None, related_to=None, k=None):
        """related_to: {source: name or id}, e.g. {"project": "Valoria Metro Line 5"}."""
        self._refresh()
        targets = self.store.sources.resolve(related_to)
        context, aligned, unresolved = ctx.normalize(context), [], []
        if self.settings.feature_auto_resolve_context and context:
            context, aligned, unresolved = ctx.align(context, self.dimensions())
        hits = self.store.search(query, context, targets, k or self.settings.top_k_answer, self.feedback)
        return {
            "related_to": {source: item.name for source, item in targets.items()},
            "context_used": context,
            "context_mapped": aligned,
            "context_unresolved": unresolved,
            "unknown": sorted(set(related_to or {}) - set(targets)),
            "related_candidates": self.store.sources.not_found(related_to, targets),
            "hits": [{
                "id": h.lesson.id,
                "title": h.lesson.title,
                "text": h.lesson.text,
                "context": h.lesson.context,
                "signals": h.lesson.signals,
                "score": round(h.score, 3),
                "similarity": round(h.parts["vector"], 3),
                "reasons": [list(r) for r in h.reasons],
            } for h in hits],
        }

    def get_lesson(self, id):
        self._refresh()
        lesson = self.by_id.get(str(id))
        return lesson.to_dict() if lesson else {"error": f"no lesson {id}"}

    def resolve_context(self, term, dimension=None):
        return ctx.resolve(term, self.dimensions(), dimension)

    def comparable_items(self, source, name, limit=5):
        self._refresh()
        return comparable_result(self.store.sources, source, name, limit)

    def count_by(self, dimension, query=None):
        """Counts per value, over all lessons or over the hits for a query. For 'recurring issues'."""
        self._refresh()
        lessons = self.store.lessons
        if query:
            lessons = [h.lesson for h in self.store.search(query, k=self.settings.top_k_candidates)]
        counts = Counter(v for l in lessons for v in l.context.get(dimension, []))
        return {"dimension": dimension, "over": len(lessons), "counts": counts.most_common(15)}
