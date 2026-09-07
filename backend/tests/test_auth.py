"""Authentication flow tests: login, invalid credentials, refresh rotation,
logout, and the 401/403 guards on protected endpoints.

These test the real JWT + rotating refresh-token auth (see auth/).
"""
from conftest import ADMIN, auth_header, try_login


def test_valid_login_returns_tokens(client):
    """A valid login must return access + refresh tokens and account info."""
    status, data = try_login(client, ADMIN["username"], ADMIN["password"])
    assert status == 200
    assert data["access_token"]
    assert data["refresh_token"]
    assert data["token_type"] == "bearer"
    assert data["expires_in"] > 0
    assert data["employee_id"] == "EMP003"
    assert data["account_status"] == "Active"


def test_invalid_credentials_rejected(client):
    """Wrong password must return 401 and no tokens."""
    status, data = try_login(client, ADMIN["username"], "wrong-password")
    assert status == 401
    assert "access_token" not in data
    assert data["detail"] == "Invalid username or password"


def test_unknown_user_rejected(client):
    """An unknown username must return 401."""
    status, _ = try_login(client, "ghost.user", "whatever")
    assert status == 401


def test_protected_endpoint_requires_token(client):
    """A protected endpoint with no token must return 401."""
    r = client.get("/api/me")
    assert r.status_code == 401


def test_protected_endpoint_requires_valid_token(client):
    """A bogus token must return 401."""
    r = client.get("/api/me", headers=auth_header("not-a-real-token"))
    assert r.status_code == 401


def test_refresh_rotates_token(client):
    """Using a refresh token must return a new pair and revoke the old one."""
    _, login = try_login(client, ADMIN["username"], ADMIN["password"])
    old_refresh = login["refresh_token"]

    r = client.post("/api/auth/refresh", json={"refresh_token": old_refresh})
    assert r.status_code == 200
    new_pair = r.json()
    assert new_pair["access_token"]
    assert new_pair["refresh_token"]
    assert new_pair["refresh_token"] != old_refresh

    # The old refresh token was rotated -> it must now be rejected.
    r2 = client.post("/api/auth/refresh", json={"refresh_token": old_refresh})
    assert r2.status_code == 401


def test_refresh_rejects_bad_token(client):
    """An invalid refresh token must return 401."""
    r = client.post("/api/auth/refresh", json={"refresh_token": "rubbish"})
    assert r.status_code == 401


def test_logout_revokes_session(client):
    """Logout must succeed for an authenticated user."""
    _, login = try_login(client, ADMIN["username"], ADMIN["password"])
    r = client.post(
        "/api/auth/logout",
        json={"refresh_token": login["refresh_token"]},
        headers=auth_header(login["access_token"]),
    )
    assert r.status_code == 200
    assert r.json()["status"] == "logged_out"
