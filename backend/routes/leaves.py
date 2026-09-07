"""Leave endpoints.

Routes receive the request, validate input, ask the database/crud helpers for
data, and return the result. Leave summarisation and request building live in
the crud helpers / business functions so the routes stay thin.
"""
from datetime import datetime

from fastapi import APIRouter, Depends

from auth.dependencies import get_authenticated_user, require_admin
from database.connection import get_db
from database.crud import (
    balance_dict,
    get_leave_balance,
    get_leave_requests,
    get_leave_requests_for_month,
    leave_request_dict,
)

router = APIRouter()


# Returns the authenticated employee's own leave balance.
# Takes: none.
# Returns: a dict containing the employee's leave balance.
@router.get("/api/leaves/balance")
def get_my_leave_balance(user=Depends(get_authenticated_user), db=Depends(get_db)):
    employee_id = user.employee_id

    balance = get_leave_balance(db, employee_id)

    if not balance:
        return {"employee_id": employee_id, "balance": {}}

    return {"employee_id": employee_id, "balance": balance_dict(balance)}


# Returns the authenticated employee's leave requests for one month.
# Takes:
#   year - the year to query.
#   month - the month to query (defaults to the current month).
# Returns: a dict containing the month's leave requests.
@router.get("/api/leaves/history")
def get_my_leave_history(
    user=Depends(get_authenticated_user),
    year: int = 2026,
    month: int | None = None,
    db=Depends(get_db),
):
    if month is None:
        month = datetime.now().month

    employee_id = user.employee_id

    rows = get_leave_requests_for_month(db, employee_id, year, month)

    requests = build_request_list(rows)

    return {"employee_id": employee_id, "requests": requests}


# Returns the authenticated employee's full leave overview: balance, all
# requests, and counts by status.
# Takes: none.
# Returns: a dict with balance, requests, and status counts.
@router.get("/api/leaves/overview")
def get_my_leave_overview(user=Depends(get_authenticated_user), db=Depends(get_db)):
    employee_id = user.employee_id

    balance_row = get_leave_balance(db, employee_id)

    if balance_row:
        balance = balance_dict(balance_row)
    else:
        balance = {}

    rows = get_leave_requests(db, employee_id)

    requests = build_request_list(rows)
    requests.sort(key=lambda item: item.get("from", "") or "", reverse=True)

    counts = build_status_counts(requests)

    return {
        "employee_id": employee_id,
        "balance": balance,
        "requests": requests,
        "counts": counts,
    }


# Admin: returns the full leave overview for a single employee.
# Takes: employee_id - the employee's unique ID.
# Returns: a dict with balance, requests, and status counts.
@router.get("/api/admin/leaves/{employee_id}")
def admin_get_leave_overview(employee_id: str, _=Depends(require_admin), db=Depends(get_db)):
    balance_row = get_leave_balance(db, employee_id)

    if balance_row:
        balance = balance_dict(balance_row)
    else:
        balance = {}

    rows = get_leave_requests(db, employee_id)

    requests = build_request_list(rows)
    requests.sort(key=lambda item: item.get("from", "") or "", reverse=True)

    counts = build_status_counts(requests)

    return {
        "employee_id": employee_id,
        "balance": balance,
        "requests": requests,
        "counts": counts,
    }


def build_request_list(leave_rows):
    """Convert leave request database rows into plain dicts.

    Takes: leave_rows - a sequence of LeaveRequest objects.
    Returns: a list of dicts in the original JSON request shape.
    """
    requests = []

    for row in leave_rows:
        item = leave_request_dict(row)
        requests.append(item)

    return requests


def build_status_counts(requests):
    """Count leave requests by their status.

    Takes: requests - a list of leave request dicts.
    Returns: a dict with total, pending, approved, and rejected counts.
    """
    status_lower = []

    for request in requests:
        status = str(request.get("status", "")).lower()
        status_lower.append(status)

    counts = {
        "total": len(requests),
        "pending": status_lower.count("pending"),
        "approved": status_lower.count("approved"),
        "rejected": status_lower.count("rejected"),
    }

    return counts
