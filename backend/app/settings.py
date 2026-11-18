from functools import lru_cache
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", extra="ignore")

    bedrock_aws_profile: str | None = None
    bedrock_region: str = "us-east-1"

    llm_provider: str = "ollama"  # ollama | bedrock
    llm_model_id: str | None = None
    llm_max_tool_rounds: int = 2

    embedding_provider: str = "ollama"  # ollama | bedrock | local
    embedding_model_id: str = "bge-m3"
    embedding_dim: int = 1024
    ollama_url: str = "http://localhost:11434"

    # empty = agent runs in this process; a URL = call it over HTTP
    agent_embedding_url: str | None = None
    agent_retrieval_url: str | None = None
    agent_graph_url: str | None = None
    agent_sparql_url: str | None = None
    agent_grader_url: str | None = None

    data_source: str = "file"
    data_dir: Path = BACKEND_DIR / "data"

    # where index versions, uploads and feedback live: local disk, or S3 (shared by all containers)
    storage: str = "local"  # local | s3
    s3_bucket: str | None = None
    s3_prefix: str = "lessons"
    s3_region: str = "us-east-1"
    s3_endpoint_url: str | None = None  # only for S3 stand-ins (moto locally)
    s3_aws_profile: str | None = None   # local runs; on Fargate the task role is used
    s3_access_key: str | None = None    # only for S3 stand-ins
    s3_secret_key: str | None = None
    index_poll_seconds: int = 30         # how often a container checks for a new index version
    dataset_config: Path = BACKEND_DIR / "config" / "dataset.yaml"
    app_name: str | None = None               # name shown in the UI; overrides app_name in assistant.yaml
    assistant_config: Path = BACKEND_DIR / "config" / "assistant.yaml"  # wording, examples, word lists

    search_store: str = "memory"
    top_k_candidates: int = 20
    top_k_answer: int = 8
    feature_vector_search: bool = True
    feature_keyword_search: bool = True
    feature_context_boost: bool = True
    score_w_context: float = 0.05
    score_w_related: float = 0.15  # boost for lessons linked to the same / comparable context items
    # below this cosine a hit is never more than 'low' confidence (bge-m3: from the eval, ~0.45)
    confidence_min_similarity: float = 0.45

    feature_neo4j: bool = False
    neo4j_uri: str | None = None
    neo4j_user: str | None = None
    neo4j_password: str | None = None
    neo4j_database: str = "neo4j"
    neo4j_fulltext_analyzer: str = "english"  # Lucene analyzer; match the language of the lesson texts

    feature_sparql_source: bool = False
    sparql_endpoint: str | None = None
    sparql_token: str | None = None
    sparql_user: str | None = None
    sparql_password: str | None = None

    feature_clarifying_questions: bool = True
    feature_grounding_checks: bool = True

    # grader agent: checks each found lesson before the answer is written; can use a smaller model
    feature_evidence_grading: bool = False
    grader_provider: str | None = None  # default: LLM_PROVIDER
    grader_model_id: str | None = None  # default: LLM_MODEL_ID
    grader_max_candidates: int = 8

    # latency: each of these saves a model round trip or output tokens
    feature_score_order: bool = True           # lessons shown in search-score order, not the model's order
    feature_feedback_boost: bool = True        # thumbs up/down nudge the ranking for similar questions
    score_w_feedback: float = 0.1              # max effect of feedback on a score (it's squashed to -1..1)
    feedback_min_similarity: float = 0.6       # a vote counts only for questions at least this similar
    feedback_half_life_days: int = 180         # votes fade with age
    user_header: str | None = None             # header with the signed-in user (from SSO), used as the voter id
    max_concurrent_answers: int = 8            # per container; more questions wait, then get "busy"
    busy_wait_seconds: int = 20                # how long a question waits for a free slot
    bedrock_role_arn: str | None = None        # Bedrock in another account: the task role assumes this role
    bedrock_max_attempts: int = 4              # retries after the first try (backoff, on throttling and timeouts)
    bedrock_max_connections: int = 32          # connection pool per Bedrock client
    bedrock_read_timeout: int = 60
    feature_parallel_grading: bool = True      # grader runs alongside the final answer; grades applied after
    feature_answer_cache: bool = True          # same question + same index / settings -> stored answer
    answer_cache_ttl_seconds: int = 900
    answer_cache_size: int = 500
    feature_stop_rule: bool = True             # a search with a good signal goes straight to the final answer
    feature_auto_resolve_context: bool = True  # search maps loose context values to the data's values itself
    feature_reasons_in_code: bool = True       # "why relevant" built from search results, not written by the model
    tool_text_chars: int = 600                 # lesson text sent to the model per hit (full text kept for checks)

    feature_feedback: bool = True
    feedback_store: str = "file"

    feature_upload_ui: bool = False
    admin_token: str | None = None
    upload_max_mb: int = 20
    upload_max_rows: int = 20000

    eval_questions: Path | None = None         # question set for `app.cli eval` (not part of the app)
    eval_dataset: Path | None = None           # dataset mapping that question set was written for
    feature_streaming: bool = True
    feature_debug_panel: bool = False

    @model_validator(mode="before")
    @classmethod
    def empty_means_unset(cls, data):
        # "GRADER_PROVIDER=" in .env means "not set": use the default instead of an empty string
        if isinstance(data, dict):
            return {k: v for k, v in data.items() if v != ""}
        return data

    @model_validator(mode="after")
    def check_combinations(self):
        if self.data_source == "sparql" and self.dataset_config.name == "dataset.yaml":
            self.dataset_config = self.dataset_config.with_name("dataset.sparql.yaml")
        errors = []
        if self.search_store == "pgvector":
            errors.append("SEARCH_STORE=pgvector is planned but not built yet; use memory or neo4j")
        elif self.search_store not in ("memory", "neo4j"):
            errors.append(f"SEARCH_STORE must be memory or neo4j, got {self.search_store}")
        if self.search_store == "neo4j" and not (self.feature_neo4j and self.neo4j_uri):
            errors.append("SEARCH_STORE=neo4j needs FEATURE_NEO4J=true and NEO4J_URI")
        if self.data_source == "sparql" and not (self.feature_sparql_source and self.sparql_endpoint):
            errors.append("DATA_SOURCE=sparql needs FEATURE_SPARQL_SOURCE=true and SPARQL_ENDPOINT")
        if self.llm_provider not in ("ollama", "bedrock"):
            errors.append(f"LLM_PROVIDER must be ollama or bedrock, got {self.llm_provider}")
        if self.embedding_provider not in ("ollama", "bedrock", "local"):
            errors.append(f"EMBEDDING_PROVIDER must be ollama, bedrock or local, got {self.embedding_provider}")
        if self.grader_provider not in (None, "ollama", "bedrock"):
            errors.append(f"GRADER_PROVIDER must be ollama or bedrock, got {self.grader_provider}")
        if self.storage not in ("local", "s3"):
            errors.append(f"STORAGE must be local or s3, got {self.storage}")
        if self.storage == "s3" and not self.s3_bucket:
            errors.append("STORAGE=s3 needs S3_BUCKET")
        if self.feedback_store not in ("file", "s3"):
            errors.append("FEEDBACK_STORE must be file or s3")
        if self.feedback_store == "s3" and self.storage != "s3":
            errors.append("FEEDBACK_STORE=s3 needs STORAGE=s3")
        if self.feature_upload_ui and not self.admin_token:
            errors.append("FEATURE_UPLOAD_UI=true needs ADMIN_TOKEN")
        if errors:
            raise ValueError("; ".join(errors))
        return self


@lru_cache
def get_settings():
    return Settings()
