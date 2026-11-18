"""How agents talk to each other: in-process today, over HTTP when split out.

An agent is any object with a `name` and a `methods` tuple listing what it
exposes. Arguments and results are plain JSON, so a call works the same
locally and remotely.
"""
import json
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class AgentError(Exception):
    pass


class LocalClient:
    def __init__(self, agent):
        self.agent = agent
        self.name = agent.name

    def call(self, method, **kwargs):
        if method not in self.agent.methods:
            raise AgentError(f"{self.name} has no method {method}")
        result = getattr(self.agent, method)(**kwargs)
        # round-trip through JSON so anything that wouldn't survive HTTP fails here too
        return json.loads(json.dumps(result))


class HttpClient:
    def __init__(self, name, base_url, timeout=300):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def call(self, method, **kwargs):
        req = urllib.request.Request(f"{self.base_url}/{method}", data=json.dumps(kwargs).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            raise AgentError(f"{self.name}.{method}: {e.code} {e.read().decode()[:300]}") from e
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            raise AgentError(f"{self.name}.{method}: cannot reach {self.base_url} ({e})") from e


def make_server(agent, host="127.0.0.1", port=8100):
    client = LocalClient(agent)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/health":
                self._send(200, {"agent": agent.name, "methods": list(agent.methods)})
            else:
                self._send(404, {"error": "not found"})

        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            try:
                kwargs = json.loads(self.rfile.read(length) or b"{}")
                self._send(200, client.call(self.path.strip("/"), **kwargs))
            except AgentError as e:
                self._send(404, {"error": str(e)})
            except Exception as e:
                self._send(500, {"error": f"{type(e).__name__}: {e}"})

        def _send(self, status, body):
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    return ThreadingHTTPServer((host, port), Handler)
