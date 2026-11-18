import base64
import json
import urllib.error
import urllib.parse
import urllib.request


class SparqlError(Exception):
    pass


class SparqlClient:
    """Minimal SPARQL 1.1 protocol client (SELECT / ASK over HTTP POST)."""

    def __init__(self, endpoint, token=None, user=None, password=None, timeout=120):
        self.endpoint = endpoint
        self.timeout = timeout
        self.headers = {"Accept": "application/sparql-results+json",
                        "Content-Type": "application/x-www-form-urlencoded"}
        if token:
            self.headers["Authorization"] = f"Bearer {token}"
        elif user:
            creds = base64.b64encode(f"{user}:{password or ''}".encode()).decode()
            self.headers["Authorization"] = f"Basic {creds}"

    def _post(self, query):
        data = urllib.parse.urlencode({"query": query}).encode()
        req = urllib.request.Request(self.endpoint, data=data, headers=self.headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = resp.read()
            return json.loads(body)
        except json.JSONDecodeError as e:  # e.g. an HTML login page instead of SPARQL results
            raise SparqlError(f"{self.endpoint} did not return SPARQL JSON: {body[:200]!r}") from e
        except urllib.error.HTTPError as e:
            raise SparqlError(f"{e.code} from {self.endpoint}: {e.read().decode()[:300]}") from e
        except (urllib.error.URLError, TimeoutError) as e:  # not reachable, DNS, TLS, timeout
            raise SparqlError(f"cannot reach {self.endpoint}: {getattr(e, 'reason', e)}") from e

    def select(self, query):
        body = self._post(query)
        names = body["head"]["vars"]
        return [{n: b[n]["value"] if n in b else "" for n in names} for b in body["results"]["bindings"]]

    def ask(self, query="ASK { ?s ?p ?o }"):
        return bool(self._post(query)["boolean"])


def pivot(rows, subject="subject", key="key", value="value", sep=";"):
    """(subject, key, value) rows -> one dict per subject. Repeated keys are joined with `sep`."""
    out = {}
    for r in rows:
        record = out.setdefault(r[subject], {})
        if r[key] in record and r[value] not in record[r[key]].split(sep):
            record[r[key]] += sep + r[value]
        else:
            record.setdefault(r[key], r[value])
    return list(out.values())
