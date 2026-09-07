"""Admin account-management endpoint tests.

Covers the /api/admin/accounts routes: listing (with passwords), creating,
editing, the admin guards, and the deactivation effect (a deactivated account
cannot log in). Temporary accounts are removed from the database afterwards.
"""
import pytest

from conftest import ADMIN, EMPLOYEE, auth_header

from auth.creds import is_encrypted
from auth.security import verify_password
from database.connection import SessionLocal
from database.models import Credential, Employee, User
from sqlalchemy import select


@pytest.fixture
def temp_employee():
    """Create a throwaway employee used for account creation tests."""
    import time

    db = SessionLocal()
    emp_id = f"TEMPE{int(time.time())}"
    try:
        e = Employee(employee_id=emp_id, first_name="Temp", last_name="Acct")
        db.add(e)
        db.commit()
        yield emp_id
    finally:
        user = db.scalar(select(User).where(User.employee_id == emp_id))
        if user:
            db.delete(user)
        cred = db.get(Credential, emp_id)
        if cred:
            db.delete(cred)
        emp = db.get(Employee, emp_id)
        if emp:
            db.delete(emp)
        db.commit()
        db.close()


@pytest.fixture
def cleanup_account():
    """Return a function that deletes a created account by username."""
    created = []

    def add(username):
        created.append(username)

    yield add

    db = SessionLocal()
    try:
        for username in created:
            user = db.scalar(select(User).where(User.username == username))
            if user:
                cred = db.get(Credential, user.employee_id)
                if cred:
                    db.delete(cred)
                db.delete(user)
        db.commit()
    finally:
        db.close()


def test_list_accounts_admin(client, login_admin):
    """Admins can list every account, including passwords."""
    r = client.get("/api/admin/accounts", headers=auth_header(login_admin["access_token"]))
    assert r.status_code == 200
    accounts = r.json()["accounts"]
    assert len(accounts) >= 30
    first = accounts[0]
    for key in ("user_id", "employee_id", "username", "password", "account_type", "account_status"):
        assert key in first


def test_list_accounts_requires_admin(client, login_employee):
    """Employees are denied access to the account list (403)."""
    r = client.get("/api/admin/accounts", headers=auth_header(login_employee["access_token"]))
    assert r.status_code == 403


def test_list_accounts_requires_token(client):
    """No token means no accounts (401)."""
    assert client.get("/api/admin/accounts").status_code == 401


def test_get_account_includes_password(client, login_admin):
    """A single account response includes the (decrypted) password."""
    r = client.get("/api/admin/accounts/1", headers=auth_header(login_admin["access_token"]))
    assert r.status_code == 200
    assert "password" in r.json()


def test_get_account_missing_returns_404(client, login_admin):
    """Unknown account ids return 404."""
    r = client.get("/api/admin/accounts/999999", headers=auth_header(login_admin["access_token"]))
    assert r.status_code == 404


def test_create_account_flow(client, login_admin, temp_employee, cleanup_account):
    """An admin can create an account, then the new user can log in."""
    h = auth_header(login_admin["access_token"])

    r = client.post(
        "/api/admin/accounts",
        json={
            "employee_id": temp_employee,
            "username": "temp.login",
            "password": "temp-pass",
            "account_type": "Employee",
            "account_status": "Active",
        },
        headers=h,
    )
    assert r.status_code == 200
    created = r.json()
    assert created["username"] == "temp.login"
    assert created["password"] == "temp-pass"
    assert created["account_type"] == "Employee"
    assert created["account_status"] == "Active"
    cleanup_account("temp.login")

    # The credential is mirrored into the legacy credentials table, encrypted.
    db = SessionLocal()
    try:
        cred = db.get(Credential, temp_employee)
        assert cred is not None
        assert cred.username == "temp.login"
        assert is_encrypted(cred.password)
        assert verify_password("temp-pass", cred.password)
        assert cred.password != "temp-pass"
        assert cred.account_type == "user"
        assert cred.account_status == "Active"
    finally:
        db.close()

    # The new account can log in straight away.
    login = client.post("/api/auth/login", json={"username": "temp.login", "password": "temp-pass"})
    assert login.status_code == 200
    assert login.json()["account_type"].lower() == "employee"


def test_create_account_auto_creates_unknown_employee(client, login_admin, cleanup_account):
    """A made-up employee ID is auto-created (with the ID as default name)."""
    import time

    emp_id = f"NOPE{int(time.time())}"
    h = auth_header(login_admin["access_token"])

    r = client.post(
        "/api/admin/accounts",
        json={
            "employee_id": emp_id,
            "username": "temp.auto",
            "password": "x",
            "account_type": "Employee",
            "account_status": "Active",
        },
        headers=h,
    )
    assert r.status_code == 200
    assert r.json()["employee_id"] == emp_id
    assert r.json()["name"] == emp_id
    cleanup_account("temp.auto")

    db = SessionLocal()
    try:
        emp = db.get(Employee, emp_id)
        assert emp is not None
        assert (emp.first_name or "") == emp_id
    finally:
        db.close()

    # The same employee ID cannot own a second account -> duplicate error.
    r2 = client.post(
        "/api/admin/accounts",
        json={
            "employee_id": emp_id,
            "username": "temp.auto2",
            "password": "y",
            "account_type": "Employee",
            "account_status": "Active",
        },
        headers=h,
    )
    assert r2.status_code == 409
    assert "duplicate employee" in r2.json()["detail"].lower()

    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.employee_id == emp_id))
        if user:
            db.delete(user)
        cred = db.get(Credential, emp_id)
        if cred:
            db.delete(cred)
        emp = db.get(Employee, emp_id)
        if emp:
            db.delete(emp)
        db.commit()
    finally:
        db.close()


def test_create_account_rejects_duplicate_username(client, login_admin):
    """A username that already exists returns 409."""
    r = client.post(
        "/api/admin/accounts",
        json={
            "employee_id": "EMP003",
            "username": ADMIN["username"],
            "password": "x",
            "account_type": "Employee",
            "account_status": "Active",
        },
        headers=auth_header(login_admin["access_token"]),
    )
    assert r.status_code == 409


def test_create_account_rejects_bad_type(client, login_admin, temp_employee):
    """An invalid account type returns 400."""
    r = client.post(
        "/api/admin/accounts",
        json={
            "employee_id": temp_employee,
            "username": "temp.badtype",
            "password": "x",
            "account_type": "Superuser",
            "account_status": "Active",
        },
        headers=auth_header(login_admin["access_token"]),
    )
    assert r.status_code == 400


def test_update_account_and_deactivate(client, login_admin, temp_employee, cleanup_account):
    """Editing a password/status works, and deactivation blocks login (403)."""
    h = auth_header(login_admin["access_token"])

    r = client.post(
        "/api/admin/accounts",
        json={
            "employee_id": temp_employee,
            "username": "temp.edit",
            "password": "old-pass",
            "account_type": "Employee",
            "account_status": "Active",
        },
        headers=h,
    )
    assert r.status_code == 200
    user_id = r.json()["user_id"]
    cleanup_account("temp.edit")

    # Change the password and deactivate.
    r2 = client.put(
        f"/api/admin/accounts/{user_id}",
        json={"password": "new-pass", "account_status": "Inactive"},
        headers=h,
    )
    assert r2.status_code == 200
    assert r2.json()["password"] == "new-pass"
    assert r2.json()["account_status"] == "Inactive"

    # Deactivated accounts are rejected at login.
    login = client.post("/api/auth/login", json={"username": "temp.edit", "password": "new-pass"})
    assert login.status_code == 403


def test_admin_cannot_deactivate_self(client, login_admin):
    """An admin cannot mark their own account inactive (400)."""
    me = client.get("/api/auth/me", headers=auth_header(login_admin["access_token"])).json()
    r = client.put(
        f"/api/admin/accounts/{me['user_id']}",
        json={"account_status": "Inactive"},
        headers=auth_header(login_admin["access_token"]),
    )
    assert r.status_code == 400


def test_admin_cannot_demote_self(client, login_admin):
    """An admin cannot remove their own admin role (400)."""
    me = client.get("/api/auth/me", headers=auth_header(login_admin["access_token"])).json()
    r = client.put(
        f"/api/admin/accounts/{me['user_id']}",
        json={"account_type": "Employee"},
        headers=auth_header(login_admin["access_token"]),
    )
    assert r.status_code == 400


def test_admin_cannot_delete_self(client, login_admin):
    """An admin cannot delete their own account (400)."""
    me = client.get("/api/auth/me", headers=auth_header(login_admin["access_token"])).json()
    r = client.delete(
        f"/api/admin/accounts/{me['user_id']}",
        headers=auth_header(login_admin["access_token"]),
    )
    assert r.status_code == 400


def test_delete_account_removes_credentials_only(client, login_admin, temp_employee, cleanup_account):
    """Deleting an account removes the login + credentials but keeps the employee."""
    h = auth_header(login_admin["access_token"])

    r = client.post(
        "/api/admin/accounts",
        json={
            "employee_id": temp_employee,
            "username": "temp.del",
            "password": "x",
            "account_type": "Employee",
            "account_status": "Active",
        },
        headers=h,
    )
    assert r.status_code == 200
    user_id = r.json()["user_id"]
    cleanup_account("temp.del")

    # Deleting the account.
    r2 = client.delete(f"/api/admin/accounts/{user_id}", headers=h)
    assert r2.status_code == 200
    assert r2.json()["status"] == "deleted"

    db = SessionLocal()
    try:
        assert db.get(User, user_id) is None          # login gone
        assert db.get(Credential, temp_employee) is None   # credentials gone
        assert db.get(Employee, temp_employee) is not None  # employee kept
    finally:
        db.close()

    # The deleted login can no longer authenticate.
    login = client.post("/api/auth/login", json={"username": "temp.del", "password": "x"})
    assert login.status_code == 401


def test_delete_missing_account_returns_404(client, login_admin):
    """Deleting an unknown account returns 404."""
    r = client.delete(
        "/api/admin/accounts/999999",
        headers=auth_header(login_admin["access_token"]),
    )
    assert r.status_code == 404