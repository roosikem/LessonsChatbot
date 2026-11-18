"""Neo4j graph agent.

The graph is rebuilt from the current index (lessons, context items, vectors). Model:

  (:Lesson {id, title, text, ...})-[:HAS_CONTEXT]->(:Context {dimension, value})
  (:Lesson)-[:LINKED_TO]->(:ContextItem {source, id, name})-[:HAS_ATTR]->(:Attr {source, name, value})
  (:ContextItem)-[:REFERS_TO {column}]->(:ContextItem)      optional, from `references` in the mapping

Context values, context items and their attributes are generic nodes, so a new column
or a new context source is new nodes, not a schema change.
"""
import json

import numpy as np
from neo4j import GraphDatabase

from app import context as ctx
from app import ranking
from app.agents.clients import EmbeddingProxy
from app.context_sources import NEGATIVE, Sources, comparable_result
from app.dataset import ContextItem, Lesson
from app.feedback import FeedbackBoost, FeedbackStore, feedback_reason
from app.index_files import store_for
from app.search.fusion import fuse

VECTOR_INDEX = "lesson_embedding"
TEXT_INDEX = "lesson_text"
CHUNK = 500


class GraphAgent:
    name = "graph"
    methods = ("build", "stats", "search", "get_lesson", "related_lessons", "comparable_items",
               "count_by", "dimensions", "resolve_context", "sources", "version")

    def __init__(self, settings, embedding_client, driver=None):
        self.settings = settings
        self.db = settings.neo4j_database
        self.driver = driver or GraphDatabase.driver(
            settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password))
        self.embedder = EmbeddingProxy(embedding_client)
        self.feedback = (FeedbackBoost(FeedbackStore(settings, store_for(settings)), self.embedder, settings)
                         if settings.feature_feedback_boost else None)

    def _run(self, query, **params):
        records, _, _ = self.driver.execute_query(query, params, database_=self.db)
        return [r.data() for r in records]

    # --- build -------------------------------------------------------------

    def build(self):
        current = store_for(self.settings).read_current()
        meta, mapping = current["meta"], current["mapping"] or {}
        sources = Sources([ContextItem(**i) for i in current["items"]], mapping)
        vectors = current["vectors"]
        vectors = vectors / np.maximum(np.linalg.norm(vectors, axis=1, keepdims=True), 1e-9)

        item_rows = [{
            "source": i.source, "id": i.id, "name": i.name,
            "attrs_json": json.dumps(i.attrs, ensure_ascii=False),  # all columns, without clashing with id/name
            "attrs": [{"name": a, "value": i.attrs[a]} for a in sources.weights(i.source)
                      if i.attrs.get(a) and i.attrs[a].lower() not in NEGATIVE],
            "refs": [{"column": col, "source": target, "value": i.attrs.get(col, "")}
                     for col, target in (sources.config[i.source].get("references") or {}).items() if i.attrs.get(col)],
        } for name in sources.names() for i in sources.items[name]]

        lesson_rows = []
        for n, l in enumerate(current["lessons"]):
            linked, plain = [], []
            for dim, values in l["context"].items():
                source = next((s for s in sources.names() if sources.lesson_column(s) == dim), None)
                for v in values:
                    item = sources.by_key[source].get(v) if source else None
                    if item:
                        linked.append({"source": source, "id": item.id})
                    else:
                        plain.append({"dimension": dim, "value": v})  # unknown links stay as plain context
            lesson_rows.append({
                "id": l["id"], "title": l["title"], "text": l["text"],
                "signals_json": json.dumps(l.get("signals") or {}), "embedding": vectors[n].tolist(),
                "search_text": Lesson(**l).embed_text(),  # same text the memory store searches
                "context": plain, "linked": linked,
            })

        self._run("CREATE CONSTRAINT lesson_id IF NOT EXISTS FOR (l:Lesson) REQUIRE l.id IS UNIQUE")
        self._run("CREATE CONSTRAINT item_key IF NOT EXISTS FOR (i:ContextItem) REQUIRE (i.source, i.id) IS UNIQUE")
        # delete and reload in one transaction: if anything fails, the old graph stays
        with self.driver.session(database=self.db) as session:
            session.execute_write(self._load, item_rows, lesson_rows, meta, mapping)
        self._ensure_indexes(int(vectors.shape[1]))
        return {"version": meta["version"], **self.stats()}

    @staticmethod
    def _load(tx, item_rows, lesson_rows, meta, mapping):
        tx.run("MATCH (n) WHERE n:Lesson OR n:Context OR n:ContextItem OR n:Attr OR n:Meta DETACH DELETE n")
        for i in range(0, len(item_rows), CHUNK):
            tx.run("""
                UNWIND $rows AS row
                MERGE (x:ContextItem {source: row.source, id: row.id})
                SET x.name = row.name, x.attrs_json = row.attrs_json
                WITH x, row
                UNWIND row.attrs AS a
                MERGE (v:Attr {source: row.source, name: a.name, value: a.value})
                MERGE (x)-[:HAS_ATTR]->(v)
            """, rows=item_rows[i:i + CHUNK])
        for i in range(0, len(item_rows), CHUNK):
            tx.run("""
                UNWIND $rows AS row
                UNWIND row.refs AS r
                MATCH (x:ContextItem {source: row.source, id: row.id})
                MATCH (y:ContextItem {source: r.source}) WHERE y.id = r.value OR y.name = r.value
                MERGE (x)-[:REFERS_TO {column: r.column}]->(y)
            """, rows=item_rows[i:i + CHUNK])
        for i in range(0, len(lesson_rows), CHUNK):
            tx.run("""
                UNWIND $rows AS row
                MERGE (l:Lesson {id: row.id})
                SET l.title = row.title, l.text = row.text, l.signals_json = row.signals_json,
                    l.embedding = row.embedding, l.search_text = row.search_text
                WITH l, row
                CALL (l, row) {
                    UNWIND row.context AS c
                    MERGE (x:Context {dimension: c.dimension, value: c.value})
                    MERGE (l)-[:HAS_CONTEXT]->(x)
                }
                CALL (l, row) {
                    UNWIND row.linked AS k
                    MATCH (x:ContextItem {source: k.source, id: k.id})
                    MERGE (l)-[:LINKED_TO]->(x)
                }
            """, rows=lesson_rows[i:i + CHUNK])
        tx.run("CREATE (m:Meta {key: 'index'}) SET m.version = $v, m.embedding_model = $model, m.mapping = $mapping",
               v=meta["version"], model=meta["embedding_model"], mapping=json.dumps(mapping, ensure_ascii=False))

    def _ensure_indexes(self, dim):
        # recreate an index only when its settings change; otherwise it just follows the data
        existing = {r["name"]: r["options"] or {} for r in self._run(
            "SHOW INDEXES YIELD name, options WHERE name IN $names RETURN name, options",
            names=[VECTOR_INDEX, TEXT_INDEX])}
        config = existing.get(VECTOR_INDEX, {}).get("indexConfig", {})
        if VECTOR_INDEX in existing and config.get("vector.dimensions") != dim:
            self._run(f"DROP INDEX {VECTOR_INDEX}")
        config = existing.get(TEXT_INDEX, {}).get("indexConfig", {})
        if TEXT_INDEX in existing and config.get("fulltext.analyzer") != self.settings.neo4j_fulltext_analyzer:
            self._run(f"DROP INDEX {TEXT_INDEX}")
        self._run(f"""
            CREATE VECTOR INDEX {VECTOR_INDEX} IF NOT EXISTS FOR (l:Lesson) ON l.embedding
            OPTIONS {{indexConfig: {{`vector.dimensions`: {dim}, `vector.similarity_function`: 'cosine'}}}}
        """)
        self._run(f"CREATE FULLTEXT INDEX {TEXT_INDEX} IF NOT EXISTS FOR (l:Lesson) ON EACH [l.search_text] "
                  "OPTIONS {indexConfig: {`fulltext.analyzer`: $analyzer}}", analyzer=self.settings.neo4j_fulltext_analyzer)
        self._run("CALL db.awaitIndexes(120)")

    def stats(self):
        rows = self._run("""
            CALL () { MATCH (l:Lesson) RETURN count(l) AS lessons }
            CALL () { MATCH (i:ContextItem) RETURN count(i) AS context_items }
            CALL () { MATCH (c:Context) RETURN count(c) AS contexts }
            CALL () { MATCH (a:Attr) RETURN count(a) AS attrs }
            CALL () { MATCH ()-[r]->() RETURN count(r) AS relationships }
            CALL () { OPTIONAL MATCH (m:Meta {key: 'index'}) RETURN m.version AS version }
            RETURN version, lessons, context_items, contexts, attrs, relationships
        """)
        return rows[0]

    # --- reading back ------------------------------------------------------

    def _sources(self, with_mapping=False):
        """Context items (and the mapping) the graph was built with."""
        meta = self._run("MATCH (m:Meta {key: 'index'}) RETURN m.mapping AS mapping")
        mapping = json.loads(meta[0]["mapping"]) if meta and meta[0]["mapping"] else {}
        rows = self._run("MATCH (i:ContextItem) RETURN i.source AS source, i.id AS id, i.name AS name, "
                         "i.attrs_json AS attrs_json")
        items = [ContextItem(source=r["source"], id=r["id"], name=r["name"], attrs=json.loads(r["attrs_json"] or "{}"),
                             text="") for r in rows]
        sources = Sources(items, mapping)
        return (sources, mapping) if with_mapping else sources

    def _lesson_context(self, plain, linked, sources):
        """Rebuild a lesson's context dict, with linked items under their source's lesson column."""
        out = {}
        for dim, value in plain:
            if dim:
                out.setdefault(dim, []).append(value)
        for source, item_id, name in linked:
            if source in sources.config:
                key = item_id if sources.config[source].get("match_on") == "id" else name
                out.setdefault(sources.lesson_column(source), []).append(key)
        return {dim: sorted(values) for dim, values in out.items()}

    def sources(self):
        return self._sources().describe()

    def version(self):
        rows = self._run("MATCH (m:Meta {key: 'index'}) RETURN m.version AS version")
        return {"version": rows[0]["version"] if rows else None}

    # --- search ------------------------------------------------------------

    def search(self, query, context=None, related_to=None, k=None):
        s = self.settings
        k = k or s.top_k_answer
        n = s.top_k_candidates
        context, aligned, unresolved = ctx.normalize(context), [], []
        if s.feature_auto_resolve_context and context:
            context, aligned, unresolved = ctx.align(context, self.dimensions())
        meta = self._run("MATCH (m:Meta {key: 'index'}) RETURN m.embedding_model AS model")
        if meta and meta[0]["model"] != self.embedder.model_id:
            raise ValueError(f"graph was built with {meta[0]['model']}, embedder is {self.embedder.model_id}")

        q = self.embedder.embed([query], kind="query")[0]
        q = (q / max(np.linalg.norm(q), 1e-9)).tolist()
        vec = {}
        if s.feature_vector_search or not s.feature_keyword_search:
            vec = {r["id"]: r["score"] for r in self._run(
                f"CALL db.index.vector.queryNodes('{VECTOR_INDEX}', $n, $q) YIELD node, score "
                "RETURN node.id AS id, score", n=n, q=q)}
        kw = {}
        if s.feature_keyword_search:
            kw = {r["id"]: r["score"] for r in self._run(
                f"CALL db.index.fulltext.queryNodes('{TEXT_INDEX}', $q, {{limit: $n}}) YIELD node, score "
                "RETURN node.id AS id, score", q=lucene_escape(query), n=n)}

        ids = list(dict.fromkeys(list(vec) + list(kw)))
        if not ids:  # same shape as a normal result, so callers don't need a special case
            sources = self._sources()
            targets = sources.resolve(related_to)
            return {"related_to": {src: item.name for src, item in targets.items()},
                    "unknown": sorted(set(related_to or {}) - set(targets)),
                    "related_candidates": sources.not_found(related_to, targets), "context_used": context,
                    "context_mapped": aligned, "context_unresolved": unresolved, "hits": []}
        fused = fuse(np.array([vec.get(i, 0.0) for i in ids], dtype=np.float32),
                     np.array([kw.get(i, 0.0) for i in ids], dtype=np.float32), s)

        # cosine for every candidate, also keyword-only ones (Neo4j reports (1 + cos) / 2)
        lessons = {r["id"]: r for r in self._run("""
            MATCH (l:Lesson) WHERE l.id IN $ids
            OPTIONAL MATCH (l)-[:HAS_CONTEXT]->(c:Context)
            OPTIONAL MATCH (l)-[:LINKED_TO]->(i:ContextItem)
            RETURN l.id AS id, l.title AS title, l.text AS text, l.signals_json AS signals_json,
                   2 * vector.similarity.cosine(l.embedding, $q) - 1 AS similarity,
                   collect(DISTINCT [c.dimension, c.value]) AS plain,
                   collect(DISTINCT [i.source, i.id, i.name]) AS linked
        """, ids=ids, q=q)}

        votes = self.feedback.scores(q) if self.feedback else {}
        sources, mapping = self._sources(with_mapping=True)
        signals = ranking.config(mapping)
        targets = sources.resolve(related_to)
        hits = []
        for n_, lid in enumerate(ids):
            l = lessons[lid]
            lesson_ctx = self._lesson_context(l["plain"], [x for x in l["linked"] if x[0]], sources)
            ctx_matches = ctx.matches(lesson_ctx, context) if s.feature_context_boost else []
            reasons = [["context_match", dim, value] for dim, value in ctx_matches]
            rel_score, rel_reasons = sources.boost(lesson_ctx, targets)
            reasons += [list(r) for r in rel_reasons]
            values = json.loads(l["signals_json"] or "{}")
            fb_score, ups, downs = votes.get(lid, (0.0, 0, 0))
            if (reason := feedback_reason(ups, downs)):
                reasons.append(reason)
            score = (fused[n_] + s.score_w_context * len(ctx_matches) + s.score_w_related * rel_score
                     + ranking.score(values, signals) + s.score_w_feedback * fb_score)
            hits.append({"id": lid, "title": l["title"], "text": l["text"], "context": lesson_ctx,
                         "signals": values, "score": round(float(score), 3),
                         "similarity": round(l["similarity"] or 0.0, 3), "reasons": reasons})

        hits.sort(key=lambda h: h["score"], reverse=True)
        return {"related_to": {src: item.name for src, item in targets.items()},
                "unknown": sorted(set(related_to or {}) - set(targets)),
                "related_candidates": sources.not_found(related_to, targets),
                "context_used": context, "context_mapped": aligned, "context_unresolved": unresolved,
                "hits": hits[:k]}

    # --- graph questions -----------------------------------------------------

    def get_lesson(self, id):
        rows = self._run("""
            MATCH (l:Lesson {id: $id})
            OPTIONAL MATCH (l)-[:HAS_CONTEXT]->(c:Context)
            OPTIONAL MATCH (l)-[:LINKED_TO]->(i:ContextItem)
            RETURN l {.id, .title, .text} AS lesson, l.signals_json AS signals_json,
                   collect(DISTINCT [c.dimension, c.value]) AS plain,
                   collect(DISTINCT [i.source, i.id, i.name]) AS linked
        """, id=str(id))
        if not rows:
            return {"error": f"no lesson {id}"}
        r = rows[0]
        return {**r["lesson"], "signals": json.loads(r["signals_json"] or "{}"),
                "context": self._lesson_context(r["plain"], [x for x in r["linked"] if x[0]], self._sources())}

    def related_lessons(self, id, limit=5):
        """Lessons connected through shared context values, the same context item, or comparable items."""
        rows = self._run("""
            MATCH (l:Lesson {id: $id})
            CALL (l) {
                // a value shared by few lessons says more than one everybody has
                MATCH (l)-[:HAS_CONTEXT]->(c:Context)<-[:HAS_CONTEXT]-(o:Lesson)
                RETURN o, 'shared ' + c.dimension + ': ' + c.value AS why,
                       3.0 / COUNT { (:Lesson)-[:HAS_CONTEXT]->(c) } AS w
                UNION ALL
                MATCH (l)-[:LINKED_TO]->(i:ContextItem)<-[:LINKED_TO]-(o:Lesson)
                RETURN o, 'same ' + i.source + ': ' + i.name AS why, 2.0 AS w
                UNION ALL
                // comparable items count at most 1.0, so they never outweigh the same item
                MATCH (l)-[:LINKED_TO]->(i:ContextItem)-[:HAS_ATTR]->(a:Attr)<-[:HAS_ATTR]-(j:ContextItem)<-[:LINKED_TO]-(o:Lesson)
                WHERE i <> j
                WITH o, i, j, count(DISTINCT a) AS shared, COUNT { (i)-[:HAS_ATTR]->() } AS total
                RETURN o, 'comparable ' + i.source + ': ' + j.name AS why, toFloat(shared) / total AS w
            }
            WITH o, why, w ORDER BY w DESC
            WITH o, sum(w) AS weight, collect(DISTINCT why)[..4] AS why
            WHERE o.id <> $id
            RETURN o.id AS id, o.title AS title, round(weight, 2) AS weight, why
            ORDER BY weight DESC LIMIT $limit
        """, id=str(id), limit=limit)
        return {"id": str(id), "related": rows}

    def comparable_items(self, source, name, limit=5):
        return comparable_result(self._sources(), source, name, limit)

    def count_by(self, dimension, query=None):
        ids = [h["id"] for h in self.search(query, k=self.settings.top_k_candidates)["hits"]] if query else None
        sources = self._sources()
        source = next((s for s in sources.names() if sources.lesson_column(s) == dimension), None)
        if source:
            rows = self._run("""
                MATCH (l:Lesson)-[:LINKED_TO]->(i:ContextItem {source: $source}) WHERE $ids IS NULL OR l.id IN $ids
                RETURN i.name AS value, count(l) AS n ORDER BY n DESC LIMIT 15
            """, source=source, ids=ids)
        else:
            rows = self._run("""
                MATCH (l:Lesson)-[:HAS_CONTEXT]->(c:Context {dimension: $dim}) WHERE $ids IS NULL OR l.id IN $ids
                RETURN c.value AS value, count(l) AS n ORDER BY n DESC LIMIT 15
            """, dim=dimension, ids=ids)
        return {"dimension": dimension, "counts": [[r["value"], r["n"]] for r in rows]}

    def dimensions(self):
        rows = self._run("MATCH (c:Context) RETURN c.dimension AS dim, collect(DISTINCT c.value) AS values")
        out = {r["dim"]: sorted(r["values"]) for r in rows}
        sources = self._sources()
        for source in sources.names():
            key = "id" if sources.config[source].get("match_on") == "id" else "name"
            values = self._run(f"MATCH (:Lesson)-[:LINKED_TO]->(i:ContextItem {{source: $source}}) "
                               f"RETURN DISTINCT i.{key} AS v", source=source)
            column = sources.lesson_column(source)
            out[column] = sorted(set(out.get(column, [])) | {r["v"] for r in values})
        return out

    def resolve_context(self, term, dimension=None):
        return ctx.resolve(term, self.dimensions(), dimension)

    def close(self):
        self.driver.close()


def lucene_escape(text):
    # lowercase first: Lucene only treats upper-case AND / OR / NOT as operators
    special = '+-&|!(){}[]^"~*?:\\/'
    return "".join("\\" + ch if ch in special else ch for ch in text.lower())
