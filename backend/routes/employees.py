"""Employee endpoints.

Each route:
  1. Receives the request.
  2. Validates input.
  3. Calls a service/database helper.
  4. Returns the result.
"""
from fastapi import APIRouter, Depends, HTTPException

from auth.dependencies import get_authenticated_user, require_admin
from auth.jwt_service import primary_role_name
from database.connection import get_db
from database.crud import (
    employee_dict,
    employee_list_item,
    get_employee,
    public_employee_dict,
)
from database.models import Employee
from sqlalchemy import select

router = APIRouter()


# Returns the authenticated employee's own profile, contacts, and location.
# Takes: user - the authenticated user from get_authenticated_user().
# Returns: a dict with the employee's identity and profile details.
# Side effect: none.
@router.get("/api/me")
def get_my_profile(user=Depends(get_authenticated_user), db=Depends(get_db)):
    from auth.routes import is_developer_identity

    if is_developer_identity(user.username):
        return {
            "employee_id": None,
            "account_type": primary_role_name(user),
            "name": "Developer",
            "profile": {"first_name": "Developer", "last_name": ""},
            "contacts": [],
            "locations": [],
        }

    employee_id = user.employee_id

    employee = get_employee(db, employee_id)

    if not employee:
        raise HTTPException(status_code=404, detail="Employee record not found")

    data = employee_dict(employee)
    profile = data["profiles"]

    full_name = f"{profile.get('first_name', '')} {profile.get('last_name', '')}".strip()

    return {
        "employee_id": employee_id,
        "account_type": primary_role_name(user),
        "name": full_name,
        "profile": profile,
        "contacts": data["contacts"],
        "locations": data["locations"],
    }


# Lists all employees with a short summary of each.
# Takes: none.
# Returns: a dict whose "employees" value is the list of summaries.
@router.get("/api/employees")
def list_employees(_=Depends(get_authenticated_user), db=Depends(get_db)):
    employees = db.scalars(select(Employee)).all()

    result = []

    for employee in employees:
        summary = employee_list_item(employee)
        result.append(summary)

    return {"employees": result}


# Returns the public directory record of a single employee by ID.
# Regular (non-admin) users only see public contact/desk details; the full
# nested record is reserved for admins (see /api/admin/employees/{id}).
# Takes: employee_id - the employee's unique ID.
# Returns: a dict with the employee's public details.
# Raises: HTTPException 404 if the employee does not exist.
@router.get("/api/employees/{employee_id}")
def get_employee_detail(employee_id: str, _=Depends(get_authenticated_user), db=Depends(get_db)):
    employee = get_employee(db, employee_id)

    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")

    return public_employee_dict(employee)


# Admin: lists all employees with a short summary of each.
# Takes: none (requires admin role).
# Returns: a dict whose "employees" value is the list of summaries.
@router.get("/api/admin/employees")
def admin_list_employees(_=Depends(require_admin), db=Depends(get_db)):
    employees = db.scalars(select(Employee)).all()

    result = []

    for employee in employees:
        summary = employee_list_item(employee)
        result.append(summary)

    return {"employees": result}


# Admin: returns the full record of a single employee by ID.
# Takes: employee_id - the employee's unique ID.
# Returns: a dict containing the employee's full record.
# Raises: HTTPException 404 if the employee does not exist.
@router.get("/api/admin/employees/{employee_id}")
def admin_get_employee(employee_id: str, _=Depends(require_admin), db=Depends(get_db)):
    employee = get_employee(db, employee_id)

    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")

    data = employee_dict(employee)

    return {"employee_id": employee_id, **data}
