import json
import math
import re
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np

from app import assistant, ranking
from app import context as ctx
from app.context_sources import Sources
from app.dataset import ContextItem, Lesson
from app.feedback import feedback_reason
from app.index_files import as_store
from app.search.fusion import fuse

def tokenize(text, stopwords=frozenset()):
    return [w for w in re.findall(r"\w+", text.lower()) if w not in stopwords and len(w) > 1]


class BM25:
    def __init__(self, docs, stopwords=frozenset(), k1=1.5, b=0.75):
        self.k1, self.b = k1, b
        self.stopwords = stopwords
        self.docs = [Counter(tokenize(d, stopwords)) for d in docs]
        self.lengths = [sum(d.values()) for d in self.docs]
        self.avg_len = (sum(self.lengths) / len(self.lengths)) if self.docs else 0
        df = Counter(term for d in self.docs for term in d)
        n = len(self.docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def scores(self, query):
        terms = tokenize(query, self.stopwords)
        out = np.zeros(len(self.docs), dtype=np.float32)
        for i, (doc, length) in enumerate(zip(self.docs, self.lengths)):
            for t in terms:
                tf = doc.get(t, 0)
                if tf:
                    norm = tf * (self.k1 + 1) / (tf + self.k1 * (1 - self.b + self.b * length / self.avg_len))
                    out[i] += self.idf[t] * norm
        return out


@dataclass
class Hit:
    lesson: Lesson
    score: float
    reasons: list = field(default_factory=list)
    parts: dict = field(default_factory=dict)


def build_index(lessons, items, embedder, target, mapping=None):
    """target: an IndexStore (local or S3-mirrored) or a plain data folder."""
    store = as_store(target)
    if not lessons:
        # publishing an empty index would break every search; keep the old one live
        raise ValueError("no lessons loaded; check the id / text columns and filters")
    version = datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4]
    out = store.new_version_dir(version)
    vectors = embedder.embed([l.embed_text() for l in lessons], kind="document")
    np.save(out / "vectors.npy", vectors)
    with open(out / "lessons.jsonl", "w", encoding="utf-8") as f:
        for l in lessons:
            f.write(json.dumps(l.to_dict(), ensure_ascii=False) + "\n")
    with open(out / "context_items.jsonl", "w", encoding="utf-8") as f:
        for item in items:
            f.write(json.dumps(item.to_dict(), ensure_ascii=False) + "\n")
    counts = {}
    for item in items:
        counts[item.source] = counts.get(item.source, 0) + 1
    meta = {"version": version, "embedding_model": embedder.model_id, "lessons": len(lessons), "context_items": counts}
    (out / "meta.json").write_text(json.dumps(meta, indent=2))
    if mapping:
        (out / "mapping.json").write_text(json.dumps(mapping, indent=2, ensure_ascii=False))
    store.publish(version)
    return version


class MemoryStore:
    def __init__(self, lessons, items, vectors, embedder, settings, mapping):
        self.lessons = lessons
        self.sources = Sources(items, mapping)
        self.signals = ranking.config(mapping)
        self.vectors = vectors / np.maximum(np.linalg.norm(vectors, axis=1, keepdims=True), 1e-9)
        self.embedder = embedder
        self.settings = settings
        self.bm25 = BM25([l.embed_text() for l in lessons], assistant.for_settings(settings)["stopwords"])
        self.version = None

    @classmethod
    def load(cls, target, embedder, settings, mapping):
        current = as_store(target).read_current()
        meta = current["meta"]
        if meta["embedding_model"] != embedder.model_id:
            raise ValueError(f"index was built with {meta['embedding_model']}, embedder is {embedder.model_id}")
        # the mapping the index was built with knows its context sources; fall back to the configured one
        store = cls([Lesson(**l) for l in current["lessons"]], [ContextItem(**i) for i in current["items"]],
                    current["vectors"], embedder, settings, current["mapping"] or mapping)
        store.version = meta["version"]
        return store

    def search(self, query, context=None, related_to=None, k=None, feedback=None):
        """related_to: {source: ContextItem} to boost lessons linked to the same or comparable items.
        feedback: a FeedbackBoost (optional)."""
        s = self.settings
        k = k or s.top_k_candidates
        q = self.embedder.embed([query], kind="query")[0]
        q = q / max(np.linalg.norm(q), 1e-9)
        vec_scores = self.vectors @ q
        kw_scores = self.bm25.scores(query) if s.feature_keyword_search else np.zeros_like(vec_scores)
        base = fuse(vec_scores, kw_scores, s)
        votes = feedback.scores(q) if feedback else {}

        hits = []
        for i, lesson in enumerate(self.lessons):
            ctx_matches = ctx.matches(lesson.context, context) if s.feature_context_boost else []
            reasons = [("context_match", dim, value) for dim, value in ctx_matches]
            rel_score, rel_reasons = self.sources.boost(lesson.context, related_to)
            reasons += rel_reasons

            signal_score = ranking.score(lesson.signals, self.signals)
            fb_score, ups, downs = votes.get(lesson.id, (0.0, 0, 0))
            if (reason := feedback_reason(ups, downs)):
                reasons.append(reason)
            score = (base[i] + s.score_w_context * len(ctx_matches)
                     + s.score_w_related * rel_score + signal_score + s.score_w_feedback * fb_score)
            parts = {"vector": float(vec_scores[i]), "keyword": float(kw_scores[i]), "fused": float(base[i]),
                     "context_matches": len(ctx_matches), "related": round(rel_score, 3),
                     "signals": round(signal_score, 3), "feedback": round(fb_score, 3)}
            hits.append(Hit(lesson, float(score), reasons, parts))

        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:k]
