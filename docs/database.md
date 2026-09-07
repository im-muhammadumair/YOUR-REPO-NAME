# MTM HR Agent — Database Reference

This document describes everything about the databases used by the MTM HR Agent.
It is written for a **database developer** who may need to connect this application
to an external office database, migrate the data, or understand how the current
storage works before changing it.

The data for a real deployment can live "somewhere else" (an office SQL Server,
Oracle, or PostgreSQL instance with tables arranged differently). This guide
explains the **contract** the application expects so you can map an external
schema onto it.

## How this doc is organised

This application keeps **two** databases side by side. Each has its own part:

- **PART A — SQLite** (`database/hr-db.db`): the main application database that
  holds all the structured HR data (employees, attendance, leave balances,
  payroll, documents metadata, auth tables).
- **PART B — ChromaDB** (`database/chroma_db/`): the vector store used only by
  the AI / RAG chat feature. It holds the embedded chunks of the admin-enabled
  PDF documents.
- **PART C — Operations** (shared): smoke tests and file-location references
  that apply to both stores.

> They are **not** one database. There is **no foreign key** between them — they
> are separate engines joined only by a shared `document_id` string (a chunk in
> ChromaDB points back to a `documents` row in SQLite). This link is explained in
> **PART B — B6**.

---

# PART A — SQLite (HR application database)

## 1. Big picture (how the data flows)

```
 frontend (React)  ──HTTP/JSON──▶  backend (FastAPI)  ──SQLAlchemy ORM──▶  database
    (reads JSON                      reads/writes                        (SQLite today,
     response shapes)                via routes ──▶ crud.py ──▶ models      swappable)
```

1. The **frontend** only speaks JSON over HTTP. It does **not** know or care
   where the data lives.
2. The **backend** exposes REST endpoints (`routes/*.py`). Each endpoint calls a
   small query helper in `database/crud.py`.
3. `crud.py` runs SQL through the SQLAlchemy **ORM**. The ORM maps Python
   objects to tables whose schema is defined in `database/models.py`.
4. The ORM looks at `DATABASE_URL` (read from `.env` by `config.py`) to know
   which engine/database to connect to.

> **Key rule:** The application delivers API responses that the frontend depends
> on. `crud.py` contains serialization helpers that build those response shapes.
> The frontend is intentionally never changed. Any new database must be able to
> answer the same logical queries.

> **What lives here vs. in ChromaDB:** SQLite holds the **structured HR data
> and the document registry** (metadata only). The PDF **text chunks and
> vectors** for AI chat live in ChromaDB (PART B). The two are bridged by
> `documents.document_id` ↔ ChromaDB chunk `document_id`.

---

## 2. Connection & configuration (how to point it at another DB)

All database connection settings are in **`backend/.env`**:

```
DATABASE_URL=sqlite:///../database/hr-db.db
```

`config.py` reads this value with `python-dotenv` and resolves relative SQLite
paths against the backend root folder. Change this one line to point the app at
another database, e.g.:

| Target DB        | Example `DATABASE_URL`                                         |
|------------------|----------------------------------------------------------------|
| SQLite (current) | `sqlite:///../database/hr-db.db`                               |
| PostgreSQL       | `postgresql+psycopg://user:pass@localhost:5432/hr_db`          |
| MySQL            | `mysql+pymysql://user:pass@localhost:3306/hr_db`               |
| SQL Server       | `mssql+pyodbc://user:pass@host:1433/hr_db?driver=ODBC+Driver+18`|
| Oracle           | `oracle+oracledb://user:pass@host:1521/?service_name=ORCL`     |

You would also ensure the matching SQLAlchemy driver package is installed and
listed in `requirements.txt`.

**Entry points / files that matter:**

- `backend/config.py` — loads `.env`, exposes `DATABASE_URL`, `engine` args, and all constants.
- `backend/database/connection.py` — builds the SQLAlchemy `engine`, `SessionLocal`, `Base`, and the `get_db` dependency used by routers.
- `backend/database/models.py` — **the schema contract** (tables + columns + relationships).
- `backend/database/crud.py` — the read queries and response-shape serializers the app actually uses.
- `backend/import_db.py` — a one-off maintenance script that built the current SQLite DB.

> If you are swapping the engine to PostgreSQL/SQL Server/Oracle, the column
> types in `models.py` (`String`, `Integer`, `Float`) map fine, but review
> auto-increment handling and any reserved words (e.g. `type`, `file`, `from`,
> `to`, `year`) — `SQLAlchemy` quotes identifiers as needed, so reserve-word
> column names are safe, but a DBA may prefer different column names in the
> physical schema.

---

## 3. Current storage: SQLite file

- **Location:** `database/hr-db.db` (the `database` folder is a *sibling* of the `backend` folder, at the project root).
- **Engine:** SQLite (single-file, serverless), created/opened by SQLAlchemy.
- **Row counts (last build):**

| Table               | Rows  |
|---------------------|-------|
| employees           | 30    |
| credentials         | 30    |
| users               | 31    |
| attendance          | 10950 |
| leave_balances      | 30    |
| leave_history       | 301   |
| payroll_structures  | 30    |
| payslips            | 360   |
| services            | 6     |
| documents           | 23    |

- The original source data is maintained separately and imported into this database.
  `import_db.py` rebuilds the SQLite DB and is idempotent (drops and recreates tables).

---

## 4. Schema (tables, columns, keys, relationships)

All tables are `VARCHAR`/`INTEGER`/`FLOAT`. Dates and times are stored as **text
strings**, not database date/time types.

### 4.1 `employees` — the central table

The hub for people. Almost every other table references it via `employee_id`.

| Column             | Type    | Notes                                         |
|--------------------|---------|-----------------------------------------------|
| `employee_id`      | VARCHAR | **PRIMARY KEY** e.g. `EMP003`                |
| `employee_number`  | VARCHAR | official payroll/HR number                     |
| `first_name`       | VARCHAR |                                               |
| `last_name`        | VARCHAR |                                               |
| `department_id`    | VARCHAR |                                               |
| `department`       | VARCHAR | e.g. `Information Technology`, `Human Resources`, `Finance`… |
| `job_title`        | VARCHAR |                                               |
| `employment_type`  | VARCHAR | `Full-Time`, `Part-Time`, `Contract`          |
| `employment_status`| VARCHAR | `Active` (no other values seen yet)           |
| `joining_date`     | VARCHAR | text date                                     |
| `email`            | VARCHAR |                                               |
| `phone`            | VARCHAR |                                               |
| `extension`        | VARCHAR | office extension                              |
| `floor`            | INTEGER | physical office floor                         |
| `desk_number`      | VARCHAR |                                               |
| `seat_status`      | VARCHAR |                                               |

**Relationships (has many):** `credentials`, `attendance`, `leave_balances`,
`leave_history`, `payroll_structures`, `payslips`.

### 4.2 `credentials` — login accounts

| Column           | Type    | Notes                                              |
|------------------|---------|----------------------------------------------------|
| `employee_id`    | VARCHAR | **PRIMARY KEY**, **FK → employees.employee_id** |
| `username`       | VARCHAR | login name                                         |
| `password`       | VARCHAR | Fernet ciphertext `fcd1$…` (see security note below) |
| `account_type`   | VARCHAR | `admin` or `user`                                  |
| `account_status` | VARCHAR | `Active`                                           |

One-to-one with `employees` (login lives on the employee).

### 4.3 `attendance` — daily punch records

| Column          | Type    | Notes                                             |
|-----------------|---------|---------------------------------------------------|
| `id`            | INTEGER | **PRIMARY KEY**, autoincrement                    |
| `year`          | INTEGER |                                                   |
| `month`         | INTEGER | 1–12                                              |
| `employee_id`   | VARCHAR | **FK → employees.employee_id**                  |
| `date`          | VARCHAR | text date `YYYY-MM-DD`                            |
| `check_in`      | VARCHAR | text time                                         |
| `check_out`     | VARCHAR | text time                                         |
| `status`        | VARCHAR | `Present`, `Late`, `Absent`, `Leave`, `Off`       |
| `working_hours` | FLOAT   | hours worked that day                             |

`year`/`month` are denormalized alongside `date` so month/year queries (the
common frontend pattern) are fast without parsing the text date.

### 4.4 `leave_balances` — remaining leave entitlements

| Column         | Type    | Notes                                  |
|----------------|---------|----------------------------------------|
| `employee_id`  | VARCHAR | **PRIMARY KEY**, **FK → employees**  |
| `annual`       | INTEGER | annual leave days left                |
| `sick`         | INTEGER | sick leave days left                  |
| `casual`       | INTEGER | casual leave days left                |
| `unpaid`       | INTEGER | unpaid leave days left                |

### 4.5 `leave_history` — leave requests

| Column         | Type    | Notes                                        |
|----------------|---------|----------------------------------------------|
| `leave_id`     | VARCHAR | **PRIMARY KEY**                             |
| `year`         | INTEGER |                                              |
| `month`        | INTEGER |                                              |
| `employee_id`  | VARCHAR | **FK → employees.employee_id**             |
| `type`         | VARCHAR | `Annual`, `Sick`, `Casual`, `Unpaid`         |
| `from_date`    | VARCHAR | `from` in the API payload — text date        |
| `to_date`      | VARCHAR | `to` in the API payload — text date          |
| `days`         | INTEGER | number of working days requested             |
| `status`       | VARCHAR | `Pending`, `Approved`, `Rejected`            |

### 4.6 `payroll_structures` — salary components per employee

| Column                  | Type    | Notes                          |
|-------------------------|---------|--------------------------------|
| `employee_id`           | VARCHAR | **PRIMARY KEY**, **FK → employees** |
| `currency`              | VARCHAR |                                 |
| `basic`                 | INTEGER | base salary                    |
| `housing_allowance`     | INTEGER |                                 |
| `transport_allowance`   | INTEGER |                                 |
| `other_allowances`      | INTEGER |                                 |
| `deductions`            | INTEGER | total deductions               |

> **Note:** The app **computes** gross/net salary from these components on the
> fly (`crud.calc_salary`: `gross = basic + housing + transport + other`,
> `net = max(0, gross − deductions)`). Gross/net are **not** stored columns.

### 4.7 `payslips` — generated monthly payslip records

| Column         | Type    | Notes                                   |
|----------------|---------|-----------------------------------------|
| `payslip_id`   | VARCHAR | **PRIMARY KEY**                        |
| `year`         | INTEGER |                                         |
| `month`        | INTEGER |                                         |
| `employee_id`  | VARCHAR | **FK → employees.employee_id**        |
| `deductions`   | INTEGER |                                         |
| `status`       | VARCHAR | `Generated`                             |
| `file`         | VARCHAR | storage-relative path to the PDF/file   |

### 4.8 `services` — office / internal directory

| Column         | Type    | Notes                  |
|----------------|---------|------------------------|
| `service_id`   | VARCHAR | **PRIMARY KEY**       |
| `name`         | VARCHAR |                        |
| `role`         | VARCHAR |                        |
| `department`   | VARCHAR |                        |
| `extension`    | VARCHAR |                        |
| `email`        | VARCHAR |                        |
| `location`     | VARCHAR |                        |
| `hours`        | VARCHAR |                        |

No FK to employees (a service is a department/role, not a person).

### 4.9 `documents` — HR document registry

| Column         | Type    | Notes                                       |
|----------------|---------|---------------------------------------------|
| `document_id`  | VARCHAR | **PRIMARY KEY**                            |
| `name`         | VARCHAR |                                             |
| `category`     | VARCHAR |                                             |
| `file`         | VARCHAR | storage-relative path to the file           |
| `type`         | VARCHAR | file/document type                          |
| `ai_enabled`   | BOOLEAN | whether the doc is enabled for AI chat     |
| `ai_status`    | VARCHAR | indexing state: `not_indexed` / `ready` / `indexing` / `error` |
| `ai_updated_at`| VARCHAR | last index/status change timestamp          |

> The last three columns are added by an idempotent migration
> (`database/migrate_ai.py`) so the existing DB is upgraded in place. The
> document **vectors** themselves live not here but in the ChromaDB vector store
> at `database/chroma_db/` (see **PART B**). Disabling AI keeps vectors in ChromaDB
> (`ai_enabled=false`, status stays `ready`), so re-enabling is instant without
> re-embedding.

---

## 4A. Authentication tables

These tables back the app's login (JWT access tokens + rotating refresh tokens +
RBAC). They are created automatically on app startup
(`Base.metadata.create_all`) and seeded from the `credentials` table
(`database/seed_users.py`, `auth/rbac.py`).

### 4A.1 `users` — application login accounts

| Column           | Type    | Notes                                             |
|------------------|---------|---------------------------------------------------|
| `id`             | INTEGER | **PRIMARY KEY**, autoincrement                    |
| `employee_id`    | VARCHAR | **FK → employees.employee_id**                  |
| `username`       | VARCHAR | login name, **unique**, indexed                   |
| `password`       | VARCHAR | Fernet ciphertext `fcd1$…` (see security note)     |
| `password_hash`  | VARCHAR | reserved for future password hashing (unused now) |
| `account_status` | VARCHAR | `Active`                                          |
| `created_at`     | DATETIME| when the user was created                         |

**Relationships:** many-to-many `roles` (via `user_roles`); one-to-many
`refresh_sessions`.

### 4A.2 `roles` — named roles

| Column | Type    | Notes               |
|--------|---------|---------------------|
| `id`   | INTEGER | **PRIMARY KEY**     |
| `name` | VARCHAR | **unique**, e.g. `Admin`, `Employee`, `Manager`, `HR`, `Payroll`, `IT` |

### 4A.3 `permissions` — fine-grained permissions

| Column | Type    | Notes                              |
|--------|---------|------------------------------------|
| `id`   | INTEGER | **PRIMARY KEY**                    |
| `name` | VARCHAR | **unique**, e.g. `employees.read`, `admin.access`, `payroll.manage` |

### 4A.4 `user_roles` — join table (users ↔ roles)

| Column   | Type    | Notes                        |
|----------|---------|------------------------------|
| `user_id`| INTEGER | **FK → users.id**, part of PK |
| `role_id`| INTEGER | **FK → roles.id**, part of PK |

### 4A.5 `role_permissions` — join table (roles ↔ permissions)

| Column         | Type    | Notes                            |
|----------------|---------|----------------------------------|
| `role_id`      | INTEGER | **FK → roles.id**, part of PK    |
| `permission_id`| INTEGER | **FK → permissions.id**, part of PK |

### 4A.6 `refresh_sessions` — long-lived refresh-token sessions

| Column          | Type    | Notes                                             |
|-----------------|---------|---------------------------------------------------|
| `id`            | INTEGER | **PRIMARY KEY**, autoincrement                    |
| `user_id`       | INTEGER | **FK → users.id**, indexed                      |
| `token_hash`    | VARCHAR | SHA-256 of the refresh token, **unique**, indexed |
| `created_at`    | DATETIME| when the session was created                      |
| `expires_at`    | DATETIME| when the session expires                          |
| `revoked_at`    | DATETIME| set on logout/rotation (NULL = still valid)       |
| `last_used_at`  | DATETIME| last refresh time                                 |
| `device_info`   | VARCHAR | optional client/device description                |

Only the hashed refresh token is stored — the raw token is never persisted.

---

## 5. Relationships summary (ER view)

```
                         ┌─────────────┐
                         │  employees  │  (PK employee_id)
                         └──────┬──────┘
        ┌───────────┬───────────┼───────────┬───────────┬──────────┬────────────┐
        │           │           │           │           │          │            │
   credentials  attendance  leave_balances leave_history payroll_  payslips
   (1:1)        (1:N)       (1:1)           (1:N)        structures (1:N)
                                                        (1:1)
```

- **1:1** with `employees`: `credentials`, `leave_balances`, `payroll_structures`.
- **1:N** with `employees`: `attendance`, `leave_history`, `payslips`.
- **Standalone** (no employee FK): `services`, `documents`.

The unifying key everywhere is **`employee_id`** (a business key string such as
`EMP003`). If you map this onto another office DB, `employee_id` is the join key
to an employee master table.

> The auth tables (`users`, `roles`, `permissions`, `user_roles`,
> `role_permissions`, `refresh_sessions`) are **not** in this ER view — they
> hang off `users.employee_id` → `employees`, not off the business tables
> directly. See section 4A.

---

## 6. Data conventions / enums

| Field                      | Allowed / observed values                                   |
|----------------------------|-------------------------------------------------------------|
| `credentials.account_type` | `admin`, `user`                                             |
| `credentials.account_status`| `Active`                                                   |
| `attendance.status`        | `Present`, `Late`, `Absent`, `Leave`, `Off`                 |
| `leave_history.type`       | `Annual`, `Sick`, `Casual`, `Unpaid`                        |
| `leave_history.status`     | `Approved`, `Pending`, `Rejected`                           |
| `payslips.status`          | `Generated`                                                 |
| `employees.employment_type`| `Full-Time`, `Part-Time`, `Contract`                        |
| `employees.employment_status`| `Active`                                                  |
| `employees.department`     | `Information Technology`, `Human Resources`, `Finance`, `Marketing`, `Sales`, `Operations`, `Administration`, `Customer Support`, `Product`, `Legal` |
| Dates / times              | Stored as **text** (`YYYY-MM-DD`, etc.), not DB date types  |

> These strings are **matched literally** in `crud.py` (e.g. `status == "Present"`,
> `"Late"`, `"Leave"`, `"Off"`, `"Absent"`). If the office DB uses different
> spellings (e.g. `PRESENT`, `late`, `PTO`), you must either map them in a view
> or adjust the comparison logic — the current code is case-sensitive.

---

## 7. How the application queries the data (read patterns)

The frontend calls these logical queries (all in `database/crud.py`). To connect
an external DB, it must be able to answer the same questions:

| Purpose                          | Query pattern (logical)                                  |
|----------------------------------|-----------------------------------------------------------|
| Load a single employee           | `employees WHERE employee_id = ?`                         |
| Employee list (cards/directory)  | all employees, projected to id/name/department/job/status/email |
| Employee profile (nested JSON)   | single employee → flattened into `profiles`/`contacts`/`locations` |
| Attendance for a month           | `attendance WHERE employee_id AND year=? AND month=?`     |
| Attendance for a year            | `attendance WHERE employee_id AND year=?`                 |
| Attendance date range            | `attendance WHERE employee_id AND date BETWEEN from AND to` (text compare) |
| Attendance summary               | count rows by `status`; sum `working_hours`               |
| Leave balance                    | `leave_balances WHERE employee_id = ?`                    |
| Leave requests (month / all)     | `leave_history WHERE employee_id [AND year AND month]`    |
| Payroll structure                | `payroll_structures WHERE employee_id = ?`                |
| Computed salary                  | `calc_salary(...)` — sums components client/server-side   |
| Single payslip (month)           | `payslips WHERE employee_id AND year AND month`           |
| Payslips for a year              | `payslips WHERE employee_id AND year`                     |
| Services directory               | all `services`                                            |
| Documents registry               | all `documents`                                           |

The app mostly **reads**. Writes are limited (it's a self-service HR portal whose
authoritative data lives in the office HR/payroll systems).

---

## 8. Security notes for the DB developer

- `credentials.password` (and the migrated `users.password`) — these hold the
  credential used to log into the app. **Treat as sensitive.** They are stored as
  **reversible Fernet ciphertext** (prefix `fcd1$`) — not plaintext, but not
  one-way hashed either, because the admin "Manage accounts" panel must be able
  to display the password again. Decryption key: `CREDENTIALS_KEY` env var or the
  key file `backend/.credentials.key` (auto-generated, `0600`). Losing the key
  makes all stored passwords unrecoverable.
  - Login: `auth/security.py::verify_password` decrypts the stored value before
    the constant-time compare; legacy plaintext values (no `fcd1$` prefix) still
    work.
  - Admin UI: `routes/accounts.py` decrypts via `auth/creds.py::decrypt_password`
    so the API returns the plaintext password to admins.
  - New/edited credentials are always written with `encrypt_password()`.
- Access control is **role/permission based** (see `auth/rbac.py`). The `users`
  table links a login to an employee, and the `user_roles` / `role_permissions`
  join tables grant permissions. The `admin.access` permission gates admin-only
  endpoints (`require_admin` in `auth/dependencies.py`).
- `refresh_sessions.token_hash` — only a SHA-256 hash of the refresh token is
  stored; the raw token lives only in the client. Never log or persist the raw
  refresh token.
- `service_id`, `document_id`, `file` — `file` columns are storage-relative paths.
  File serving uses short-lived signed links (`utils/helpers.py`); the signed
  token only allows paths whose top-level folder is in the configured
  `ALLOWED_STORAGE_ROOTS`. Keep those paths in sync with the storage layout.

---

## 9. Swapping to an external office DB (integration guide)

To connect this app to an existing office database (Postgres / SQL Server /
Oracle) instead of the SQLite file, follow this checklist:

1. **Confirm the logical contract.** Map each of the business tables above to the
   office schema. Not every office table lines up 1:1, so create database
   **views** that present the external data in the exact shape the app expects
   (exact table/column names, or update `models.py` to reflect the real names).

2. **Set `DATABASE_URL`** in `backend/.env` to the office connection string and
   ensure the corresponding SQLAlchemy driver is installed.

3. **Align the `employee_id` join key.** Make sure the office employee master
   exposes an `employee_id`-style key you can join attendance, leave, and
   payroll on.

4. **Align enums and formats.** Convert office codes to the app's expected
   strings (`Present`/`Late`/`Absent`/`Leave`/`Off`, `Annual`/`Sick`/`Casual`/
   `Unpaid`, leave statuses, `account_type` admin/user) — ideally in the view.

5. **Decide read-only vs. write.** The app is primarily read-only for the office
   data, so a set of read-only **views** is often the safest integration point.

6. **Preserve payload shapes.** Do not change `crud.py` serializers / response
   shapes; the frontend depends on them.

7. **Test against the endpoints** (see PART C — C1) after the swap.

---

# PART B — ChromaDB vector store (AI / RAG)

## B1. Overview & where it lives

**What it is.** ChromaDB is a separate, local **vector database** used only by the
AI / RAG chat feature. It stores the embedded text chunks of the PDF documents
that an admin has enabled for AI. It does **not** store employee/personal HR
data. Its content is driven by the `documents` table in SQLite (PART A, §4.9): a
managed document is **enabled** (`ai_enabled=true`) and **indexed**
(`ai_status=ready`) only when its chunks are present here.

**Where it lives / what files.** `database/chroma_db/` (a ChromaDB
persistent-store folder, separate from the SQLite HR file):

| File/dir in `database/chroma_db/`        | Purpose                                        |
|-------------------------------------------|------------------------------------------------|
| `chroma.sqlite3`                          | the actual ChromaDB **database file** (tables in B3 below) |
| `<uuid>/` (e.g. `b921d9e2-…`)            | segment files holding the float vectors/BLOBs  |

It is configured via `config.CHROMA_DIR` and managed by the code in `backend/rag/`.

## B2. Collection(s)

ChromaDB organises vectors into named collections. There is currently a single
collection: `hr_documents`. All enabled documents share it, and queries are
filtered at runtime by the set of enabled `document_id`s.

| Collection      | Purpose                                    | Managed by                      |
|-----------------|--------------------------------------------|---------------------------------|
| `hr_documents`  | one collection holding every enabled PDF's text chunks | `rag/ingestion.py` (`collection()`) |

## B3. The actual tables inside `chroma.sqlite3`

ChromaDB is itself backed by a SQLite file, so a developer inspecting it with
`sqlite3 database/chroma_db/chroma.sqlite3` will see the tables below. Most are
ChromaDB **internal plumbing** — the tables that hold your **application data**
are `embeddings`, `embedding_metadata`, `embedding_fulltext_search_content`,
`collections`, and `embeddings_queue`.

| Table                                   | Meaning / application relevance                          | Row count* |
|-----------------------------------------|-----------------------------------------------------------|------------|
| `collections`                           | one row per vector collection (`id`, `name`, `dimension`, `config_json_str`) | 1 (`hr_documents`, dim **1536**) |
| `embeddings`                            | **the chunks**: one row per vector (`id`, `embedding_id`, `segment_id`, `seq_id`, `created_at`) | 9 |
| `embeddings_queue`                      | pending/ingested chunks as JSON (`id`, `vector` BLOB, `encoding`, `metadata` JSON) | 9 |
| `embedding_metadata`                    | **chunk metadata**: flattened key/value rows (`id`, `key`, `string_value`, …) | 81 (9 chunks × 9 keys) |
| `embedding_fulltext_search_content`     | the chunk **text** for keyword search (FTS) (`id`, `c0`) | 9 |
| `embedding_fulltext_search_data/_idx/_docsize/_config` | FTS5 internal index plumbing | — |
| `segments`                              | storage segments (`id`, `type`, `scope`, `collection`) | 2 |
| `segment_metadata`                      | per-segment metadata (empty here)                        | 0 |
| `collection_metadata`                   | per-collection metadata (empty here)                     | 0 |
| `databases` / `tenants`                 | ChromaDB multi-tenant plumbing                           | 1 / 1 |
| `max_seq_id`                            | last write sequence per segment                          | 1 |
| `migrations`                            | ChromaDB schema-version bookkeeping                      | 18 |
| `embeddings_queue_config` / `maintenance_log` / `acquire_write` | internal config/locking                    | — |

\* Row counts are the **current live state** (DOC016 only).

## B4. Metadata keys per chunk

Each chunk's metadata is flattened into `embedding_metadata` (9 rows per chunk)
and is also stored as a JSON object in `embeddings_queue.metadata`. The 9 keys:

| Metadata key        | Example value                            | Description                              |
|---------------------|------------------------------------------|------------------------------------------|
| `chroma:document`   | `"employee as part of his/her basic pay …"` | the **chunk text** (also in the FTS table) |
| `document_id`       | `DOC016`                                 | **links to SQLite `documents.document_id`** |
| `document_name`     | `Payroll & Salary Structure`             | mirrors SQLite `documents.name`           |
| `category`          | `finance`                                | mirrors SQLite `documents.category`       |
| `source_file`       | `finance/Payroll & Salary Structure.pdf` | storage-relative file path                |
| `chunk_index`       | `0` … `8`                                | order of the chunk within its PDF         |
| `page`              | `1` … `7`                                | PDF page the chunk came from              |
| `embedding_model`   | `gemini-embedding-001`                   | which model produced the vector           |
| `fingerprint`       | `baea3a27d73c8e5af65ccf3c6cea5e68`       | content hash (change detection / skip re-index) |

## B5. Vector storage

The float embedding itself is **never** in a readable column — it is stored as a
BLOB in the segment vector files (under the `<uuid>/` subfolder) and as the
`vector` BLOB in `embeddings_queue`, with `encoding=FLOAT32` and dimension
`1536`.

## B6. Linkage to SQLite

There is **no foreign key** between the two databases — they are separate
engines. They are joined logically by the shared `document_id` string:
`rag/retriever.py` reads the enabled `document_id`s from SQLite, then queries
ChromaDB filtered to those ids. Every ChromaDB chunk's `document_id` must match
a row in SQLite `documents` (PART A, §4.9).

## B7. Data entries (example on a fresh import)

After enabling DOC016 for AI and indexing it, the stores look like:

```
SQLite  documents      :  (DOC016, 'Payroll & Salary Structure', 'finance', ai_enabled=True,  ai_status='ready')
ChromaDB collections   :  (id='9cf577a9-…', name='hr_documents', dimension=1536)
ChromaDB embeddings    :  (id=1..9, embedding_id='DOC016:0'..'DOC016:8')
ChromaDB metadata      :  81 rows = 9 chunks × 9 metadata keys (document_id=DOC016 each)
ChromaDB databases     :  (id='00000000-…', name='default_database', tenant='default_tenant')
```

Not every SQLite document is in ChromaDB: only `ai_enabled=True` **and**
`ai_status='ready'` ones are searchable. Documents that are **disabled** keep
their ChromaDB chunks (so re-enabling is instant, no re-embed); deleting a
document removes both its SQLite row and its ChromaDB chunks.

## B8. Maintenance / resets

- Rebuild existing indexes: delete `database/chroma_db/` and re-index the PDFs
  (e.g. via the admin UI / re-running ingestion) — the SQLite `documents` table
  is not the source used to regenerate embeddings for already-deleted vectors.
- If ChromaDB is missing but `documents` says `ready`, re-enable or re-upload to
  rebuild the index.

---

# PART C — Operations (shared)

## C1. Smoke-test checklist (after any DB change)

Login uses a credentialed account, e.g. admin `saria` / `saria`
(`employee_id = EMP003`, assigned the `Admin` role). A quick pass should hit:

- `POST /api/auth/login` → `{access_token, refresh_token, …, account_type}`
- `GET /api/me` (with `Authorization: Bearer <access_token>`)
- `GET /api/attendance?year=<Y>&month=<M>`
- `GET /api/leaves/balance`, `/api/leaves/history?year=&month=`, `/api/leaves/overview`
- `GET /api/salary/structure`, `/api/salary/payslip?year=&month=`
- `GET /api/services`, `/api/documents`, `/api/employees`
- admin: `/api/admin/employees`, attendance/leaves/salary/payslips for an employee ID
- AI/RAG (if a PDF is enabled): `POST /api/chat` returns a grounded `{answer, sources, grounded}`.
  Verify the enabled `document_id` has matching chunks in `database/chroma_db/`.

All core endpoints should return `200`.

## C2. File locations summary

| Path (project root `3. currently working/`)            | Purpose                                   |
|--------------------------------------------------------|-------------------------------------------|
| `backend/.env`                                         | DB connection string (`DATABASE_URL`)     |
| `backend/config.py`                                    | loads `.env`, constants                   |
| `backend/database/connection.py`                       | engine / session / `get_db`               |
| `backend/database/models.py`                           | **schema contract** (tables)              |
| `backend/database/crud.py`                             | queries + response-shape serializers   |
| `backend/import_db.py`                                 | rebuilds SQLite DB                      |
| `database/hr-db.db`                                    | current SQLite database file (PART A)   |
| `database/chroma_db/`                                  | ChromaDB vector store (AI/RAG chunks, PART B) |
| `backend/rag/` (ingestion, embeddings, retriever, etc.)| reads/writes the ChromaDB store         |
| `backend/routes/*.py`                                  | HTTP endpoints                           |
| `backend/auth/` (keys, jwt_service, rbac, refresh_service, dependencies, routes) | auth logic (JWT/RBAC/refresh) |
| `backend/database/seed_users.py`                       | migrates `credentials` → `users` + roles |
| `backend/utils/helpers.py`                             | file-link signing, token extraction       |
