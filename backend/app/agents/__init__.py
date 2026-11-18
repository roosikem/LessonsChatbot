"""Wiring: build each agent in-process, or point at it over HTTP when its URL is set.

Code outside this package uses only these functions, never the agent modules directly.
"""
from app.agents.transport import HttpClient, LocalClient, make_server


def embedding_client(settings):
    if settings.agent_embedding_url:
        return HttpClient("embedding", settings.agent_embedding_url)
    from app.agents.embedding import EmbeddingAgent
    return LocalClient(EmbeddingAgent(settings))


def embedder(settings, embedding=None):
    """Something with .embed() / .model_id that goes through the embedding agent, e.g. for build_index."""
    from app.agents.clients import EmbeddingProxy
    return EmbeddingProxy(embedding or embedding_client(settings))


def graph_client(settings, embedding=None):
    if not settings.feature_neo4j:
        return None
    if settings.agent_graph_url:
        return HttpClient("graph", settings.agent_graph_url)
    from app.agents.graph import GraphAgent
    return LocalClient(GraphAgent(settings, embedding or embedding_client(settings)))


def retrieval_client(settings, embedding=None):
    # with SEARCH_STORE=neo4j the graph agent answers the retrieval calls
    if settings.search_store == "neo4j":
        return graph_client(settings, embedding)
    if settings.agent_retrieval_url:
        return HttpClient("retrieval", settings.agent_retrieval_url)
    from app.agents.retrieval import RetrievalAgent
    return LocalClient(RetrievalAgent(settings, embedding or embedding_client(settings)))


def sparql_client(settings):
    if settings.data_source != "sparql":
        return None
    if settings.agent_sparql_url:
        return HttpClient("sparql", settings.agent_sparql_url)
    from app.agents.sparql_source import SparqlSourceAgent
    return LocalClient(SparqlSourceAgent(settings))


def grader_client(settings):
    if not settings.feature_evidence_grading:
        return None
    if settings.agent_grader_url:
        return HttpClient("grader", settings.agent_grader_url)
    from app.agents.grader import GraderAgent
    return LocalClient(GraderAgent(settings))


def make_ingest_agent(settings):
    from app.agents.ingest import IngestAgent
    embedding = embedding_client(settings)
    return IngestAgent(settings, embedding, graph_client(settings, embedding), sparql_client(settings))


def make_answer_agent(settings, retrieval=None, graph=None, llm=None):
    from app.agents.answer import AnswerAgent
    from app.llm import make_llm
    if retrieval is None:
        embedding = embedding_client(settings)
        retrieval = retrieval_client(settings, embedding)
        graph = retrieval if settings.search_store == "neo4j" else graph_client(settings, embedding)
    return AnswerAgent(settings, llm or make_llm(settings), retrieval, graph, grader_client(settings))


SERVABLE = ("embedding", "retrieval", "graph", "sparql", "grader")


def make_agent(name, settings):
    """An agent object by name, to run it as its own service."""
    if name == "embedding":
        from app.agents.embedding import EmbeddingAgent
        return EmbeddingAgent(settings)
    if name == "retrieval":
        from app.agents.retrieval import RetrievalAgent
        return RetrievalAgent(settings, embedding_client(settings))
    if name == "graph":
        from app.agents.graph import GraphAgent
        return GraphAgent(settings, embedding_client(settings))
    if name == "sparql":
        from app.agents.sparql_source import SparqlSourceAgent
        return SparqlSourceAgent(settings)
    if name == "grader":
        from app.agents.grader import GraderAgent
        return GraderAgent(settings)
    raise ValueError(f"unknown agent {name}; choose from {', '.join(SERVABLE)}")


def serve(name, settings, host="127.0.0.1", port=8100):
    """An HTTP server for one agent (call .serve_forever() on it)."""
    return make_server(make_agent(name, settings), host, port)
