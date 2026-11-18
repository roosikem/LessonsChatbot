"""Deployment wording and word lists from config/assistant.yaml (see that file)."""
import hashlib
from functools import lru_cache

import yaml


@lru_cache
def load(path):
    with open(path, encoding="utf-8") as f:
        raw = f.read()
    cfg = yaml.safe_load(raw) or {}
    cfg["hash"] = hashlib.sha256(raw.encode()).hexdigest()[:16]  # part of the answer-cache key
    cfg["filler_words"] = set(str(cfg.get("filler_words", "")).split())
    cfg["stopwords"] = set(str(cfg.get("stopwords", "")).split())
    cfg.setdefault("examples", [])
    cfg.setdefault("personal_column_hints", [])
    cfg.setdefault("keep_status_values", [])
    return cfg


DEFAULT_NAME = "Talk to Lessons Learned"


def for_settings(settings):
    cfg = load(str(settings.assistant_config))
    # APP_NAME in .env wins over app_name in the YAML, so a deployment can rename the app without editing files
    name = settings.app_name or cfg.get("app_name") or DEFAULT_NAME
    return {**cfg, "app_name": name}


def public(cfg):
    """What the browser needs."""
    return {key: cfg.get(key) for key in ("app_name", "tagline", "placeholder", "examples", "keep_status_values",
                                          "related_only_text")}
