"""Endpoint coverage test: every route returns an expected status.

Each protected route is exercised with an employee token (self-service) and,
where applicable, an admin token (admin endpoints). Employee self-endpoints
should be 200 for the employee; admin endpoints should be 403 for a non-admin.
"""
from conftest import ADMIN, EMPLOYEE, auth_header


def _headers(token):
    return auth_header(token)


def test_public_endpoints(client):
    """Health and login-style public routes."""
    assert client.get("/api/health").status_code == 200


def test_employee_self_endpoints(client, login_employee):
    """All self-service endpoints return 200 for a logged-in employee."""
    h = _headers(login_employee["access_token"])

    employee_paths = [
        "/api/me",
        "/api/attendance?year=2026&month=1",
        "/api/attendance/range?from=2026-01-01&to=2026-01-07",
        "/api/leaves/balance",
        "/api/leaves/history?year=2026&month=1",
        "/api/leaves/overview",
        "/api/salary/structure",
        "/api/salary/payslip?year=2026&month=1",
        "/api/services",
        "/api/documents",
        "/api/employees",
        "/api/employees/EMP001",
    ]
    for path in employee_paths:
        r = client.get(path, headers=h)
        assert r.status_code == 200, f"expected 200 for {path}, got {r.status_code}"


def test_unauth_protected_endpoints_rejected(client):
    """Protected routes reject requests with no token (401)."""
    for path in ["/api/me", "/api/employees", "/api/attendance?year=2026&month=1"]:
        assert client.get(path).status_code == 401, f"expected 401 for {path}"


def test_admin_endpoints_for_employee(client, login_employee):
    """Admin endpoints reject a regular employee (403)."""
    h = _headers(login_employee["access_token"])
    admin_paths = [
        "/api/admin/employees",
        "/api/admin/employees/EMP001",
        "/api/admin/attendance/EMP001?year=2026",
        "/api/admin/leaves/EMP001",
        "/api/admin/payslips/EMP001?year=2026",
        "/api/admin/salary/EMP001?year=2026",
    ]
    for path in admin_paths:
        r = client.get(path, headers=h)
        assert r.status_code == 403, f"expected 403 for {path}, got {r.status_code}"


def test_admin_endpoints_for_admin(client, login_admin):
    """Admin endpoints succeed for an admin (200)."""
    h = _headers(login_admin["access_token"])
    admin_paths = [
        "/api/admin/employees",
        "/api/admin/employees/EMP003",
        "/api/admin/attendance/EMP003?year=2026",
        "/api/admin/leaves/EMP003",
        "/api/admin/payslips/EMP003?year=2026",
        "/api/admin/salary/EMP003?year=2026",
    ]
    for path in admin_paths:
        r = client.get(path, headers=h)
        assert r.status_code == 200, f"expected 200 for {path}, got {r.status_code}"


def test_employee_detail_public_vs_admin(client, login_employee, login_admin):
    """Regular users see only public fields; admins get the full record."""
    pub = client.get("/api/employees/EMP001", headers=_headers(login_employee["access_token"])).json()
    assert "profiles" not in pub and "contacts" not in pub and "locations" not in pub
    assert {"name", "department", "job_title", "email", "extension", "floor", "desk_number"} <= set(pub)

    full = client.get("/api/admin/employees/EMP001", headers=_headers(login_admin["access_token"])).json()
    assert {"profiles", "contacts", "locations"} <= set(full)
