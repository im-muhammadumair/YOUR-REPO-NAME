"""Application configuration and shared constants.

Centralises paths, security settings, and behavioural knobs so the rest of the
codebase only imports from here.

Environment variables are read from the `.env` file next to this module (see
`.env.example` for the supported variables). Secrets and environment-specific
values belong in `.env`, never in source code.
"""
import os
import secrets
from pathlib import Path

from dotenv import load_dotenv

# Location of this file = the backend package root.
BASE_DIR = Path(__file__).resolve().parent

# Load environment variables from the .env file next to this module.
load_dotenv(BASE_DIR / ".env")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
# Storage of served files (sibling of the backend folder).
STORAGE_DIR = BASE_DIR.parent / "storage"

# The local development database file. Used only when DATABASE_URL does not
# point at an external database. It lives in the data `database/` folder
# (sibling of the backend folder).
DATABASE_FILE = BASE_DIR.parent / "database" / "hr-db.db"

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
# Connection string for the application database, read from the DATABASE_URL
# environment variable. Examples:
#   SQLite   -> sqlite:///C:/path/to/hr-db.db
#   Postgres -> postgresql+psycopg://user:pass@host:5432/dbname
#   Oracle   -> oracle+oracledb://user:pass@host:1521/?service_name=ORCL
# If unset, the local SQLite file above is used as the development default.
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DATABASE_FILE.as_posix()}")


def resolve_database_url(url: str) -> str:
    """Make a relative SQLite URL point at the right absolute file path.

    Relative paths in DATABASE_URL are resolved against the backend root
    (BASE_DIR), so the value does not depend on where the app is launched from.
    Non-SQLite URL schemes are left untouched.

    Takes: url - the raw database URL string.
    Returns: a URL with relative SQLite paths made absolute.
    """
    if not url.startswith("sqlite"):
        return url

    # sqlite:///relative/path  ->  scheme plus the path part after "///".
    scheme_prefix = "sqlite:///"
    relative_path = url[len(scheme_prefix):]

    if not relative_path:
        return url

    path = Path(relative_path)

    if path.is_absolute():
        return url

    absolute = BASE_DIR / path
    return f"{scheme_prefix}{absolute.as_posix()}"


DATABASE_URL = resolve_database_url(DATABASE_URL)

# SQLite requires disabling the "same thread" check so the threaded FastAPI
# server can share its pool across requests. This is not needed by client/server
# databases (PostgreSQL, Oracle, ...), so it is only applied for SQLite.
if DATABASE_URL.startswith("sqlite"):
    DATABASE_CONNECT_ARGS = {"check_same_thread": False}
else:
    DATABASE_CONNECT_ARGS = {}

# ---------------------------------------------------------------------------
# Security configuration
# ---------------------------------------------------------------------------
# Frontend origin(s) allowed to talk to this API. Token-based auth is used (no
# cookies), so credentials need not be shared with cross-origin requests.
ALLOWED_ORIGINS = [
    "http://127.0.0.1:5173",
    "http://localhost:5173",
    "http://127.0.0.1:8000",
    "http://localhost:8000",
]

# Session (opaque token) lifetime in seconds. Tokens expire and force re-login.
TOKEN_TTL_SECONDS = 8 * 60 * 60  # 8 hours

# Login throttling: after this many consecutive failures, lock the client out.
LOGIN_MAX_ATTEMPTS = 5
LOGIN_LOCKOUT_SECONDS = 15 * 60

# ---------------------------------------------------------------------------
# File-link (short-lived signed URLs) configuration
# ---------------------------------------------------------------------------
# Secret used to sign short-lived, single-purpose links to files in storage.
# Anyone with a valid signature can open the file; links expire after this many
# seconds, so they cannot be shared/injected to bypass login for long.
FILE_LINK_TTL_SECONDS = 5 * 60


def _load_file_link_secret() -> str:
    """Return a stable signing secret shared by every worker/restart.

    A random secret generated per process would break signed file links the
    moment a request lands on a different worker (multiple people viewing the
    same PDF). The secret therefore comes from, in order of precedence:
      1. the FILE_LINK_SECRET environment variable (.env), or
      2. a secret file created once under the backend folder and reused.

    Takes: none.
    Returns: the stable secret string.
    """
    env_value = os.getenv("FILE_LINK_SECRET", "").strip()

    if env_value:
        return env_value

    secret_path = BASE_DIR / ".file-link-secret"

    try:
        fd = os.open(secret_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        pass
    except OSError:
        return secrets.token_hex(32)
    else:
        # This process created the file (atomically), so it writes the secret.
        with os.fdopen(fd, "w") as secret_file:
            secret_file.write(secrets.token_hex(32))

    try:
        stored = secret_path.read_text().strip()
    except OSError:
        return secrets.token_hex(32)

    return stored or secrets.token_hex(32)


FILE_LINK_SECRET = _load_file_link_secret()

# Valid top-level folders inside storage/ that files may be served from.
# Derived from the folders actually present in storage/ so newly added
# categories (e.g. created through the admin document manager) are allowed too.
_ALLOWED_STORAGE_ROOTS = [
    "benefits",
    "company policy",
    "compilance",
    "finance",
    "forms",
    "HR",
    "IT",
    "onboarding",
    "safety",
]


def _discover_storage_roots() -> list:
    """Return the top-level folder names present in the storage directory.

    Includes the static defaults and any folders an admin created at runtime,
    so every category folder that exists on disk can be served safely.
    """
    roots = set(_ALLOWED_STORAGE_ROOTS)
    try:
        for child in STORAGE_DIR.iterdir():
            if child.is_dir():
                roots.add(child.name)
    except OSError:
        pass
    return sorted(roots)


ALLOWED_STORAGE_ROOTS = _discover_storage_roots()

# ---------------------------------------------------------------------------
# JWT authentication configuration
# ---------------------------------------------------------------------------
# Algorithm used to sign JWT access tokens (asymmetric RS256).
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "RS256")

# Issuer and audience claims that must be present and match during verification.
JWT_ISSUER = os.getenv("JWT_ISSUER", "MTM-HR-Agent")
JWT_AUDIENCE = os.getenv("JWT_AUDIENCE", "MTM-HR-API")

# Access token lifetime. Access tokens must stay short-lived.
JWT_ACCESS_TOKEN_EXPIRE_MINUTES = int(
    os.getenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "20")
)

# Refresh token / refresh session lifetime.
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "14"))

# Base64 Fernet key used to encrypt account passwords at rest. When unset a key
# file is created once under the backend folder (.credentials.key) and reused on
# every restart. Losing the key makes stored passwords unrecoverable.
CREDENTIALS_KEY = os.getenv("CREDENTIALS_KEY", "")

# RSA key pair used to sign and verify JWTs (RS256).
# Provided as base64-safe quoted PEM in .env; generated at runtime if missing.
JWT_PRIVATE_KEY = os.getenv("JWT_PRIVATE_KEY", "")
JWT_PUBLIC_KEY = os.getenv("JWT_PUBLIC_KEY", "")

# ---------------------------------------------------------------------------
# RAG / AI configuration
# ---------------------------------------------------------------------------
# Gemini API key, read from .env (never hardcoded). Used for embeddings and
# the generative chat model that answers grounded questions.
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()

# Local ChromaDB persistence folder. Any vectors/embeddings live here, separate
# from the application SQLite database (which is left untouched).
CHROMA_DIR = BASE_DIR.parent / "database" / "chroma_db"

# The ChromaDB collection key. All indexed HR documents share one collection,
# filtered at query time by the set of admin-enabled document ids.
CHROMA_COLLECTION = "hr_documents"

# Gemini model names.
#
# Embeddings use a stable text model with task_type hints for retrieval.
GEMINI_EMBED_MODEL = os.getenv("GEMINI_EMBED_MODEL", "gemini-embedding-001")

# Generation models. The router (rag/model_registry.py) dynamically discovers
# which of these are actually available at startup and builds a fallback chain
# from them, because Google can retire model names at any time. These values are
# therefore "preferences / candidates", not guarantees. The `-latest` aliases
# are intentionally preferred because they always point at a current model.
GEMINI_CHAT_MODEL = os.getenv("GEMINI_CHAT_MODEL", "gemini-flash-latest")
GEMINI_RERANK_MODEL = os.getenv("GEMINI_RERANK_MODEL", "gemini-flash-lite-latest")

# Additional generation candidates consulted during model discovery, most
# capable first. The router picks the cheapest of these that is healthy and
# appropriate for the task, and falls back to the next if it fails.
GEMINI_MODEL_CANDIDATES = [
    os.getenv("GEMINI_STRONG_MODEL", "gemini-pro-latest"),
    os.getenv("GEMINI_GENERAL_MODEL", "gemini-flash-latest"),
    os.getenv("GEMINI_LIGHT_MODEL", "gemini-flash-lite-latest"),
]

# Embedding output dimensionality. gemini-embedding-001 supports 128-3072.
# 1536 is a good balance of quality and storage/query speed.
RAG_EMBEDDING_DIMENSIONS = int(os.getenv("RAG_EMBEDDING_DIMENSIONS", "1536"))

# Retrieval knobs. The RAG engine searches the whole enabled corpus (never a
# single PDF), fuses BM25 + vector signals with RRF, reranks locally, then keeps
# only the strongest evidence for Gemini. candidate vs final counts are
# deliberately separated so retrieval can be broad while generation stays cheap.
RAG_TOP_K = int(os.getenv("RAG_TOP_K", "8"))
RAG_SCORE_THRESHOLD = float(os.getenv("RAG_SCORE_THRESHOLD", "0.30"))
RAG_FINAL_CONTEXT_CHUNKS = int(os.getenv("RAG_FINAL_CONTEXT_CHUNKS", "5"))

# RRF fusion constant (standard value used by most implementations).
RAG_RRF_K = float(os.getenv("RAG_RRF_K", "60"))

# Candidate counts per retrieval profile (EXACT/NORMAL/COMPLEX/DEEP). The
# planner picks one tier; the reranker then aggressively trims to
# RAG_FINAL_CONTEXT_CHUNKS. candidate_k is always >= final_context_k.
RAG_CANDIDATE_K = {
    "EXACT":   int(os.getenv("RAG_CANDIDATE_K_EXACT", "16")),
    "NORMAL":  int(os.getenv("RAG_CANDIDATE_K_NORMAL", "30")),
    "COMPLEX": int(os.getenv("RAG_CANDIDATE_K_COMPLEX", "60")),
    "DEEP":    int(os.getenv("RAG_CANDIDATE_K_DEEP", "100")),
}

# How many candidates each retrieval path returns before fusion.
RAG_BM25_K = int(os.getenv("RAG_BM25_K", "60"))
RAG_VECTOR_K = int(os.getenv("RAG_VECTOR_K", "30"))

# Reranker depth: how many RRF-fused candidates get the (heuristic) reranker.
RAG_RERANK_K = int(os.getenv("RAG_RERANK_K", "40"))

# How many parent/neighbor chunks to attach around a matched chunk (same doc,
# plus/minus this many chunk_index), to recover surrounding context without
# returning an entire PDF.
RAG_NEIGHBOR_WINDOW = int(os.getenv("RAG_NEIGHBOR_WINDOW", "1"))

# ---------------------------------------------------------------------------
# Cost / reliability guardrails for the AI orchestration layer
# ---------------------------------------------------------------------------
# Caps that prevent accidental cost or latency explosions on any single request.
AI_MAX_GEMINI_CALLS = int(os.getenv("AI_MAX_GEMINI_CALLS", "4"))   # total gen calls
AI_MAX_FALLBACKS = int(os.getenv("AI_MAX_FALLBACKS", "3"))         # model switches
AI_MAX_RETRIES = int(os.getenv("AI_MAX_RETRIES", "1"))             # retries of a 429/5xx

# Model health: after this many consecutive failures a model enters a cool-down;
# it is not used again until the cool-down expires.
AI_HEALTH_FAILURE_LIMIT = int(os.getenv("AI_HEALTH_FAILURE_LIMIT", "3"))
AI_HEALTH_COOLDOWN_SECONDS = int(os.getenv("AI_HEALTH_COOLDOWN_SECONDS", "300"))

# Cache: how long safe (non-user-specific) grounded answers are reused.
AI_CACHE_TTL_SECONDS = int(os.getenv("AI_CACHE_TTL_SECONDS", "3600"))
