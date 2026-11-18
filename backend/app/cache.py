"""A small in-process answer cache with a time limit and a size limit.

Each container (e.g. Fargate task) has its own; a short TTL keeps them roughly in step,
and a new index version changes the key, so stale answers are never served for new data.
"""
import copy
import hashlib
import json
import threading
import time
from collections import OrderedDict


class AnswerCache:
    def __init__(self, ttl_seconds=900, max_entries=500):
        self.ttl = ttl_seconds
        self.max_entries = max_entries
        self.entries = OrderedDict()  # key -> (stored_at, result)
        self.keys_by_id = {}
        self.lock = threading.Lock()

    def get(self, key):
        with self.lock:
            entry = self.entries.get(key)
            if entry is None:
                return None
            stored_at, result = entry
            if time.monotonic() - stored_at > self.ttl:
                self._remove(key)
                return None
            self.entries.move_to_end(key)
            return copy.deepcopy(result)

    def put(self, key, result):
        with self.lock:
            if key in self.entries:
                self._remove(key)  # also drops the old answer id, so forget(old_id) can't hit the new answer
            self.entries[key] = (time.monotonic(), copy.deepcopy(result))
            self.entries.move_to_end(key)
            if result.get("id"):
                self.keys_by_id[result["id"]] = key
            while len(self.entries) > self.max_entries:
                self._remove(next(iter(self.entries)))

    def forget(self, answer_id):
        """Drop the answer a user voted down, so the next ask builds a fresh one."""
        with self.lock:
            key = self.keys_by_id.get(answer_id)
            if key:
                self._remove(key)
            return key is not None

    def _remove(self, key):
        _, result = self.entries.pop(key, (None, {}))
        self.keys_by_id.pop((result or {}).get("id"), None)


def make_key(*parts):
    return hashlib.sha256(json.dumps(parts, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def normalize_question(text):
    return " ".join(text.lower().split()).rstrip("?!. ")
