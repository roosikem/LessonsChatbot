import hashlib
import json
import os
import urllib.request
from pathlib import Path

import numpy as np


class BedrockEmbedder:
    def __init__(self, model_id, profile=None, region="us-east-1", dim=1024, settings=None):
        from app.llm import bedrock_client
        self.client = bedrock_client(profile, region, settings)
        self.model_id = model_id
        self.dim = dim

    def embed(self, texts, kind="document"):
        if self.model_id.startswith("cohere.embed"):
            return self._cohere(texts, kind)
        return np.array([self._titan(t) for t in texts], dtype=np.float32)

    def _titan(self, text):
        body = {"inputText": text[:20000], "dimensions": self.dim, "normalize": True}
        resp = self.client.invoke_model(modelId=self.model_id, body=json.dumps(body))
        return json.loads(resp["body"].read())["embedding"]

    def _cohere(self, texts, kind):
        input_type = "search_query" if kind == "query" else "search_document"
        out = []
        for i in range(0, len(texts), 96):  # cohere takes max 96 texts per call
            body = {"texts": [t[:2000] for t in texts[i:i + 96]], "input_type": input_type}
            resp = self.client.invoke_model(modelId=self.model_id, body=json.dumps(body))
            out.extend(json.loads(resp["body"].read())["embeddings"])
        return np.array(out, dtype=np.float32)


class OllamaEmbedder:
    def __init__(self, model, url="http://localhost:11434"):
        self.model = model
        self.url = url.rstrip("/")
        self.model_id = f"ollama:{model}"

    def embed(self, texts, kind="document"):
        out = []
        for i in range(0, len(texts), 32):
            body = json.dumps({"model": self.model, "input": list(texts[i:i + 32])}).encode()
            req = urllib.request.Request(f"{self.url}/api/embed", data=body, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=300) as resp:
                out.extend(json.loads(resp.read())["embeddings"])
        return np.array(out, dtype=np.float32)


class HashEmbedder:
    """Offline stand-in for tests. Not semantic, only word overlap."""

    model_id = "local-hash"

    def __init__(self, dim=256):
        self.dim = dim

    def embed(self, texts, kind="document"):
        vecs = np.zeros((len(texts), self.dim), dtype=np.float32)
        for i, text in enumerate(texts):
            for word in text.lower().split():
                h = int(hashlib.md5(word.encode()).hexdigest(), 16)
                vecs[i, h % self.dim] += 1.0
        return vecs


class CachedEmbedder:
    """Keeps document embeddings on disk so re-ingesting doesn't pay twice."""

    def __init__(self, inner, cache_dir):
        self.inner = inner
        dim = getattr(inner, "dim", None)
        suffix = f"-{dim}" if dim else ""
        self.path = Path(cache_dir) / f"embeddings-{inner.model_id.replace(':', '_')}{suffix}.json"
        self.cache = json.loads(self.path.read_text()) if self.path.exists() else {}

    @property
    def model_id(self):
        return self.inner.model_id

    def embed(self, texts, kind="document"):
        if kind == "query":
            return self.inner.embed(texts, kind)
        keys = [hashlib.sha256(t.encode()).hexdigest() for t in texts]
        missing = [i for i, k in enumerate(keys) if k not in self.cache]
        if missing:
            new = self.inner.embed([texts[i] for i in missing], kind)
            for i, vec in zip(missing, new):
                self.cache[keys[i]] = vec.tolist()
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_name(f"{self.path.name}.{os.getpid()}.tmp")  # write, then rename: never half a file
            tmp.write_text(json.dumps(self.cache))
            os.replace(tmp, self.path)
        return np.array([self.cache[k] for k in keys], dtype=np.float32)


def make_embedder(settings):
    if settings.embedding_provider == "local":
        inner = HashEmbedder()
    elif settings.embedding_provider == "ollama":
        inner = OllamaEmbedder(settings.embedding_model_id, settings.ollama_url)
    else:
        inner = BedrockEmbedder(
            settings.embedding_model_id,
            profile=settings.bedrock_aws_profile,
            region=settings.bedrock_region,
            dim=settings.embedding_dim,
            settings=settings,
        )
    return CachedEmbedder(inner, settings.data_dir / "cache")
