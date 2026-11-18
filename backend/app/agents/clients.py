"""Client-side helpers for calling agents (local or over HTTP)."""
import numpy as np


class EmbeddingProxy:
    """Looks like an embedder, but goes through the embedding agent (local or remote)."""

    def __init__(self, client):
        self.client = client
        self._model_id = None

    @property
    def model_id(self):
        if self._model_id is None:
            self._model_id = self.client.call("info")["model_id"]
        return self._model_id

    def embed(self, texts, kind="document", batch=64):
        # batches keep each call (local or HTTP) well inside its timeout
        texts = list(texts)
        out = []
        for i in range(0, len(texts), batch):
            out.extend(self.client.call("embed", texts=texts[i:i + batch], kind=kind))
        return np.array(out, dtype=np.float32)
