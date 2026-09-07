"""Data-access (CRUD) helpers for the MTM HR Agent.

Holds the small query helpers and the serialization functions that rebuild the
original JSON-shaped response payloads so the frontend stays unchanged.
"""
from sqlalchemy import select

from database.models import (
    Attendance,
    Employee,
    LeaveBalance,
    LeaveRequest,
    Payslip,
    PayrollStructure,
)


def get_employee(db, employee_id: str):
    """Fetch a single employee record by id."""
    return db.scalar(select(Employee).where(Employee.employee_id == employee_id))


def get_payroll_structure(db, employee_id: str):
    """Fetch an employee's payroll structure."""
    return db.scalar(
        select(PayrollStructure).where(PayrollStructure.employee_id == employee_id)
    )


def get_leave_balance(db, employee_id: str):
    """Fetch an employee's leave balance."""
    return db.scalar(
        select(LeaveBalance).where(LeaveBalance.employee_id == employee_id)
    )


def get_attendance_for_month(db, employee_id, year, month):
    """All attendance rows for an employee in a given month."""
    return db.scalars(
        select(Attendance)
        .where(Attendance.employee_id == employee_id)
        .where(Attendance.year == year)
        .where(Attendance.month == month)
    ).all()


def get_attendance_for_year(db, employee_id, year):
    """All attendance rows for an employee in a given year."""
    return db.scalars(
        select(Attendance).where(Attendance.employee_id == employee_id).where(Attendance.year == year)
    ).all()


def get_attendance_range(db, employee_id, from_date, to_date):
    """Attendance rows for an employee between two dates (inclusive)."""
    return db.scalars(
        select(Attendance)
        .where(Attendance.employee_id == employee_id)
        .where(Attendance.date >= from_date.strftime("%Y-%m-%d"))
        .where(Attendance.date <= to_date.strftime("%Y-%m-%d"))
        .order_by(Attendance.date)
    ).all()


def get_leave_requests_for_month(db, employee_id, year, month):
    """Leave requests for an employee in a given month."""
    return db.scalars(
        select(LeaveRequest)
        .where(LeaveRequest.employee_id == employee_id)
        .where(LeaveRequest.year == year)
        .where(LeaveRequest.month == month)
    ).all()


def get_leave_requests(db, employee_id):
    """All leave requests for an employee."""
    return db.scalars(
        select(LeaveRequest).where(LeaveRequest.employee_id == employee_id)
    ).all()


def get_payslip(db, employee_id, year, month):
    """A single payslip for an employee in a given month."""
    return db.scalar(
        select(Payslip)
        .where(Payslip.employee_id == employee_id)
        .where(Payslip.year == year)
        .where(Payslip.month == month)
    )


def get_payslips_for_year(db, employee_id, year):
    """All payslips for an employee in a given year."""
    return db.scalars(
        select(Payslip).where(Payslip.employee_id == employee_id).where(Payslip.year == year)
    ).all()


# ---------------------------------------------------------------------------
# Serialization helpers (rebuild original JSON-shaped payloads)
# ---------------------------------------------------------------------------
def structure_to_dict(structure) -> dict:
    """Convert a PayrollStructure ORM object (or dict) into a flat dict."""
    if not structure:
        return {}
    if isinstance(structure, dict):
        return dict(structure)
    return {
        "currency": structure.currency,
        "basic": structure.basic,
        "housing_allowance": structure.housing_allowance,
        "transport_allowance": structure.transport_allowance,
        "other_allowances": structure.other_allowances,
        "deductions": structure.deductions,
    }


def calc_salary(structure) -> dict:
    """Compute gross and net salary from the salary components instead of the
    stored static values."""
    base = structure_to_dict(structure)
    if not base:
        return {}
    gross = (
        (base.get("basic") or 0)
        + (base.get("housing_allowance") or 0)
        + (base.get("transport_allowance") or 0)
        + (base.get("other_allowances") or 0)
    )
    deductions = base.get("deductions") or 0
    net = max(0, gross - deductions)
    out = dict(base)
    out["gross_salary"] = gross
    out["net_salary"] = net
    return out


def employee_dict(emp: Employee) -> dict:
    """Rebuild the original nested profile/contacts/locations JSON shape.

    Keeps response payloads identical to the previous JSON-based backend so the
    frontend does not need to change.
    """
    return {
        "profiles": {
            "employee_number": emp.employee_number,
            "first_name": emp.first_name,
            "last_name": emp.last_name,
            "department_id": emp.department_id,
            "department": emp.department,
            "job_title": emp.job_title,
            "employment_type": emp.employment_type,
            "employment_status": emp.employment_status,
            "joining_date": emp.joining_date,
        },
        "contacts": {
            "email": emp.email,
            "phone": emp.phone,
            "extension": emp.extension,
        },
        "locations": {
            "floor": emp.floor,
            "desk_number": emp.desk_number,
            "seat_status": emp.seat_status,
        },
    }


def attendance_row_dict(row: Attendance) -> dict:
    """Build the JSON record shape for a single attendance row."""
    return {
        "date": row.date,
        "check_in": row.check_in,
        "check_out": row.check_out,
        "status": row.status,
        "working_hours": row.working_hours,
    }


def attendance_summary(items) -> dict:
    present = sum(1 for x in items if x.get("status") == "Present")
    late = sum(1 for x in items if x.get("status") == "Late")
    absent = sum(1 for x in items if x.get("status") == "Absent")
    leave = sum(1 for x in items if x.get("status") == "Leave")
    off = sum(1 for x in items if x.get("status") == "Off")
    total_hours = round(sum(x.get("working_hours") or 0 for x in items if x.get("working_hours")), 2)
    return {
        "total_days": len(items),
        "present": present,
        "late": late,
        "absent": absent,
        "leave": leave,
        "off": off,
        "total_working_hours": total_hours,
    }


def leave_request_dict(r: LeaveRequest) -> dict:
    """Build the JSON record shape for a leave request."""
    return {
        "leave_id": r.leave_id,
        "employee_id": r.employee_id,
        "type": r.type,
        "from": r.from_date,
        "to": r.to_date,
        "days": r.days,
        "status": r.status,
    }


def balance_dict(b) -> dict:
    return {"annual": b.annual, "sick": b.sick, "casual": b.casual, "unpaid": b.unpaid}


def employee_list_item(emp) -> dict:
    return {
        "employee_id": emp.employee_id,
        "name": f"{emp.first_name or ''} {emp.last_name or ''}".strip(),
        "department": emp.department,
        "job_title": emp.job_title,
        "employment_status": emp.employment_status,
        "email": emp.email,
    }


def public_employee_dict(emp: Employee) -> dict:
    """Build the directory shape shown to regular (non-admin) users.

    Only public contact/desk details are exposed here; the full nested record
    (profiles/contacts/locations) is reserved for admins.
    """
    return {
        "employee_id": emp.employee_id,
        "name": f"{emp.first_name or ''} {emp.last_name or ''}".strip(),
        "department": emp.department,
        "job_title": emp.job_title,
        "email": emp.email,
        "extension": emp.extension,
        "floor": emp.floor,
        "desk_number": emp.desk_number,
    }
