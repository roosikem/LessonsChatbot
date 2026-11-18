"""Feedback votes: written by the API, read by search for the feedback boost.

Storage follows FEEDBACK_STORE: one JSON line per vote in data/feedback.jsonl, or one S3
object per vote (S3 can't append, and several containers would overwrite one file).
Each vote carries the embedding of its question (made when the vote is written), so search
never embeds old votes; S3 votes are loaded in the background, never inside a search.
The API and the search agents keep separate stores: S3 votes reach search after the poll interval.

Boost: a vote on a lesson counts for questions similar to the one it was given for
(cosine of the question embeddings), fades with age, and is squashed into -1..1, so a
few votes nudge the ranking but can't take it over. A thumbs-down never removes a lesson.
"""
import json
import math
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np


class FeedbackStore:
    def __init__(self, settings, index_store=None):
        self.settings = settings
        self.path = Path(settings.data_dir) / "feedback.jsonl"
        self.remote = index_store.remote if index_store is not None and settings.feedback_store == "s3" else None
        self.rows, self.loaded_at, self.last_key, self.refreshing = [], 0.0, None, False
        self.lock = threading.Lock()

    def write(self, row):
        now = datetime.now(timezone.utc)
        row = {**row, "at": now.isoformat()}
        if self.remote:
            self.remote.put_bytes(json.dumps(row, ensure_ascii=False).encode(),
                                  "feedback", f"{now:%Y-%m-%d}", f"{now:%H%M%S}-{time.time_ns() % 10**8:08d}.json")
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        return row

    def votes(self):
        """All votes so far. The local file is re-read when it changes; S3 is refreshed in the background."""
        if self.remote is None:
            with self.lock:
                mtime = self.path.stat().st_mtime if self.path.exists() else 0.0
                if mtime != self.loaded_at:
                    self._load_file()
                    self.loaded_at = mtime
                return list(self.rows)
        if time.monotonic() - self.loaded_at >= self.settings.index_poll_seconds and not self.refreshing:
            self.refreshing = True
            self.loaded_at = time.monotonic()
            threading.Thread(target=self._load_s3, daemon=True).start()
        return list(self.rows)

    def _load_file(self):
        if self.path.exists():
            with open(self.path, encoding="utf-8") as f:
                self.rows = [json.loads(line) for line in f if line.strip()]

    def _load_s3(self):
        try:
            for key in self.remote.list_keys("feedback", start_after=self.last_key):
                row = json.loads(self.remote.get_bytes_by_key(key))
                with self.lock:
                    self.rows = self.rows + [row]
                    self.last_key = key
        finally:
            self.refreshing = False


class FeedbackBoost:
    """Per-lesson feedback scores for a query, from votes on similar questions."""

    def __init__(self, store, embedder, settings):
        self.store = store
        self.embedder = embedder
        self.settings = settings
        self.vectors = {}  # question text -> embedding, for votes stored without one

    def scores(self, query_vector, today=None):
        """{lesson_id: (score -1..1, ups, downs)} for lessons with votes on similar questions."""
        votes = latest_per_voter(v for v in self.store.votes() if v.get("lesson_id") and v.get("question"))
        if not votes:
            return {}
        q = np.asarray(query_vector, dtype=np.float32)
        q = q / max(float(np.linalg.norm(q)), 1e-9)

        totals, counts = {}, {}
        now = today or datetime.now(timezone.utc)
        for v in votes:
            similarity = float(self._vector(v) @ q)
            if similarity < self.settings.feedback_min_similarity:
                continue  # a vote only counts for questions like the one it was given for
            sign = 1 if v.get("vote") == "up" else -1
            totals[v["lesson_id"]] = totals.get(v["lesson_id"], 0.0) + sign * similarity * self._decay(v, now)
            ups, downs = counts.get(v["lesson_id"], (0, 0))
            counts[v["lesson_id"]] = (ups + (sign > 0), downs + (sign < 0))
        return {lid: (math.tanh(total), *counts[lid]) for lid, total in totals.items()}

    def _vector(self, vote):
        # stored with the vote when the embedding model matches; otherwise embedded once and kept in memory
        if vote.get("question_vector") and vote.get("embedding_model") == self.embedder.model_id:
            v = np.asarray(vote["question_vector"], dtype=np.float32)
        else:
            if vote["question"] not in self.vectors:
                self.vectors[vote["question"]] = np.asarray(self.embedder.embed([vote["question"]], kind="query")[0],
                                                            dtype=np.float32)
            v = self.vectors[vote["question"]]
        return v / max(float(np.linalg.norm(v)), 1e-9)

    def _decay(self, vote, now):
        try:
            age_days = (now - datetime.fromisoformat(vote["at"])).total_seconds() / 86400
        except (KeyError, ValueError):
            return 1.0
        return 0.5 ** (max(age_days, 0) / self.settings.feedback_half_life_days)


def feedback_reason(ups, downs):
    """A reason for the answer card, only when users found the lesson helpful overall."""
    return ["feedback", ups, downs] if ups > downs else None


def latest_per_voter(votes):
    """One vote per voter, lesson and question: the latest counts, so nobody can stack votes."""
    latest = {}
    for v in votes:
        key = (v.get("voter") or "anonymous", v["lesson_id"], " ".join(v["question"].lower().split()))
        latest[key] = v
    return list(latest.values())
