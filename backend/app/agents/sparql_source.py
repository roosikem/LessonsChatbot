"""Source adapter for a knowledge graph behind a SPARQL 1.1 endpoint.

It only reads. The queries live in the dataset mapping, so pointing at another
graph means editing YAML, not code.
"""
from app.dataset import load_mapping
from app.sparql import SparqlClient, pivot


class SparqlSourceAgent:
    name = "sparql"
    methods = ("info", "ping", "fetch")

    def __init__(self, settings, client=None):
        self.settings = settings
        self.mapping = load_mapping(settings.dataset_config)
        self.client = client or SparqlClient(
            settings.sparql_endpoint,
            token=settings.sparql_token,
            user=settings.sparql_user,
            password=settings.sparql_password,
        )

    def info(self):
        tables = ["lessons"] + list(self.mapping.get("context_sources") or {})
        return {"endpoint": self.settings.sparql_endpoint, "tables": tables}

    def ping(self):
        return {"ok": self.client.ask()}

    def fetch(self, table):
        """table: "lessons" or the name of a context source."""
        m = self.mapping.get(table) if table == "lessons" else (self.mapping.get("context_sources") or {}).get(table)
        if not m or "sparql" not in m:
            raise ValueError(f"no SPARQL query configured for table {table!r}; check the SPARQL source mapping")
        rows = self.client.select(m["sparql"])
        if m.get("shape") == "key_value":
            rows = pivot(rows, sep=m.get("join", ";"))
        return {"table": table, "rows": rows}
