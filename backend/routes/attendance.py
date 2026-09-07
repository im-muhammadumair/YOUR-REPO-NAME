"""Attendance endpoints.

Routes receive the request, validate input, ask the database/crud helpers for
the data, and return the result. All attendance summarisation (present, late,
absent, hours) lives in the crud helpers so it is shared and testable.
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query

from auth.dependencies import get_authenticated_user, require_admin
from database.connection import get_db
from database.crud import (
    attendance_row_dict,
    attendance_summary,
    get_attendance_for_month,
    get_attendance_for_year,
    get_attendance_range,
)

router = APIRouter()


# Returns an employee's own attendance for one month.
# Takes:
#   year - the year to query.
#   month - the month to query (defaults to the current month).
# Returns: a dict with attendance rows and a summary for that month.
@router.get("/api/attendance")
def get_my_attendance(
    user=Depends(get_authenticated_user),
    year: int = 2026,
    month: int | None = None,
    db=Depends(get_db),
):
    if month is None:
        month = datetime.now().month

    employee_id = user.employee_id

    rows = get_attendance_for_month(db, employee_id, year, month)

    attendance_rows = []

    for row in rows:
        item = attendance_row_dict(row)
        attendance_rows.append(item)

    summary = attendance_summary(attendance_rows)

    return {
        "year": year,
        "month": month,
        "employee_id": employee_id,
        "attendance": attendance_rows,
        "summary": summary,
    }


# Returns an employee's own attendance between two dates (inclusive).
# Takes:
#   from_ - the start date as YYYY-MM-DD.
#   to - the end date as YYYY-MM-DD.
# Returns: a dict with attendance rows and a summary for the range.
# Raises: HTTPException 400 if the dates are invalid or reversed.
@router.get("/api/attendance/range")
def get_my_attendance_range(
    user=Depends(get_authenticated_user),
    from_: str | None = Query(default=None, alias="from"),
    to: str | None = Query(default=None, alias="to"),
    db=Depends(get_db),
):
    validate_range_dates(from_, to)

    from_date, to_date = parse_range_dates(from_, to)

    if to_date < from_date:
        raise HTTPException(status_code=400, detail="'to' must be on or after 'from'")

    employee_id = user.employee_id

    rows = get_attendance_range(db, employee_id, from_date, to_date)

    attendance_rows = []

    for row in rows:
        item = attendance_row_dict(row)
        attendance_rows.append(item)

    summary = attendance_summary(attendance_rows)

    return {
        "employee_id": employee_id,
        "from": from_,
        "to": to,
        "attendance": attendance_rows,
        "summary": summary,
    }


# Admin: returns all attendance for an employee in a given year.
# Takes:
#   employee_id - the employee's unique ID.
#   year - the year to query.
# Returns: a dict with attendance rows and a summary for the year.
@router.get("/api/admin/attendance/{employee_id}")
def admin_get_attendance(
    employee_id: str,
    _=Depends(require_admin),
    year: int = 2026,
    db=Depends(get_db),
):
    rows = get_attendance_for_year(db, employee_id, year)

    attendance_rows = []

    for row in rows:
        item = attendance_row_dict(row)
        attendance_rows.append(item)

    attendance_rows.sort(key=lambda item: item.get("date", ""))

    summary = attendance_summary(attendance_rows)

    return {
        "employee_id": employee_id,
        "year": year,
        "attendance": attendance_rows,
        "summary": summary,
    }


def validate_range_dates(from_value, to_value):
    """Ensure both range dates are provided.

    Takes:
      from_value - the start date string.
      to_value - the end date string.
    Returns: None.
    Raises: HTTPException 400 if either value is missing.
    """
    if not from_value or not to_value:
        raise HTTPException(
            status_code=400,
            detail="from and to are required (YYYY-MM-DD)",
        )


def parse_range_dates(from_value, to_value):
    """Parse the range date strings into datetime objects.

    Takes:
      from_value - the start date string.
      to_value - the end date string.
    Returns: a tuple (from_date, to_date) of datetime objects.
    Raises: HTTPException 400 if either string is not a valid date.
    """
    try:
        from_date = datetime.strptime(from_value, "%Y-%m-%d")
        to_date = datetime.strptime(to_value, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="Dates must be YYYY-MM-DD")

    return from_date, to_date
