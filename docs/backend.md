# MTM HR Agent — Backend Reference

This document describes the entire backend so a developer can quickly understand
every file, what it does, and where to change things.

- **Stack:** Python + [FastAPI](https://fastapi.tiangolo.com/) + SQLAlchemy ORM + SQLite (swappable)
- **Auth:** enterprise JWT + rotating refresh tokens + RBAC (RS256), sessions in SQLite
- **Entry point:** `backend/main.py` (run with `python main.py`)
- **Port / host:** `127.0.0.1:8000`

---

## Table of Contents

1. [Architecture & data flow](#1-architecture--data-flow)
2. [Directory structure](#2-directory-structure)
3. [File references (quick review + details)](#3-file-references-quick-review--details)
   - [main.py](#mainpy)
   - [config.py](#configpy)
   - [auth (folder)](#auth-folder-)
     - [keys.py](#keyspy)
     - [jwt_service.py](#jwt_servicepy)
     - [security.py](#securitypy)
     - [refresh_service.py](#refresh_servicepy)
     - [rbac.py](#rbacpy)
     - [dependencies.py](#dependenciespy)
     - [routes.py](#routespy)
   - [database (folder)](#database-folder-)
     - [connection.py](#connectionpy)
     - [models.py](#modelspy)
     - [crud.py](#crudpy)
     - [seed_users.py](#seed_userspy)
   - [schemas (folder)](#schemas-folder-)
     - [schemas.py](#schemaspy)
   - [utils (folder)](#utils-folder-)
     - [helpers.py](#helperspy)
- [routes (folder)](#routes-folder-)
      - [employees.py](#employeespy)
      - [attendance.py](#attendancepy)
      - [leaves.py](#leavespy)
      - [payroll.py](#payrollpy)
      - [documents.py](#documentspy)
      - [accounts.py](#accountspy)
4. [Endpoint map (all routes)](#4-endpoint-map-all-routes)
5. [How to run / test](#5-how-to-run--test)
6. [Common change scenarios](#6-common-change-scenarios)

---

## 1. Architecture & data flow

```
 Browser / frontend (React)
        │  HTTP + JSON  (Authorization: Bearer <access token>)
        ▼
   FastAPI app  (main.py)
        │
        ├── routes/*.py          → receives request, validates, returns result
        │         │
        │         ▼
        ├── auth/dependencies.py → JWT verification, user load, RBAC gates
        │         │
        ├── auth/jwt_service.py  → create/verify RS256 access tokens
        ├── auth/refresh_service.py → rotating refresh sessions (SHA-256 in DB)
        ├── auth/rbac.py         → roles → permissions mapping + seeding
        ├── auth/keys.py         → loads the RS256 keys from .env
        │
        ├── database/crud.py     → all SQL queries + response-shape helpers
        │         │
        │         ▼
        ├── database/models.py    → ORM table definitions (the schema)
        │         │
        │         ▼
        ├── database/connection.py → ORM engine + session (reads DATABASE_URL)
        │
        └── utils/helpers.py      → file-link signing + token extraction
```

- The **frontend only sees JSON over HTTP**. It never talks to the database.
- **Routes are thin**: they validate input, call a crud/business helper, and
  return data. Business logic lives in `auth/` and `database/crud.py`.
- **All data access goes through the ORM**, so switching databases
  (SQLite → PostgreSQL/Oracle) only requires changing `DATABASE_URL` — query
  code does not change.

---

## 2. Directory structure

```
3. currently working/
├── backend/                 ← the Python API (this doc)
│   ├── main.py              entrypoint: FastAPI app, lifespan seeding, routers
│   ├── config.py            .env loading + all constants/settings
│   ├── import_db.py         one-off script that builds the SQLite DB
│   ├── requirements.txt     Python dependencies
│   ├── pyproject.toml       uv project config
│   ├── .env                 connection string + RS256 keys + JWT settings + CREDENTIALS_KEY
│   ├── auth/
│   │   ├── keys.py          load/generate the RS256 key pair
│   │   ├── jwt_service.py   create/verify access JWTs
│   │   ├── security.py      password check + login throttle
│   │   ├── creds.py         Fernet encrypt/decrypt for stored passwords
│   │   ├── refresh_service.py  refresh-token generate/validate/rotate/revoke
│   │   ├── rbac.py          ROLE_PERMISSIONS mapping + seed + helpers
│   │   ├── dependencies.py  FastAPI auth dependencies (get_authenticated_user…)
│   │   ├── routes.py        /api/auth/* endpoints (login, refresh, logout, …)
│   │   └── __init__.py
│   ├── database/
│   │   ├── connection.py    engine, session, get_db dependency
│   │   ├── models.py        ORM tables (business + auth schema contract)
│   │   ├── crud.py          queries + serializers
│   │   ├── migrate_ai.py    idempotent migration: adds Document AI/RAG columns
│   │   ├── seed_users.py    migrates credentials → users + assigns roles
│   │   └── __init__.py
│   ├── schemas/
│   │   ├── schemas.py       Pydantic request/response schemas
│   │   └── __init__.py
│   ├── utils/
│   │   ├── helpers.py       signed file links, bearer token extraction
│   │   └── __init__.py
│   ├── rag/                 RAG / AI orchestration for the chat endpoint
│   │   ├── config.py        RAG settings + model preference candidates
│   │   ├── embeddings.py    Gemini embedding wrappers (query + document)
│   │   ├── ingestion.py     PDF parsing, chunking, ChromaDB index/deindex
│   │   ├── model_registry.py  dynamic Gemini model discovery + tiers
│   │   ├── model_health.py    per-model success/failure + cooldown
│   │   ├── model_router.py    cost-aware model selection + failover chain
│   │   ├── token_manager.py   adaptive token budgets + context trimming
│   │   ├── query_router.py    complexity detection + personal-question deflect
│   │   ├── retriever.py       vector search over ChromaDB (raw candidates)
│   │   ├── reranker.py        relevance rerank + dedup + context compression
│   │   ├── generator.py       generation with escalation + smart failover
│   │   ├── validator.py       grounding/confidence + escalation decision
│   │   ├── cache.py           safe cache for non-personal answers
│   │   ├── prompts.py         reusable prompt components + injection protection
│   │   ├── rag_service.py     public orchestration entry point
│   │   └── __init__.py
│   └── routes/
│       ├── employees.py
│       ├── attendance.py
│       ├── leaves.py
│       ├── payroll.py
│       ├── documents.py
│       ├── chat.py           POST /api/chat (grounded PDF answers)
│       ├── accounts.py
│       └── __init__.py
├── database/                data folder (hr-db.db, chroma_db/) — sibling of backend
├── storage/                 served files (PDFs) — sibling of backend
└── frontend/                React app (calls this API)
```

Packages named `auth/`, `database/`, `schemas/`, `utils/`, `routes/` are Python
packages (have `__init__.py`). The top-level `database/` **data folder** (next
to `backend/`, holding `hr-db.db`) is **not** the code package — they are
distinct things.

---

## 3. File references (quick review + details)

### main.py

**Quick review:** The application entrypoint. Builds the FastAPI app, adds CORS,
registers the auth + domain routers, and seeds authentication data on startup.

**Details:**
- Imports `ALLOWED_ORIGINS` from `config`, the auth router from `auth.routes`,
  the seeding helpers, and the domain routers from `routes`.
- `app = FastAPI(title="MTM HR Agent API", lifespan=lifespan)`
- **CORS:** `add_middleware(CORSMiddleware, ...)` with `allow_credentials=False`
  (JWT bearer auth, no cookies). Origins come from `config.ALLOWED_ORIGINS`.
- **lifespan startup:**
  - `Base.metadata.create_all(bind=engine)` — ensures the auth tables
    (`users`, `roles`, `permissions`, `refresh_sessions`) exist.
  - `run_ai_migrations()` — adds the `documents` AI/RAG columns if missing.
  - **Gemini model discovery** — when `GEMINI_API_KEY` is set, calls
    `rag.model_registry.discover()` against the live API and binds the shared
    `health` tracker (`rag.model_health`). This is wrapped in try/except so a
    missing key or a failed discovery never crashes startup; model names are
    never hardcoded to a single always-available version.
  - `seed_roles_and_permissions(db)` — inserts the role/permission lookup data.
  - `seed_users(db)` — migrates existing `credentials` into `users` + roles.
- Includes routers: auth, accounts, employees, attendance, leaves, payroll,
  documents, chat.
- `GET /api/health` → `{"status": "ok"}`
- `if __name__ == "__main__":` → runs `uvicorn.run(app, host="127.0.0.1", port=8000)`.

> **Where to change:** adding a new endpoint group (add a router file +
> `include_router`), changing CORS origins, startup seeding, server port/host.

---

### config.py

**Quick review:** Single place for paths, settings, and security constants. Loads
`.env` and resolves the database URL and JWT keys.

**Details:**
- `BASE_DIR = Path(__file__).resolve().parent` (the backend folder).
- `load_dotenv(BASE_DIR / ".env")` — loads env vars from `.env` next to config.
- `STORAGE_DIR = BASE_DIR.parent / "storage"` — served files folder.
- `DATABASE_FILE = BASE_DIR.parent / "database" / "hr-db.db"` — local SQLite file.
- `DATABASE_URL = os.getenv("DATABASE_URL", <local sqlite default>)`.
- `resolve_database_url(url)` — makes relative SQLite URLs absolute (resolved
  against `BASE_DIR`); leaves other schemes (postgres/oracle) untouched.
- `DATABASE_CONNECT_ARGS` — sets `{"check_same_thread": False}` only for SQLite
  (needed by threaded FastAPI); empty for client/server DBs.
- JWT / auth settings (from `.env`):
  - `JWT_ALGORITHM`, `JWT_ISSUER`, `JWT_AUDIENCE`.
  - `JWT_ACCESS_TOKEN_EXPIRE_MINUTES=20`, `REFRESH_TOKEN_EXPIRE_DAYS=14`.
  - `JWT_PRIVATE_KEY`, `JWT_PUBLIC_KEY` — RS256 key pair (quoted PEM with `\n`).
- Other security constants:
  - `ALLOWED_ORIGINS` — CORS list.
  - `FILE_LINK_TTL_SECONDS = 5 * 60`. `FILE_LINK_SECRET` is **stable**: it comes
    from `FILE_LINK_SECRET` in `.env` if set, otherwise from a secret file
    (`backend/.file-link-secret`) created once and reused — so every worker and
    restart signs/verifies with the same secret and PDF links work for all users.
    The secret file is gitignored.
  - `ALLOWED_STORAGE_ROOTS` — list of top-level folder names files may be served from.

> **Where to change:** `.env` (real settings), DB connection, CORS origins, JWT
> settings/keys, login throttle values, storage roots, file-link ttl/secret,
> Gemini model candidates / RAG retrieval knobs / AI cost & health guardrails.

---

### auth (folder)

#### keys.py

**Quick review:** Loads the RS256 signing/verification keys from `.env`, and can
generate a fresh key pair.

**Details:**
- `load_private_key(pem_text)` / `load_public_key(pem_text)` — parse the PEM.
- `get_signing_key()` / `get_verification_key()` — return the loaded keys used
  by `jwt_service` (reads `JWT_PRIVATE_KEY` / `JWT_PUBLIC_KEY`).
- `generate_key_pair()` — creates a new RS256 pair (print the output to paste
  into `.env` if keys ever need rotating).

> **Where to change:** key loading logic, key rotation.

---

#### jwt_service.py

**Quick review:** Signs and verifies the short-lived access JWTs.

**Details:**
- `create_access_token(user, permissions)` — builds a JWT with claims `sub`
  (username), `employee_id`, `role`, `permissions`, `iat`, `exp`, `iss`, `aud`,
  `jti`, `token_type`. Signs with RS256 using `get_signing_key()`.
- `verify_access_token(token)` — validates signature, issuer, audience and
  expiry using `get_verification_key()`. Returns the claims; raises on any
  invalid/expired token.
- `primary_role_name(user)` — returns the user's single most-privileged role
  name (used for display, e.g. `/api/me` `account_type`).

> **Where to change:** token TTL/claims, signing algorithm, claim names.

---

#### security.py

**Quick review:** Password verification and a login throttle.

**Details:**
- `verify_password(password, stored_password, stored_hash=None)` —
  compares a submitted password against the stored password.
  `stored_password` is transparently decrypted first (via `auth/creds.py`) when
  it carries the Fernet ciphertext prefix (`fcd1$…`); legacy plaintext values
  are compared as-is. `password_hash` is reserved for future hashing (currently
  not enforced).
- `constant_time_equals(left, right)` — constant-time string comparison.
- `class LoginThrottle` — in-memory failed-login tracker keyed by
  `clientIP::username`; locks after `LOGIN_MAX_ATTEMPTS` for
  `LOGIN_LOCKOUT_SECONDS`. Methods: `is_locked`, `record_failure`, `reset`.

> **Where to change:** password storage/verification strategy, throttle rules.

---

#### creds.py

**Quick review:** Password encryption for the DB. Passwords are stored as
reversible Fernet ciphertext (prefix `fcd1$`) instead of plaintext — reversible
on purpose so the admin "Manage accounts" panel can still display the password.

**Details:**
- Decryption key comes from the `CREDENTIALS_KEY` env var (base64 Fernet key)
  or, when absent, from an auto-generated key file `backend/.credentials.key`
  (created once, permissions `0600`).
- `is_encrypted(value)` — true when the value starts with `fcd1$`.
- `encrypt_password(plaintext)` — idempotent: encrypts a plaintext password,
  returns ciphertext unchanged if already encrypted, returns `None` for empty.
- `decrypt_password(token)` — returns the plaintext, or `None` on failure
  (bad key / corrupt token); legacy plaintext values pass through untouched.

> **Where to change:** key source, cipher scheme. **Warning:** losing the key
> makes every stored password unrecoverable — keep a copy safe.

---

#### refresh_service.py

**Quick review:** Manages long-lived refresh sessions stored in SQLite.

**Details:**
- `generate_refresh_token()` — a random opaque token.
- `hash_token(token)` — SHA-256 of the token (only the hash is stored).
- `create_refresh_session(db, user, device_info)` — inserts a `refresh_sessions`
  row (token hash, expiry from `REFRESH_TOKEN_EXPIRE_DAYS`).
- `validate_refresh_token(db, token)` — finds the session by token hash, checks
  it is not revoked/expired; returns the session.
- `rotate_refresh_session(db, session, device_info)` — revokes the used session
  and issues a new one (refresh-token rotation).
- `revoke_session(db, session)` / `revoke_all_sessions(db, user_id)` — logout
  (single session or all).
- `list_sessions(db, user_id)` — active sessions for the "my sessions" view.

> **Where to change:** refresh TTL, rotation policy, adding device metadata.

---

#### rbac.py

**Quick review:** Role → permission mapping and helpers.

**Details:**
- `ROLE_PERMISSIONS` — dict of role names (Employee, Manager, HR, Payroll, IT,
  Admin) → lists of permission strings (e.g. `employees.read`, `admin.access`,
  `payroll.manage`, `attendance.read_all`, …).
- `get_user_permissions(db, user)` — union of permissions across the user's roles.
- `has_permission(permissions, required)` — membership check.
- `assign_role(db, user, role_name)` — makes the user's role exactly match the
  given role name (replaces existing roles). Used by account management so the
  admin-chosen account type is reflected in the user's permissions.
- `seed_roles_and_permissions(db)` — idempotently inserts each role and its
  permissions into the `roles` / `permissions` / `role_permissions` tables.

> **Where to change:** permission names, role mapping, adding new roles.

---

#### dependencies.py

**Quick review:** FastAPI dependencies that protect routes.

**Details:**
- `get_authenticated_user(...)` — **the standard route guard.** Extracts the
  bearer token, verifies the access JWT via `verify_access_token`, loads the
  `User` from the DB, rejects inactive accounts. 401 if missing/invalid/expired.
- `extract_bearer_token(authorization)` — strips the `Bearer ` prefix.
- `require_permission(permission_name)` — factory returning a dependency that
  403s unless the user holds the given permission.
- `require_admin(...)` — depends on `get_authenticated_user`; 403 unless the
  user holds `admin.access`.

> **Where to change:** the standard route guards, adding new permission gates.

---

#### routes.py

**Quick review:** The `/api/auth/*` endpoints (login, refresh, logout, sessions).

**Details — endpoints:**
- `POST /api/auth/login` — verifies credentials (with throttle), creates an
  access token + a refresh session; returns an `AuthResponse`.
- `POST /api/auth/refresh` — validates the refresh token, rotates it, returns a
  new access + refresh pair (`RefreshResponse`).
- `POST /api/auth/logout` — revokes the caller's refresh session.
- `GET /api/auth/me (via /api/me)` / `GET /api/auth/sessions` — session list.
- `DELETE /api/auth/sessions/{id}` — revoke one session.

Helper functions in file: `find_user_by_username`, `credentials_valid`,
`extract_device_info`.

> **Where to change:** login/refresh/logout logic, response fields, device info.

---

### database (folder)

#### connection.py

**Quick review:** Creates the SQLAlchemy engine, session factory, and the
`Base` ORM class; exposes the `get_db` FastAPI dependency.

**Details:**
- `engine = create_engine(DATABASE_URL, connect_args=DATABASE_CONNECT_ARGS, future=True)`
- `SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)`
- `class Base(DeclarativeBase)` — all ORM models inherit from this.
- `get_db()` — yields a session to a route and **always closes it** in a
  `finally` block. This is the `Depends(get_db)` used across routers.

> **Where to change:** usually nothing here. If you swap DB engines, most changes
> are in `config.py` (DATABASE_URL) and adding the driver package.

---

#### models.py

**Quick review:** Defines all ORM tables (9 business + 6 auth). This is the
**schema contract** the app expects. See `docs/database.md` for the full
column-level reference.

**Details — business tables:**
- `employees` — hub table; PK `employee_id`. Relationships to credentials,
  attendance, leave_balances, leave_history, payroll_structures, payslips.
- `credentials` — legacy login accounts (source for the `users` seed);
  PK + FK `employee_id` (1:1). Fields: username, password (Fernet ciphertext,
  see `auth/creds.py`), account_type, account_status.
- `attendance`, `leave_balances`, `leave_history`, `payroll_structures`,
  `payslips`, `services`, `documents` — see `docs/database.md`.

**Details — auth tables:**
- `users` — application login accounts; PK `id`, FK `employee_id`, `username`
  (unique), `password` (Fernet ciphertext, see `auth/creds.py`), `password_hash`
  (placeholder), `account_status`,
  `created_at`; `roles` and `refresh_sessions` relationships.
- `roles` — named role (`name` unique). Linked to users and permissions.
- `permissions` — fine-grained permission (`name` unique).
- `user_roles`, `role_permissions` — association join tables.
- `refresh_sessions` — `token_hash` (unique), `user_id`, timestamps
  (`created_at`, `expires_at`, `revoked_at`, `last_used_at`), `device_info`.

> **Where to change:** if you add/modify columns or tables, or change the schema
> to match an external office DB.

---

#### crud.py

**Quick review:** All the SQL queries the app uses plus the response-shape
serializers. Routes call these, and `main.py` does not contain queries.

**Details — query helpers (all read):**
- `get_employee(db, employee_id)`, `get_payroll_structure(db, employee_id)`
- `get_leave_balance(db, employee_id)`
- `get_attendance_for_month` / `get_attendance_for_year` / `get_attendance_range`
- `get_leave_requests_for_month` / `get_leave_requests`
- `get_payslip` / `get_payslips_for_year`

**Details — serializers (build response dicts):**
- `structure_to_dict(structure)`, `calc_salary(structure)` (computes gross/net).
- `employee_dict(emp)` — rebuilds nested `profiles/contacts/locations` shape.
- `attendance_row_dict(row)`, `attendance_summary(items)` — counts + total hours.
- `leave_request_dict(r)`, `balance_dict(b)`, `employee_list_item(emp)`.

> **Where to change:** query logic, salary calculation, filtering, or response
> shape. **Important:** the frontend depends on these shapes — change carefully.

---

#### seed_users.py

**Quick review:** Migrates the legacy `credentials` table into the new `users`
authentication table and assigns each user a default role.

**Details:**
- `seed_users(db)` — for each credential, create or update a `User` (employee_id,
  username, password, account_status, created_at) and assign a role.
- `assign_default_role(db, user, account_type)` — admin accounts get the Admin
  role, everyone else gets Employee. Preserves an existing admin role.

> **Where to change:** how users are provisioned, default role assignment.

---

### schemas (folder)

#### schemas.py

**Quick review:** Pydantic request/response models for auth.

**Details:**
- Requests: `LoginRequest` (username, password), `RefreshRequest` (refresh_token),
  `LogoutRequest` (refresh_token),
  `AccountCreateRequest` (employee_id, username, password, account_type,
  account_status), `AccountUpdateRequest` (all optional: employee_id, username,
  password, account_type, account_status).
- Responses: `AuthResponse` (access_token, refresh_token, token_type, expires_in,
  employee_id, account_type, account_status), `RefreshResponse` (access_token,
  refresh_token, token_type, expires_in).

> **Where to change:** add new request/response schemas whenever you add a
> body-accepting endpoint.

---

### utils (folder)

#### helpers.py

**Quick review:** Small shared utilities — bearer-token extraction and
short-lived signed file links.

**Details:**
- `extract_token(authorization)` — strips a `Bearer ` prefix.
- `sign_file_link(relative_path)` — builds `"<path>|<expiry>|<signature>"` using
  HMAC-SHA256 with `FILE_LINK_SECRET` and `FILE_LINK_TTL_SECONDS`.
- `verify_file_link(token)` — validates a signed link. Orchestrator that calls:
  - `parse_token(token)` — split into path/expiry/signature.
  - `is_expired(expires_at)` — expiry check.
  - `has_valid_signature(path, expires_at, signature)` — HMAC compare.
  - `is_allowed_path(relative_path)` — top-level folder must be in
    `ALLOWED_STORAGE_ROOTS`.
  Returns the path if valid, else `None`.
- `compute_signature(unsigned_token)` — the HMAC-SHA256 digest.

> **Where to change:** file-link format, TTL, signature algorithm, allowed roots.

---

### routes (folder)

These route files protect their endpoints with
`get_authenticated_user` (any logged-in user) or `require_admin` (admin only),
and use `user.employee_id` from the authenticated user.

#### employees.py

**Details — endpoints:**
- `GET /api/me` — authenticated user's own profile (returns `account_type` from
  the user's primary role).
- `GET /api/employees` — list of all employees (summaries).
- `GET /api/employees/{employee_id}` — **public directory view** for any logged-in
  user: only `name`, `department`, `job_title`, `email`, `extension`, `floor`,
  `desk_number` (no phone/joining date/employment details).
- `GET /api/admin/employees` — same as list, but requires admin.
- `GET /api/admin/employees/{employee_id}` — admin full record.

All use `employee_dict` / `employee_list_item` / `public_employee_dict` from crud,
and `get_employee`.

---

#### attendance.py

**Details — endpoints:**
- `GET /api/attendance?year=&month=` — own attendance for a month + summary
  (defaults: `year=2026`, `month=current month`).
- `GET /api/attendance/range?from=YYYY-MM-DD&to=YYYY-MM-DD` — own attendance
  between two dates + summary (validates dates, `to >= from`).
- `GET /api/admin/attendance/{employee_id}?year=` — admin attendance for a year.

Helpers in file: `validate_range_dates`, `parse_range_dates`. Summaries come from
`attendance_summary` in crud.

---

#### leaves.py

**Details — endpoints:**
- `GET /api/leaves/balance` — own leave balance.
- `GET /api/leaves/history?year=&month=` — own leave requests for a month.
- `GET /api/leaves/overview` — balance + all requests + status counts.
- `GET /api/admin/leaves/{employee_id}` — admin overview for one employee.

Helpers in file: `build_request_list`, `build_status_counts`.

---

#### payroll.py

**Details — endpoints:**
- `GET /api/salary/structure` — own salary structure with computed gross/net.
- `GET /api/salary/payslip?year=&month=` — own payslip enriched with salary.
- `GET /api/admin/payslips/{employee_id}?year=` — all payslips for the year.
- `GET /api/admin/salary/{employee_id}?year=` — structure + per-month payslips.

Helpers in file: `build_month_payslip`, `build_year_slips`. Salary computed via
`calc_salary` from crud.

---

#### documents.py

**Details — endpoints:**
- `GET /api/services` — company services directory.
- `GET /api/documents?category=` — document registry (optional category filter).
- `GET /api/documents/file-url?path=` — returns a **signed, short-lived URL**
  that serves the file. Guards the top-level folder against
  `ALLOWED_STORAGE_ROOTS` (404 if not allowed).
- `GET /api/documents/file?token=` — actually serves the file. Checks the signed
  token (403 if invalid/expired), verifies the file exists (404), then returns a
  `FileResponse`. Serves **inline** (no `filename=`), so PDFs **open in the tab**
  instead of downloading.

Helpers in file: `service_dict`, `document_dict`.

> **Where to change (services/docs):** directory content, file serving (inline vs
> download), storage roots, signed-link behavior. Uses `utils/helpers.py`.

---

#### accounts.py

**Quick review:** Admin-only account management. Admins can view every login
account (passwords are decrypted on the way out — the stored form is Fernet
ciphertext), create new accounts for employees, and edit existing ones.

**Details — endpoints (all require `require_admin`):**
- `GET /api/admin/accounts` — list all accounts. Each item includes `user_id`,
  `employee_id`, `name` (from employees), `username`, **`password`**,
  `account_type`, `account_status`, `created_at`.
- `GET /api/admin/accounts/{user_id}` — a single account incl. its password.
- `POST /api/admin/accounts` — create an account. Validates: username required &
  unique, password required, `account_type` in (Admin/Employee),
  `account_status` in (Active/Inactive). **Employee ID is never rejected: if the
  ID does not exist yet, an Employee row is auto-created with the ID itself as
  the default name.** The only conflict is a duplicate — the same `employee_id`
  cannot own two accounts (409 "Duplicate employee ID").
- **Every credential change is also mirrored into the legacy `credentials`
  table** (`_sync_credential`): `credentials` is the source of truth that
  reseeds `users` on startup (`database/seed_users.py`), so admin-created
  accounts survive restarts and appear in `credentials`. Passwords are
  transformed with `encrypt_password()` from `auth/creds.py` wherever they are
  stored. Only credentials are
  touched — employee data (attendance, salary, etc.) is never modified here.
- `PUT /api/admin/accounts/{user_id}` — partial update of username, password,
  account_type, account_status or employee link. Re-pointing to a new
  employee_id auto-creates the Employee row if missing (same rule as POST).
  Duplicate username/employee → 409. **Self-protection:** an admin cannot
  deactivate or demote their own account (prevents locking out the last admin).

- `DELETE /api/admin/accounts/{user_id}` — **delete credentials only.** Removes
  the `users` row, its role links, refresh sessions and the `credentials`
  mirror; the `employees` business record is left untouched. An admin cannot
  delete their own account (400). Unknown account → 404.

Helpers in file: `_normalise_account_type`, `_normalise_account_status`,
`_ensure_employee`, `_sync_credential`, `_account_dict`. Uses `assign_role`
from `auth/rbac.py`.

> **Deactivating an account (`account_status: Inactive`):** the user is rejected
> at login (403) and refresh (403), and **already-issued access tokens are
> rejected immediately** on their next request because
> `get_authenticated_user` re-checks `account_status` on every call.

---

## 4. Endpoint map (all routes)

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET  | `/api/health` | none | liveness check |
| POST | `/api/auth/login` | none | login → access + refresh tokens |
| POST | `/api/auth/refresh` | none (refresh token) | rotate refresh → new pair |
| POST | `/api/auth/logout` | user + refresh token | revoke refresh session |
| GET  | `/api/auth/sessions` | user | list my sessions |
| DELETE | `/api/auth/sessions/{id}` | user | revoke one session |
| GET  | `/api/me` | user | own profile |
| GET  | `/api/employees` | user | employee list |
| GET  | `/api/employees/{id}` | user | single employee — public view only |
| GET  | `/api/admin/employees` | admin | employee list |
| GET  | `/api/admin/employees/{id}` | admin | single employee |
| GET  | `/api/attendance` | user | own attendance (month) |
| GET  | `/api/attendance/range` | user | own attendance (date range) |
| GET  | `/api/admin/attendance/{id}` | admin | employee attendance (year) |
| GET  | `/api/leaves/balance` | user | own leave balance |
| GET  | `/api/leaves/history` | user | own leave requests (month) |
| GET  | `/api/leaves/overview` | user | own leave overview |
| GET  | `/api/admin/leaves/{id}` | admin | employee leave overview |
| GET  | `/api/salary/structure` | user | own salary structure |
| GET  | `/api/salary/payslip` | user | own payslip (month) |
| GET  | `/api/admin/payslips/{id}` | admin | employee payslips (year) |
| GET  | `/api/admin/salary/{id}` | admin | employee salary overview |
| GET  | `/api/services` | user | services directory |
| GET  | `/api/documents` | user | documents registry |
| GET  | `/api/documents/file-url` | user | signed file URL |
| GET  | `/api/documents/file` | token | serve file (inline) |
| POST | `/api/chat` | user | grounded PDF answer from enabled docs (payload: `question`, optional `document_id`) |
| GET  | `/api/admin/accounts` | admin | list all accounts (passwords decrypted) |
| GET  | `/api/admin/accounts/{id}` | admin | one account (password decrypted) |
| POST | `/api/admin/accounts` | admin | create a login account |
| PUT  | `/api/admin/accounts/{id}` | admin | edit an account (partial) |
| DELETE | `/api/admin/accounts/{id}` | admin | delete credentials only (employee row kept) |

---

## 4A. AI / RAG system

The AI assistant answers **only** from the admin-enabled PDF documents stored in
ChromaDB (`database/chroma_db/`). It never answers from personal / structured
(SQLite) records — questions about the employee's own balance, salary or
attendance are deflected to the HR portal rather than guessed. All answers are
grounded in retrieved document excerpts with citations.

**Pipeline per question** (orchestrated by `rag/rag_service.py`):

```
question
  -> complexity + personal/greeting detection        (rag/query_router.py)
  -> safety cache lookup (keyed by enabled-doc set)  (rag/cache.py)
  -> vector retrieval over ChromaDB                  (rag/retriever.py)
  -> rerank / dedup / compress / confidence          (rag/reranker.py)
  -> cost-aware model selection + adaptive tokens    (rag/model_router.py,
                                                      rag/token_manager.py)
  -> generation with escalation + smart failover     (rag/generator.py)
  -> grounding validation + escalation decision      (rag/validator.py)
```

**Dynamic model discovery** (`rag/model_registry.py`): on startup the app asks
the Gemini API which text-generation models exist, classifies each into a
capability tier (LIGHT / GENERAL / STRONG), and builds a live fallback chain.
This is why model names are not hardcoded to a single version — e.g. the retired
`gemini-2.5-flash` is excluded automatically and replaced by whatever is
currently available (the `-latest` aliases are preferred). A single unavailable
model never crashes startup or the chat endpoint.

**Cost-aware routing** (`rag/model_router.py`): simple questions use the cheapest
healthy model first (flash-lite), normal ones the general flash model, and
complex/critical ones the strongest (pro). Failover (`rag/model_health.py`)
tracks per-model success/failure with cool-downs, and `rag/generator.py` moves
to the next healthy model instead of retrying a dead one — the employee never
sees a model/API error.

**Other properties:**
- **Grounding:** the model is told to answer only from the excerpts; if the
  evidence is insufficient it says so honestly (verified against the live API).
- **Security:** retrieved documents are treated as untrusted data (prompt-
  injection protection lives in `rag/prompts.py`); private data is never shown.
- **Escalation** (`rag/validator.py`) only for genuinely difficult/low-confidence
  answers — never a second call on every easy reply.
- **Caching** (`rag/cache.py`) reuses safe, non-personal answers and is
  invalidated when the enabled-document set changes (fingerprint keyed).
- **Guardrails** in `config.py`: `AI_MAX_GEMINI_CALLS`, `AI_MAX_RETRIES`,
  `AI_HEALTH_*`, `AI_CACHE_TTL_SECONDS`.

**Entry point:** `POST /api/chat` → `routes/chat.py` → `rag.rag_service.answer_question`.
Internal errors are logged server-side and returned as a friendly "try again"
message — never leaked to the client.

---

## 5. How to run / test

```bash
# From the backend folder
python main.py          # server on http://127.0.0.1:8000
```

Interactive API docs: `http://127.0.0.1:8000/docs` (Swagger) or `/redoc`.

**Test login:** admin `saria` / `saria` (employee `EMP003`). `POST /api/auth/login`
returns `{access_token, refresh_token, token_type, expires_in, employee_id,
account_type, account_status}`.

Send the **access token** as `Authorization: Bearer <access_token>` for protected
endpoints. When it expires (~20 min), call `POST /api/auth/refresh` with the
`refresh_token` to get a new pair (the old refresh token is rotated/revoked).

**Rebuild the DB** (careful — this resets data): `python import_db.py` from the
backend folder. The auth tables are created and seeded automatically on the next
app startup.

> **Frontend note:** the frontend currently reads `login.token` from the old
> login response. For the new auth it must use `login.access_token` (and store
> `login.refresh_token` for refresh/logout).

---

## 6. Common change scenarios

| I want to…                                   | Change here                                       |
|----------------------------------------------|---------------------------------------------------|
| Point at another DB (Postgres/Oracle)        | `.env` → `DATABASE_URL`; install driver           |
| Add a new endpoint                           | new/existing file in `routes/`, + `main.py` include_router |
| Add a new table/column                       | `database/models.py` (+ crud helpers)             |
| Change an API response shape                  | `database/crud.py` serializers (be careful)       |
| Change access-token expiry / JWT keys        | `.env` (JWT_* settings, JWT_PRIVATE_KEY)          |
| Change refresh-token lifetime                | `.env` → `REFRESH_TOKEN_EXPIRE_DAYS`              |
| Add a new permission / role                  | `auth/rbac.py` (ROLE_PERMISSIONS, seed)           |
| Change which routes need auth / admin        | `routes/*.py` — swap the dependency               |
| Change login throttle / lockout              | `config.py` + `auth/security.py`                  |
| Change password storage / encryption key     | `auth/creds.py` (key: `CREDENTIALS_KEY` or `backend/.credentials.key`) |
| Change CORS / server port / host             | `config.py` + `main.py`                           |
| Make PDFs download again                     | `routes/documents.py` — add `filename=` to FileResponse |
| Change which files can be served             | `config.py` → `ALLOWED_STORAGE_ROOTS`             |
| Add a body to a request                      | `schemas/schemas.py` + route                       |
| Manage login accounts (create/edit/view pw)  | `routes/accounts.py` + `auth/rbac.py` (`assign_role`) |
| Change the Gemini model candidates / failover | `config.py` → `GEMINI_*` model + `AI_*` guardrails |
| Change retrieval quality (chunk count, threshold) | `config.py` → `RAG_TOP_K`, `RAG_SCORE_THRESHOLD`, `RAG_FINAL_CONTEXT_CHUNKS` |
| Change AI cost/reliability limits            | `config.py` → `AI_MAX_GEMINI_CALLS`, `AI_MAX_RETRIES`, `AI_HEALTH_*`, `AI_CACHE_TTL_SECONDS` |
| Change how answers are generated / routed    | `rag/` — `model_router.py`, `generator.py`, `validator.py`, `prompts.py` |
