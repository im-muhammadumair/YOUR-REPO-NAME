"""All-users test: every user in the database can log in and use the app.

Credential pairs are read straight from the live users table, then each user is
exercised concurrently (login + a few self-service endpoints) to prove the whole
user base works at the same time on the running backend.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest
from conftest import auth_header

from database.connection import SessionLocal
from database.models import User
from sqlalchemy import select


def all_credentials():
    """Return [(username, password)] for every user in the database."""
    db = SessionLocal()
    try:
        rows = db.scalars(select(User)).all()
        return [(u.username, u.password) for u in rows]
    finally:
        db.close()


def _one_user(client, username, password):
    """Login as one user and hit a few endpoints. Returns a result dict."""
    try:
        r = client.post(
            "/api/auth/login",
            json={"username": username, "password": password},
        )
        if r.status_code != 200:
            return {"username": username, "ok": False, "why": f"login {r.status_code}"}

        data = r.json()
        h = auth_header(data["access_token"])

        checks = {
            "me": client.get("/api/me", headers=h).status_code,
            "salary": client.get("/api/salary/structure", headers=h).status_code,
            "attendance": client.get("/api/attendance?year=2026&month=1", headers=h).status_code,
        }
        bad = {k: v for k, v in checks.items() if v != 200}
        return {"username": username, "ok": not bad, "why": bad or "ok"}
    except Exception as e:  # pragma: no cover - defensive
        return {"username": username, "ok": False, "why": repr(e)}


def test_all_users_are_creatable_credentials(client):
    """Sanity: the DB exposes at least a handful of users."""
    creds = all_credentials()
    assert len(creds) >= 1


def test_all_users_can_login_and_use_app(client):
    """Every user in the DB logs in and uses self-service endpoints."""
    creds = all_credentials()
    assert len(creds) > 0, "no users found in the database"

    failures = []
    for username, password in creds:
        result = _one_user(client, username, password)
        if not result["ok"]:
            failures.append(result)

    assert not failures, f"{len(failures)} users failed: {failures}"


def test_all_users_concurrently(client):
    """All users run through the app at the same time (concurrency check)."""
    creds = all_credentials()
    assert len(creds) > 0

    failures = []
    with ThreadPoolExecutor(max_workers=max(8, len(creds))) as pool:
        futures = {
            pool.submit(_one_user, client, username, password): username
            for username, password in creds
        }
        for future in as_completed(futures):
            result = future.result()
            if not result["ok"]:
                failures.append(result)

    assert not failures, f"{len(failures)} users failed under concurrency: {failures}"


@pytest.fixture(scope="session")
def _noop():  # pragma: no cover
    pass
