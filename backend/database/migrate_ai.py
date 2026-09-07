"""Idempotent migration to add AI/RAG columns to the documents table.

This script upgrades an existing SQLite database in place by adding the columns
needed by the RAG feature. It is safe to run any number of times: columns that
already exist are left untouched, and no tables or data are modified.

Run manually with:
    python -m database.migrate_ai
(inside the backend folder) or invoke run_migrations() programmatically, which
the application also calls on startup so new deployments self-migrate.
"""
from sqlalchemy import text

from database.connection import engine

# Column definitions to ensure exist on the documents table.
_AI_COLUMNS = [
    (
        "ai_enabled",
        "BOOLEAN",
        "ALTER TABLE documents ADD COLUMN ai_enabled BOOLEAN DEFAULT 0 NOT NULL",
    ),
    (
        "ai_status",
        "VARCHAR",
        "ALTER TABLE documents ADD COLUMN ai_status VARCHAR(20) DEFAULT 'not_indexed' NOT NULL",
    ),
    (
        "ai_updated_at",
        "VARCHAR",
        "ALTER TABLE documents ADD COLUMN ai_updated_at VARCHAR(40)",
    ),
]


def run_migrations():
    """Add any missing AI columns to the documents table.

    Uses SQLite's PRAGMA table_info to check which columns already exist, then
    ALTERs the table only for those that are missing. Resets nothing - existing
    data is preserved exactly.

    Returns: a list of the column names that were added.
    """
    added = []

    with engine.connect() as connection:
        existing = {
            row["name"]
            for row in connection.execute(
                text("PRAGMA table_info(documents)")
            ).mappings()
        }

        for name, _sql_type, ddl in _AI_COLUMNS:
            if name in existing:
                continue
            connection.execute(text(ddl))
            added.append(name)

        connection.commit()

    return added


if __name__ == "__main__":
    added = run_migrations()
    if added:
        print(f"Added columns: {', '.join(added)}")
    else:
        print("No new columns needed - documents table is up to date.")
