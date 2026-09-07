"""Shared pytest fixtures for the MTM HR Agent backend tests.

These tests run against the REAL application (main.app) and the REAL database
(hr-db.db via DATABASE_URL). Using the app inside a TestClient context manager
triggers the lifespan, which creates/seeds the auth tables and users - exactly
as a real server boot would.

The DB holds 30 users: 4 admins (saria, rabia.tariq, salman.zaidi, anum.haider)
and 26 employees.
"""
import pytest
from fastapi.testclient import TestClient

import main

# Admin and a regular employee for role-based tests.
ADMIN = {"username": "saria", "password": "saria"}
EMPLOYEE = {"username": "umair", "password": "umair"}


@pytest.fixture(scope="session")
def client():
    """A TestClient wrapping the live app (runs the startup lifespan once)."""
    with TestClient(main.app) as c:
        yield c


def try_login(client, username, password):
    """Attempt a login and return the (status_code, json) tuple."""
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    return r.status_code, r.json()


def auth_header(token):
    """Build an Authorization header for an access token."""
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="session")
def login_admin(client):
    """Returns an access token capturing the admin session."""
    status, data = try_login(client, ADMIN["username"], ADMIN["password"])
    assert status == 200, f"admin login failed: {status} {data}"
    return data


@pytest.fixture(scope="session")
def login_employee(client):
    """Returns an access token capturing a regular employee session."""
    status, data = try_login(client, EMPLOYEE["username"], EMPLOYEE["password"])
    assert status == 200, f"employee login failed: {status} {data}"
    return data
