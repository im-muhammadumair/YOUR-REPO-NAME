"""Payroll endpoints.

Routes receive the request, validate input, ask the database/business helpers
for data, and return the result. Salary calculation and payslip dict building
live in the helpers so the routes stay thin.
"""
from datetime import datetime

from fastapi import APIRouter, Depends

from auth.dependencies import get_authenticated_user, require_admin
from database.connection import get_db
from database.crud import (
    calc_salary,
    get_payroll_structure,
    get_payslip,
    get_payslips_for_year,
)

router = APIRouter()


# Returns the authenticated employee's salary structure with computed
# gross and net values.
# Takes: none.
# Returns: a dict containing the employee's salary structure.
@router.get("/api/salary/structure")
def get_my_salary_structure(user=Depends(get_authenticated_user), db=Depends(get_db)):
    employee_id = user.employee_id

    structure = get_payroll_structure(db, employee_id)
    salary = calc_salary(structure)

    return {"employee_id": employee_id, "structure": salary}


# Returns the authenticated employee's payslip for one month, enriched with the
# computed salary amounts.
# Takes:
#   year - the year to query.
#   month - the month to query (defaults to the current month).
# Returns: a dict containing the employee's payslip.
@router.get("/api/salary/payslip")
def get_my_payslip(
    user=Depends(get_authenticated_user),
    year: int = 2026,
    month: int | None = None,
    db=Depends(get_db),
):
    if month is None:
        month = datetime.now().month

    employee_id = user.employee_id

    structure = get_payroll_structure(db, employee_id)
    salary = calc_salary(structure)

    slip = get_payslip(db, employee_id, year, month)

    payslip = build_month_payslip(slip, salary, year, month)

    return {"employee_id": employee_id, "payslip": payslip}


# Admin: returns all payslips for an employee in a given year.
# Takes:
#   employee_id - the employee's unique ID.
#   year - the year to query.
# Returns: a dict listing the employee's payslips.
@router.get("/api/admin/payslips/{employee_id}")
def admin_get_payslips(employee_id: str, _=Depends(require_admin), year: int = 2026, db=Depends(get_db)):
    structure = get_payroll_structure(db, employee_id)
    salary = calc_salary(structure)

    slips = get_payslips_for_year(db, employee_id, year)

    results = build_year_slips(slips, salary)

    return {"employee_id": employee_id, "payslips": results}


# Admin: returns an employee's full salary overview for a year, including the
# salary structure and per-month payslips.
# Takes:
#   employee_id - the employee's unique ID.
#   year - the year to query.
# Returns: a dict with the structure and the employee's payslips.
@router.get("/api/admin/salary/{employee_id}")
def admin_get_salary(employee_id: str, _=Depends(require_admin), year: int = 2026, db=Depends(get_db)):
    structure = get_payroll_structure(db, employee_id)
    salary = calc_salary(structure)

    slips = get_payslips_for_year(db, employee_id, year)

    payslips = build_year_slips(slips, salary)

    return {
        "employee_id": employee_id,
        "year": year,
        "structure": salary,
        "payslips": payslips,
    }


def build_month_payslip(slip, salary, year, month):
    """Build a single payslip dict enriched with computed salary amounts.

    Takes:
      slip - the Payslip object (may be None).
      salary - the computed salary dict (gross/net plus components).
      year - the payslip year.
      month - the payslip month.
    Returns: a dict representing the payslip.
    """
    if slip:
        payslip = {
            "payslip_id": slip.payslip_id,
            "year": year,
            "month": month,
            "status": slip.status,
            "file": slip.file,
        }
    else:
        payslip = {
            "payslip_id": None,
            "year": year,
            "month": month,
            "status": None,
            "file": None,
        }

    payroll_fields = {
        "basic": salary.get("basic"),
        "housing_allowance": salary.get("housing_allowance"),
        "transport_allowance": salary.get("transport_allowance"),
        "other_allowances": salary.get("other_allowances"),
        "gross_salary": salary.get("gross_salary"),
        "net_salary": salary.get("net_salary"),
        "deductions": salary.get("deductions"),
    }

    payslip.update(payroll_fields)

    return payslip


def build_year_slips(slips, salary):
    """Build payslip dicts for all payslips in a year.

    Takes:
      slips - a sequence of Payslip objects.
      salary - the computed salary dict (gross/net plus components).
    Returns: a list of payslip dicts including the month for each.
    """
    results = []

    for slip in slips:
        record = {
            "payslip_id": slip.payslip_id,
            "year": slip.year,
            "month": slip.month,
            "status": slip.status,
            "file": slip.file,
            "gross_salary": salary.get("gross_salary"),
            "net_salary": salary.get("net_salary"),
            "deductions": salary.get("deductions"),
        }

        results.append({"month": slip.month, **record})

    return results
