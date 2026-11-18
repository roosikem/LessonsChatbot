"""One small chat interface over Ollama (local dev) and Bedrock Converse (live).

Messages use a neutral shape so the answer agent doesn't care which backend runs:
  {"role": "user" | "assistant", "content": str, "tool_calls": [...]}
  {"role": "tool", "tool_call_id": str, "name": str, "content": dict}
A tool call is {"id": str, "name": str, "input": dict}.
"""
import json
import urllib.request
import uuid
from dataclasses import dataclass, field

import boto3


@dataclass
class Reply:
    text: str = ""
    tool_calls: list = field(default_factory=list)
    data: dict | None = None  # filled when a schema was requested
    usage: dict = field(default_factory=dict)  # input_tokens, output_tokens, model_ms (what the provider reports)


class OllamaLLM:
    def __init__(self, model, url="http://localhost:11434", timeout=600, temperature=0.1):
        self.model = model
        self.temperature = temperature
        self.url = url.rstrip("/")
        self.timeout = timeout

    def chat(self, system, messages, tools=None, schema=None):
        body = {
            "model": self.model,
            "stream": False,
            "think": False,
            "options": {"temperature": self.temperature},
            "messages": [{"role": "system", "content": system}] + [self._to_ollama(m) for m in messages],
        }
        if tools:
            body["tools"] = [{"type": "function", "function": {
                "name": t["name"], "description": t["description"], "parameters": t["schema"]}} for t in tools]
        if schema:
            body["format"] = schema
        req = urllib.request.Request(f"{self.url}/api/chat", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            body = json.loads(resp.read())
        msg = body["message"]

        calls = [{"id": c.get("id") or uuid.uuid4().hex[:8], "name": c["function"]["name"],
                  "input": c["function"].get("arguments") or {}} for c in msg.get("tool_calls") or []]
        reply = Reply(text=msg.get("content", ""), tool_calls=calls, usage={
            "input_tokens": body.get("prompt_eval_count"), "output_tokens": body.get("eval_count"),
            "model_ms": round((body.get("total_duration") or 0) / 1e6)})
        if schema:
            reply.data = json.loads(reply.text)
        return reply

    @staticmethod
    def _to_ollama(m):
        if m["role"] == "tool":
            return {"role": "tool", "tool_name": m["name"], "content": json.dumps(m["content"])}
        out = {"role": m["role"], "content": m.get("content", "")}
        if m.get("tool_calls"):
            out["tool_calls"] = [{"function": {"name": c["name"], "arguments": c["input"]}} for c in m["tool_calls"]]
        return out


class CutOff(RuntimeError):
    """The model stopped at the token limit, so its reply (or tool input) is incomplete."""


def bedrock_client(profile=None, region="us-east-1", settings=None):
    from botocore.config import Config
    config = Config(
        retries={"max_attempts": getattr(settings, "bedrock_max_attempts", 4), "mode": "adaptive"},
        max_pool_connections=getattr(settings, "bedrock_max_connections", 32),
        read_timeout=getattr(settings, "bedrock_read_timeout", 60), connect_timeout=5)
    session = boto3.Session(profile_name=profile, region_name=region)
    role_arn = getattr(settings, "bedrock_role_arn", None)
    if role_arn:
        session = assumed_session(session, role_arn, region)
    return session.client("bedrock-runtime", config=config)


def assumed_session(base, role_arn, region):
    """A session on another account's role whose credentials renew themselves before they expire."""
    from botocore.credentials import RefreshableCredentials
    from botocore.session import get_session
    sts = base.client("sts")

    def fetch():
        c = sts.assume_role(RoleArn=role_arn, RoleSessionName="lessons-chatbot", DurationSeconds=3600)["Credentials"]
        return {"access_key": c["AccessKeyId"], "secret_key": c["SecretAccessKey"], "token": c["SessionToken"],
                "expiry_time": c["Expiration"].isoformat()}

    core = get_session()
    core._credentials = RefreshableCredentials.create_from_metadata(fetch(), fetch, "assume-role")
    return boto3.Session(botocore_session=core, region_name=region)


class BedrockLLM:
    max_tokens = 2000

    def __init__(self, model_id, profile=None, region="us-east-1", temperature=0.1, settings=None):
        self.model_id = model_id
        self.temperature = temperature
        self.client = bedrock_client(profile, region, settings)

    def chat(self, system, messages, tools=None, schema=None):
        specs = [{"toolSpec": {"name": t["name"], "description": t["description"],
                               "inputSchema": {"json": t["schema"]}}} for t in tools or []]
        tool_config = None
        if schema:
            # Converse has no JSON mode, so force a single "answer" tool with the schema
            specs = [{"toolSpec": {"name": "answer", "description": "Return the final answer.",
                                   "inputSchema": {"json": schema}}}]
            tool_config = {"tools": specs, "toolChoice": {"tool": {"name": "answer"}}}
        elif specs:
            tool_config = {"tools": specs, "toolChoice": {"auto": {}}}

        kwargs = {"modelId": self.model_id, "system": [{"text": system}],
                  "messages": self._to_converse(messages),
                  "inferenceConfig": {"maxTokens": self.max_tokens, "temperature": self.temperature}}
        if tool_config:
            kwargs["toolConfig"] = tool_config
        resp = self.client.converse(**kwargs)
        if resp.get("stopReason") == "max_tokens":
            # a cut-off tool input or answer would look valid but be missing parts: try once with more room
            kwargs["inferenceConfig"]["maxTokens"] = self.max_tokens * 2
            resp = self.client.converse(**kwargs)
            if resp.get("stopReason") == "max_tokens":
                raise CutOff(f"{self.model_id} reply hit the token limit twice")

        usage = resp.get("usage", {})
        reply = Reply(usage={"input_tokens": usage.get("inputTokens"), "output_tokens": usage.get("outputTokens"),
                             "model_ms": resp.get("metrics", {}).get("latencyMs")})
        for block in resp["output"]["message"]["content"]:
            if "text" in block:
                reply.text += block["text"]
            elif "toolUse" in block:
                use = block["toolUse"]
                reply.tool_calls.append({"id": use["toolUseId"], "name": use["name"], "input": use["input"]})
        if schema:
            reply.data = reply.tool_calls[0]["input"] if reply.tool_calls else json.loads(reply.text)
            reply.tool_calls = []
        return reply

    @staticmethod
    def _to_converse(messages):
        """Neutral messages -> Converse turns. Converse wants alternating user/assistant turns with
        non-empty content, so tool results and the next user text share one user turn."""
        out = []
        for m in messages:
            if m["role"] == "tool":
                role, content = "user", [{"toolResult": {"toolUseId": m["tool_call_id"],
                                                         "content": [{"json": m["content"]}]}}]
            else:
                role = m["role"]
                content = [{"text": m["content"]}] if (m.get("content") or "").strip() else []
                content += [{"toolUse": {"toolUseId": c["id"], "name": c["name"], "input": c["input"]}}
                            for c in m.get("tool_calls") or []]
            if not content:
                continue
            if out and out[-1]["role"] == role:
                out[-1]["content"].extend(content)
            else:
                out.append({"role": role, "content": content})
        while out and out[0]["role"] != "user":
            out.pop(0)
        return out


def make_llm(settings, provider=None, model_id=None, temperature=0.1):
    """The main chat model, or another one (e.g. a small grader model) when provider/model_id are given."""
    provider = provider or settings.llm_provider
    model_id = model_id or settings.llm_model_id
    if not model_id:
        raise ValueError("LLM_MODEL_ID is not set")
    if provider == "ollama":
        return OllamaLLM(model_id, settings.ollama_url, temperature=temperature)
    return BedrockLLM(model_id, settings.bedrock_aws_profile, settings.bedrock_region, temperature=temperature,
                      settings=settings)
