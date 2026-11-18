from app.embeddings import make_embedder


class EmbeddingAgent:
    name = "embedding"
    methods = ("info", "embed")

    def __init__(self, settings, embedder=None):
        self.embedder = embedder or make_embedder(settings)

    def info(self):
        return {"model_id": self.embedder.model_id}

    def embed(self, texts, kind="document"):
        return self.embedder.embed(texts, kind).tolist()
