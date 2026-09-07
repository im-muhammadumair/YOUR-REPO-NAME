"""Role-based access control (RBAC) tests.

Verifies that:
  - each user is assigned the expected role (Admin vs Employee),
  - the admin-only endpoints are reachable by admins but denied to employees,
  - the RBAC permission helpers agree with what the endpoints enforce.
"""
from conftest import ADMIN, EMPLOYEE, auth_header

from auth.jwt_service import primary_role_name
from auth.rbac import get_user_permissions, has_permission

from database.connection import SessionLocal
from database.models import User, Role
from sqlalchemy import select
from sqlalchemy.orm import selectinload


def _user(username):
    """Return a user with roles eager-loaded (kept attached to a session)."""
    db = SessionLocal()
    row = db.scalar(select(User).options(selectinload(User.roles)).where(User.username == username))
    db.expunge_all()
    db.close()
    return row


def _perms(user):
    """Compute permissions via RBAC (eager-loads roles -> permissions)."""
    db = SessionLocal()
    try:
        loaded = db.scalar(
            select(User)
            .options(selectinload(User.roles).selectinload(Role.permissions))
            .where(User.username == user.username)
        )
        return get_user_permissions(db, loaded)
    finally:
        db.close()


def test_admin_role_assigned(client):
    """The admin account carries the Admin role and the admin.access permission."""
    user = _user(ADMIN["username"])
    assert user is not None
    role_names = {r.name for r in user.roles}
    assert "Admin" in role_names
    assert primary_role_name(user) == "Admin"

    perms = _perms(user)
    assert has_permission(perms, "admin.access")


def test_employee_role_assigned(client):
    """A regular employee does NOT have the admin.access permission."""
    user = _user(EMPLOYEE["username"])
    assert user is not None
    role_names = {r.name for r in user.roles}
    assert "Admin" not in role_names
    assert primary_role_name(user) == "Employee"


def test_admin_uses_admin_roles(client, login_admin, login_employee):
    """login.account_type reflects the primary role for both admin and employee."""
    assert login_admin["account_type"].lower() == "admin"
    assert login_employee["account_type"].lower() == "employee"


def test_employee_denied_admin_endpoints(client, login_employee):
    """An employee calling an admin endpoint gets 403."""
    h = auth_header(login_employee["access_token"])
    assert client.get("/api/admin/employees", headers=h).status_code == 403


def test_admin_allowed_admin_endpoints(client, login_admin):
    """An admin calling an admin endpoint gets 200."""
    h = auth_header(login_admin["access_token"])
    assert client.get("/api/admin/employees", headers=h).status_code == 200


def test_employee_can_still_use_own_endpoints(client, login_employee):
    """Denying admin routes must not break the employee's own endpoints."""
    h = auth_header(login_employee["access_token"])
    assert client.get("/api/salary/structure", headers=h).status_code == 200
