"""One-user happy-path test: a single user logs in and walks the whole app.

This mirrors what one human user does in the UI: login, load their profile,
check attendance, leaves, salary, documents, then logout.
"""
from conftest import EMPLOYEE, ADMIN, auth_header


def test_single_employee_full_flow(client):
    """A regular employee can log in and use all self-service endpoints."""
    r = client.post(
        "/api/auth/login",
        json={"username": EMPLOYEE["username"], "password": EMPLOYEE["password"]},
    )
    assert r.status_code == 200
    login = r.json()
    h = auth_header(login["access_token"])

    me = client.get("/api/me", headers=h)
    assert me.status_code == 200
    assert me.json()["employee_id"] == login["employee_id"] == "EMP001"
    assert me.json()["account_type"] in ("Employee", "Admin")

    for path, name in [
        ("/api/attendance?year=2026&month=1", "attendance"),
        ("/api/leaves/balance", "leave balance"),
        ("/api/leaves/overview", "leave overview"),
        ("/api/salary/structure", "salary structure"),
        ("/api/salary/payslip?year=2026&month=1", "payslip"),
        ("/api/services", "services"),
        ("/api/documents", "documents"),
    ]:
        resp = client.get(path, headers=h)
        assert resp.status_code == 200, f"{name} endpoint failed: {resp.status_code}"

    # Refresh the session, then log out.
    ref = client.post("/api/auth/refresh", json={"refresh_token": login["refresh_token"]})
    assert ref.status_code == 200

    out = client.post(
        "/api/auth/logout",
        json={"refresh_token": ref.json()["refresh_token"]},
        headers=h,
    )
    assert out.status_code == 200
    assert out.json()["status"] == "logged_out"


def test_single_admin_full_flow(client):
    """An admin can additionally reach the admin-only endpoints."""
    r = client.post("/api/auth/login", json=ADMIN)
    assert r.status_code == 200
    h = auth_header(r.json()["access_token"])

    for path in [
        "/api/admin/employees",
        "/api/admin/employees/EMP003",
        "/api/admin/attendance/EMP003?year=2026",
        "/api/admin/leaves/EMP003",
        "/api/admin/payslips/EMP003?year=2026",
        "/api/admin/salary/EMP003?year=2026",
    ]:
        resp = client.get(path, headers=h)
        assert resp.status_code == 200, f"{path} failed: {resp.status_code}"
