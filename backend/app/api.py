import json
import logging
import queue
import re
import secrets
import threading
import uuid
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app import agents, assistant, upload
from app.dataset import load_mapping
from app.feedback import FeedbackStore
from app.index_files import store_for
from app.settings import BACKEND_DIR, get_settings

FRONTEND_DIR = BACKEND_DIR.parent / "frontend"
HEARTBEAT_SECONDS = 15
log = logging.getLogger("lessons.api")


# size caps keep one request from sending megabytes of text to the model or the feedback file
class Turn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=4000)


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    history: list[Turn] = Field(default=[], max_length=10)


class IngestRequest(BaseModel):
    roles: list[dict] = Field(max_length=200)
    filters: dict[str, list[str]] = {}


class Feedback(BaseModel):
    answer_id: str = Field(max_length=64)
    voter: str | None = Field(default=None, max_length=64)  # browser id; the SSO user header wins
    question: str = Field(max_length=2000)
    vote: Literal["up", "down"]
    lesson_id: str | None = Field(default=None, max_length=64)
    comment: str | None = Field(default=None, max_length=2000)


class Busy(Exception):
    pass


def create_app(settings=None, retrieval=None, graph=None, answer=None, ingest=None):
    settings = settings or get_settings()
    if retrieval is None:
        embedding = agents.embedding_client(settings)
        retrieval = agents.retrieval_client(settings, embedding)
        graph = retrieval if settings.search_store == "neo4j" else agents.graph_client(settings, embedding)
    state = {"answer": answer, "ingest": ingest}
    wording = assistant.for_settings(settings)
    index_store = store_for(settings)
    feedback_store = FeedbackStore(settings, index_store)
    jobs = {}
    ingest_lock = threading.Lock()
    answer_slots = threading.BoundedSemaphore(settings.max_concurrent_answers)

    def limited(fn):
        """Run one answer when a slot is free; waits a little, then gives up so callers aren't stuck."""
        if not answer_slots.acquire(timeout=settings.busy_wait_seconds):
            raise Busy()
        try:
            return fn()
        finally:
            answer_slots.release()
    uploads_dir = Path(settings.data_dir) / "uploads"

    def answer_agent():
        # built on first use so the API starts even if the LLM isn't reachable yet
        if state["answer"] is None:
            state["answer"] = agents.make_answer_agent(settings, retrieval, graph)
        return state["answer"]

    app = FastAPI(title=wording["app_name"])

    @app.get("/api/health")
    def health():
        """For the container platform's health check: ready when an index is loaded and searchable."""
        try:
            version = index_store.current_version()
            retrieval.call("dimensions")  # the search agent answers
        except Exception as e:
            log.warning("health check failed: %s", e)
            raise HTTPException(503, "not ready")
        if version is None:
            raise HTTPException(503, "no index loaded")
        return {"status": "ok", "index": version, "storage": settings.storage,
                "llm": f"{settings.llm_provider}:{settings.llm_model_id}"}

    @app.get("/api/config")
    def config():
        return {
            "llm": f"{settings.llm_provider}:{settings.llm_model_id}",
            "embedding": f"{settings.embedding_provider}:{settings.embedding_model_id}",
            "search_store": settings.search_store,
            "graph": graph is not None,
            "feedback": settings.feature_feedback,
            "debug": settings.feature_debug_panel,
            "streaming": settings.feature_streaming,
            "upload": settings.feature_upload_ui,
            "assistant": assistant.public(assistant.for_settings(settings)),
        }

    @app.post("/api/ask")
    def ask(req: AskRequest):
        try:
            return limited(lambda: answer_agent().ask(req.question, [t.model_dump() for t in req.history]))
        except Busy:
            raise HTTPException(503, "Too many questions at once. Please try again in a moment.",
                                headers={"Retry-After": "10"})

    @app.post("/api/ask/stream")
    def ask_stream(req: AskRequest):
        """Server-sent events: one per tool step, then the final answer."""
        events = queue.Queue()
        history = [t.model_dump() for t in req.history]

        def work():
            try:
                result = limited(lambda: answer_agent().ask(req.question, history, on_event=events.put))
                events.put({"type": "answer", **result})
            except Busy:
                events.put({"type": "error", "message": "Too many questions at once. Please try again in a moment."})
            except Exception:
                log.exception("answer failed")
                events.put({"type": "error", "message": "The answer could not be generated. Please try again."})
            events.put(None)

        threading.Thread(target=work, daemon=True).start()

        def stream():
            while True:
                try:
                    event = events.get(timeout=HEARTBEAT_SECONDS)
                except queue.Empty:
                    yield ": ping\n\n"  # keeps proxies from closing a slow answer
                    continue
                if event is None:
                    return
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

        return StreamingResponse(stream(), media_type="text/event-stream")

    @app.get("/api/lessons/{lesson_id}")
    def lesson(lesson_id: str):
        result = retrieval.call("get_lesson", id=lesson_id)
        if "error" in result:
            raise HTTPException(404, result["error"])
        return result

    @app.get("/api/lessons/{lesson_id}/related")
    def related(lesson_id: str):
        if graph is None:
            raise HTTPException(404, "graph is not enabled")
        return graph.call("related_lessons", id=lesson_id)

    @app.post("/api/feedback")
    def feedback(fb: Feedback, request: Request):
        if not settings.feature_feedback:
            raise HTTPException(404, "feedback is disabled")
        row = fb.model_dump()
        if settings.user_header and request.headers.get(settings.user_header):
            row["voter"] = request.headers[settings.user_header][:64]
        if fb.lesson_id and settings.feature_feedback_boost:
            # embed the question once now, so search never has to embed old votes
            try:
                embedder = state.setdefault("embedder", agents.embedder(settings))
                row["question_vector"] = [round(float(x), 5) for x in embedder.embed([fb.question], kind="query")[0]]
                row["embedding_model"] = embedder.model_id
            except Exception:
                log.warning("could not embed feedback question; search will embed it later")
        feedback_store.write(row)
        if fb.vote == "down" and state["answer"] is not None:
            state["answer"].forget(fb.answer_id)  # don't serve a disliked answer again from the cache
        return {"ok": True}

    def require_admin(token):
        if not settings.feature_upload_ui:
            raise HTTPException(404, "upload is disabled")
        if settings.data_source == "sparql":
            # ingest reads the lessons from SPARQL source, so an uploaded file would be ignored
            raise HTTPException(409, "uploads are off while DATA_SOURCE=sparql")
        if not token or not secrets.compare_digest(token.encode(), (settings.admin_token or "").encode()):
            raise HTTPException(401, "admin token required")

    def active_mapping():
        # the mapping of the live index (e.g. from the last upload), else the configured one
        return index_store.current_mapping() or load_mapping(settings.dataset_config)

    def upload_folder(upload_id):
        folder = uploads_dir / upload_id
        if not re.fullmatch(r"[a-f0-9]{12}", upload_id) or not folder.is_dir():
            raise HTTPException(404, "unknown upload")
        return folder

    @app.post("/api/admin/uploads")
    async def create_upload(file: UploadFile = File(...), sheet: str | None = Form(None), header_row: int = Form(1),
                            x_admin_token: str | None = Header(None)):
        require_admin(x_admin_token)
        name = Path(file.filename or "upload.csv").name
        if Path(name).suffix.lower() not in (".csv", ".xlsx", ".xlsm"):
            raise HTTPException(422, "only .csv and .xlsx files")
        data = await file.read()
        if len(data) > settings.upload_max_mb * 1024 * 1024:
            raise HTTPException(413, f"file is larger than {settings.upload_max_mb} MB")

        upload_id = uuid.uuid4().hex[:12]
        folder = uploads_dir / upload_id
        folder.mkdir(parents=True)
        path = folder / re.sub(r"[^\w.\- ]", "_", name)
        path.write_bytes(data)
        if index_store.remote:  # keep the raw upload; the container's disk doesn't survive a restart
            index_store.remote.put_file(path, "uploads", upload_id, path.name)
        try:
            prof = upload.profile(path, sheet or None, header_row)
        except Exception as e:
            raise HTTPException(422, f"could not read the file: {e}")
        if prof["rows"] > settings.upload_max_rows:
            raise HTTPException(413, f"more than {settings.upload_max_rows} rows")
        meta = {"file": str(path), "sheet": sheet or None, "header_row": header_row, "filename": name,
                "csv": prof["csv"], "columns": [{k: c[k] for k in ("column", "max", "date")} for c in prof["columns"]]}
        (folder / "upload.json").write_text(json.dumps(meta))
        return {"upload_id": upload_id, "filename": name, "profile": prof,
                "suggestion": upload.suggest(prof, active_mapping(), wording["personal_column_hints"]),
                "roles": upload.ROLES, "keep_status_values": wording["keep_status_values"]}

    @app.post("/api/admin/uploads/{upload_id}/ingest")
    def start_ingest(upload_id: str, req: IngestRequest, x_admin_token: str | None = Header(None)):
        require_admin(x_admin_token)
        meta = json.loads((upload_folder(upload_id) / "upload.json").read_text())
        try:
            mapping = upload.build_mapping(active_mapping(), meta["file"], req.roles, req.filters,
                                           meta["sheet"], meta["header_row"], meta.get("csv"),
                                           {"columns": meta.get("columns", [])})
        except ValueError as e:
            raise HTTPException(422, str(e))
        if not ingest_lock.acquire(blocking=False):
            raise HTTPException(409, "another ingest is still running")

        job_id = uuid.uuid4().hex[:12]
        jobs[job_id] = {"status": "running", "upload_id": upload_id}

        def work():
            try:
                if state["ingest"] is None:
                    state["ingest"] = agents.make_ingest_agent(settings)
                jobs[job_id].update(status="done", result=state["ingest"].ingest(mapping=mapping))
            except ValueError as e:  # our own messages, e.g. "no lessons loaded"
                jobs[job_id].update(status="failed", error=str(e))
            except Exception:
                log.exception("ingest failed")
                jobs[job_id].update(status="failed", error="Ingest failed; see the server log.")
            finally:
                ingest_lock.release()

        threading.Thread(target=work, daemon=True).start()
        return {"job_id": job_id}

    @app.get("/api/admin/jobs/{job_id}")
    def job(job_id: str, x_admin_token: str | None = Header(None)):
        require_admin(x_admin_token)
        if job_id not in jobs:
            raise HTTPException(404, "unknown job")
        return jobs[job_id]

    @app.get("/api/admin/current")
    def current(x_admin_token: str | None = Header(None)):
        require_admin(x_admin_token)
        meta = index_store.current_meta()
        if meta is None:
            return {"version": None}
        return {**meta, "mapping": index_store.current_mapping(), "dimensions": retrieval.call("dimensions"),
                "storage": settings.storage}

    @app.get("/")
    def index():
        return FileResponse(FRONTEND_DIR / "index.html")

    @app.get("/admin")
    def admin_page():
        return FileResponse(FRONTEND_DIR / "admin.html")

    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
    return app
