"""Build the SQLite database (hr-db.db) from the existing JSON data files.

This is a one-off maintenance script. It reads every JSON collection in the
data `database/` folder (a sibling of the backend folder) and writes the records
into the ORM tables using the exact schema defined in database/models.py.

Re-running this script drops and rebuilds all tables, so it is idempotent.
"""
import json
from pathlib import Path

from auth.creds import encrypt_password
from database.connection import Base, SessionLocal, engine
from database.models import (
    Attendance,
    Credential,
    Document,
    Employee,
    LeaveBalance,
    LeaveRequest,
    Payslip,
    PayrollStructure,
    Service,
)

# The folder holding all source JSON data lives one level above the backend.
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR.parent / "database"


# ---------------------------------------------------------------------------
# Small reading helpers
# ---------------------------------------------------------------------------
def read_json_file(path, default):
    """Read and parse a JSON file into a Python object.

    Takes:
      path - the path to the JSON file.
      default - the object returned when the file is missing or empty.
    Returns: the parsed Python object, or the default.
    """
    try:
        with open(path, "r", encoding="utf-8") as file:
            content = file.read().strip()

            if not content:
                return default

            return json.loads(content)

    except FileNotFoundError:
        return default

    except json.JSONDecodeError:
        return default


def read_keyed_collection(relative_path, id_key=None):
    """Read a JSON file that maps keys to embedded records.

    Takes:
      relative_path - the file path relative to the data folder.
      id_key - when set, returns the embedded dict keyed by that field.
    Returns: a dict of records keyed by id (or the raw dict when no id_key).
    """
    path = DATA_DIR / relative_path
    data = read_json_file(path, {})

    if not id_key:
        return data

    records = data.get(id_key, {})
    return records or {}


def read_list_collection(relative_path, list_key):
    """Read a JSON file that contains a list under a given key.

    Takes:
      relative_path - the file path relative to the data folder.
      list_key - the key holding the list of records.
    Returns: a list of records (empty list when absent or malformed).
    """
    path = DATA_DIR / relative_path
    data = read_json_file(path, {})

    if not isinstance(data, dict):
        return []

    records = data.get(list_key, [])
    return records or []


def read_plain_list(relative_path):
    """Read a JSON file that is itself a list.

    Takes: relative_path - the file path relative to the data folder.
    Returns: a list of records (empty list when malformed).
    """
    path = DATA_DIR / relative_path
    data = read_json_file(path, [])

    if not isinstance(data, list):
        return []

    return data


def get_monthly_files(relative_dir):
    """Collect all JSON files under each year subfolder of a data directory.

    Takes: relative_dir - the directory path relative to the data folder.
    Returns: a list of JSON file paths, sorted by year then file name.
    """
    directory = DATA_DIR / relative_dir

    if not directory.exists():
        return []

    files = []

    for year_dir in sorted(directory.iterdir()):
        if not year_dir.is_dir():
            continue

        for file_path in sorted(year_dir.glob("*.json")):
            files.append(file_path)

    return files


# ---------------------------------------------------------------------------
# Employees
# ---------------------------------------------------------------------------
def build_employee_record(employee_id, employee_data):
    """Build an Employee ORM object from one employee's JSON record.

    Takes:
      employee_id - the employee's unique ID.
      employee_data - the raw JSON record for that employee.
    Returns: an Employee object.
    """
    profile = employee_data.get("profiles", {})
    contact = employee_data.get("contacts", {})
    location = employee_data.get("locations", {})

    employee_number = profile.get("employee_number")
    first_name = profile.get("first_name")
    last_name = profile.get("last_name")
    department_id = profile.get("department_id")
    department = profile.get("department")
    job_title = profile.get("job_title")

    employment_type = profile.get("employment_type")
    employment_status = profile.get("employment_status")
    joining_date = profile.get("joining_date")

    email = contact.get("email")
    phone = contact.get("phone")
    extension = contact.get("extension")

    floor = location.get("floor")
    desk_number = location.get("desk_number")
    seat_status = location.get("seat_status")

    return Employee(
        employee_id=employee_id,
        employee_number=employee_number,
        first_name=first_name,
        last_name=last_name,
        department_id=department_id,
        department=department,
        job_title=job_title,
        employment_type=employment_type,
        employment_status=employment_status,
        joining_date=joining_date,
        email=email,
        phone=phone,
        extension=extension,
        floor=floor,
        desk_number=desk_number,
        seat_status=seat_status,
    )


def build_employees(employees_data):
    """Build Employee ORM objects for every employee in the data.

    Takes: employees_data - a dict keyed by employee ID.
    Returns: a list of Employee objects.
    """
    employees = []

    for employee_id, employee_data in employees_data.items():
        employee = build_employee_record(employee_id, employee_data)
        employees.append(employee)

    return employees


def import_employees(db):
    """Load and save all employees.

    Takes: db - the database session.
    Returns: None.
    """
    employees_data = read_keyed_collection("employees/employees.json")
    employees = build_employees(employees_data)

    db.add_all(employees)


# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------
def build_credential_record(employee_id, credential_data):
    """Build a Credential ORM object from one credential's JSON record.

    Takes:
      employee_id - the employee's unique ID.
      credential_data - the raw JSON credential record.
    Returns: a Credential object.
    """
    username = credential_data.get("username")
    password = credential_data.get("password")
    account_type = credential_data.get("account_type")
    account_status = credential_data.get("account_status")

    return Credential(
        employee_id=employee_id,
        username=username,
        password=encrypt_password(password),
        account_type=account_type,
        account_status=account_status,
    )


def build_credentials(credentials_data):
    """Build Credential ORM objects for every credential in the data.

    Takes: credentials_data - a dict keyed by employee ID.
    Returns: a list of Credential objects.
    """
    credentials = []

    for employee_id, credential_data in credentials_data.items():
        credential = build_credential_record(employee_id, credential_data)
        credentials.append(credential)

    return credentials


def import_credentials(db):
    """Load and save all credentials.

    Takes: db - the database session.
    Returns: None.
    """
    credentials_data = read_keyed_collection(
        "credentials/private.json",
        id_key="credentials",
    )
    credentials = build_credentials(credentials_data)

    db.add_all(credentials)


# ---------------------------------------------------------------------------
# Attendance
# ---------------------------------------------------------------------------
def build_attendance_records(month_data, year, month):
    """Build Attendance ORM objects for every record in one month's file.

    Takes:
      month_data - the parsed monthly attendance JSON.
      year - the year this data belongs to.
      month - the month this data belongs to.
    Returns: a list of Attendance objects.
    """
    attendance_rows = []

    records = month_data.get("records", [])

    for record in records:
        employee_id = record.get("employee_id")

        daily_entries = record.get("attendance", [])

        for entry in daily_entries:
            date = entry.get("date")
            check_in = entry.get("check_in")
            check_out = entry.get("check_out")
            status = entry.get("status")
            working_hours = entry.get("working_hours")

            attendance = Attendance(
                year=year,
                month=month,
                employee_id=employee_id,
                date=date,
                check_in=check_in,
                check_out=check_out,
                status=status,
                working_hours=working_hours,
            )

            attendance_rows.append(attendance)

    return attendance_rows


def import_attendance(db):
    """Load and save all attendance data across every month.

    Takes: db - the database session.
    Returns: None.
    """
    attendance_files = get_monthly_files("attendance")

    attendance_rows = []

    for file_path in attendance_files:
        month_data = read_json_file(file_path, {})

        year = month_data.get("year")
        month = month_data.get("month")

        rows = build_attendance_records(month_data, year, month)
        attendance_rows.extend(rows)

    db.add_all(attendance_rows)


# ---------------------------------------------------------------------------
# Leave balances
# ---------------------------------------------------------------------------
def build_leave_balance_record(employee_id, balance_data):
    """Build a LeaveBalance ORM object from one balance JSON record.

    Takes:
      employee_id - the employee's unique ID.
      balance_data - the raw JSON balance record.
    Returns: a LeaveBalance object.
    """
    annual = balance_data.get("annual")
    sick = balance_data.get("sick")
    casual = balance_data.get("casual")
    unpaid = balance_data.get("unpaid")

    return LeaveBalance(
        employee_id=employee_id,
        annual=annual,
        sick=sick,
        casual=casual,
        unpaid=unpaid,
    )


def build_leave_balances(balances_data):
    """Build LeaveBalance ORM objects for every balance in the data.

    Takes: balances_data - a dict keyed by employee ID.
    Returns: a list of LeaveBalance objects.
    """
    balances = []

    for employee_id, balance_data in balances_data.items():
        balance = build_leave_balance_record(employee_id, balance_data)
        balances.append(balance)

    return balances


def import_leave_balances(db):
    """Load and save all leave balances.

    Takes: db - the database session.
    Returns: None.
    """
    balances_data = read_keyed_collection(
        "leaves/balances.json",
        id_key="employees",
    )
    balances = build_leave_balances(balances_data)

    db.add_all(balances)


# ---------------------------------------------------------------------------
# Leave history
# ---------------------------------------------------------------------------
def build_leave_request_records(month_data, year, month):
    """Build LeaveRequest ORM objects for one month's history file.

    Takes:
      month_data - the parsed monthly leave history JSON.
      year - the year this data belongs to.
      month - the month this data belongs to.
    Returns: a list of LeaveRequest objects.
    """
    requests = []

    leave_requests = month_data.get("requests", [])

    for record in leave_requests:
        leave_id = record.get("leave_id")
        employee_id = record.get("employee_id")
        leave_type = record.get("type")

        from_date = record.get("from")
        to_date = record.get("to")

        days = record.get("days")
        status = record.get("status")

        request = LeaveRequest(
            leave_id=leave_id,
            year=year,
            month=month,
            employee_id=employee_id,
            type=leave_type,
            from_date=from_date,
            to_date=to_date,
            days=days,
            status=status,
        )

        requests.append(request)

    return requests


def import_leave_history(db):
    """Load and save all leave request history across every month.

    Takes: db - the database session.
    Returns: None.
    """
    history_files = get_monthly_files("leaves/history")

    history_rows = []

    for file_path in history_files:
        month_data = read_json_file(file_path, {})

        year = month_data.get("year")
        month = month_data.get("month")

        rows = build_leave_request_records(month_data, year, month)
        history_rows.extend(rows)

    db.add_all(history_rows)


# ---------------------------------------------------------------------------
# Payroll structures
# ---------------------------------------------------------------------------
def build_payroll_structure_record(employee_id, structure_data):
    """Build a PayrollStructure ORM object from one structure JSON record.

    Takes:
      employee_id - the employee's unique ID.
      structure_data - the raw JSON structure record.
    Returns: a PayrollStructure object.
    """
    currency = structure_data.get("currency")
    basic = structure_data.get("basic")
    housing_allowance = structure_data.get("housing_allowance")
    transport_allowance = structure_data.get("transport_allowance")
    other_allowances = structure_data.get("other_allowances")
    deductions = structure_data.get("deductions")

    return PayrollStructure(
        employee_id=employee_id,
        currency=currency,
        basic=basic,
        housing_allowance=housing_allowance,
        transport_allowance=transport_allowance,
        other_allowances=other_allowances,
        deductions=deductions,
    )


def build_payroll_structures(structures_data):
    """Build PayrollStructure ORM objects for every structure in the data.

    Takes: structures_data - a dict keyed by employee ID.
    Returns: a list of PayrollStructure objects.
    """
    structures = []

    for employee_id, structure_data in structures_data.items():
        structure = build_payroll_structure_record(employee_id, structure_data)
        structures.append(structure)

    return structures


def import_payroll_structures(db):
    """Load and save all payroll structures.

    Takes: db - the database session.
    Returns: None.
    """
    structures_data = read_keyed_collection(
        "payroll/structures.json",
        id_key="employees",
    )
    structures = build_payroll_structures(structures_data)

    db.add_all(structures)


# ---------------------------------------------------------------------------
# Payslips
# ---------------------------------------------------------------------------
def build_payslip_records(month_data, year, month):
    """Build Payslip ORM objects for one month's payslip file.

    Takes:
      month_data - the parsed monthly payslip JSON.
      year - the year this data belongs to.
      month - the month this data belongs to.
    Returns: a list of Payslip objects.
    """
    payslips = []

    slip_records = month_data.get("payslips", [])

    for record in slip_records:
        payslip_id = record.get("payslip_id")
        employee_id = record.get("employee_id")
        deductions = record.get("deductions")
        status = record.get("status")
        file = record.get("file")

        payslip = Payslip(
            payslip_id=payslip_id,
            year=year,
            month=month,
            employee_id=employee_id,
            deductions=deductions,
            status=status,
            file=file,
        )

        payslips.append(payslip)

    return payslips


def import_payslips(db):
    """Load and save all payslips across every month.

    Takes: db - the database session.
    Returns: None.
    """
    payslip_files = get_monthly_files("payroll/payslips")

    payslip_rows = []

    for file_path in payslip_files:
        month_data = read_json_file(file_path, {})

        year = month_data.get("year")
        month = month_data.get("month")

        rows = build_payslip_records(month_data, year, month)
        payslip_rows.extend(rows)

    db.add_all(payslip_rows)


# ---------------------------------------------------------------------------
# Services
# ---------------------------------------------------------------------------
def build_service_record(service_data):
    """Build a Service ORM object from one service JSON record.

    Takes: service_data - the raw JSON service record.
    Returns: a Service object.
    """
    service_id = service_data.get("service_id")
    name = service_data.get("name")
    role = service_data.get("role")
    department = service_data.get("department")
    extension = service_data.get("extension")
    email = service_data.get("email")
    location = service_data.get("location")
    hours = service_data.get("hours")

    return Service(
        service_id=service_id,
        name=name,
        role=role,
        department=department,
        extension=extension,
        email=email,
        location=location,
        hours=hours,
    )


def build_services(services_data):
    """Build Service ORM objects for every service in the data.

    Takes: services_data - a list of raw service records.
    Returns: a list of Service objects.
    """
    services = []

    for service_data in services_data:
        service = build_service_record(service_data)
        services.append(service)

    return services


def import_services(db):
    """Load and save all services.

    Takes: db - the database session.
    Returns: None.
    """
    services_data = read_list_collection("services/directory.json", list_key="services")
    services = build_services(services_data)

    db.add_all(services)


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------
def build_document_record(document_data):
    """Build a Document ORM object from one document JSON record.

    Takes: document_data - the raw JSON document record.
    Returns: a Document object.
    """
    document_id = document_data.get("document_id")
    name = document_data.get("name")
    category = document_data.get("category")
    file = document_data.get("file")
    type = document_data.get("type")

    return Document(
        document_id=document_id,
        name=name,
        category=category,
        file=file,
        type=type,
    )


def build_documents(documents_data):
    """Build Document ORM objects for every document in the data.

    Takes: documents_data - a list of raw document records.
    Returns: a list of Document objects.
    """
    documents = []

    for document_data in documents_data:
        document = build_document_record(document_data)
        documents.append(document)

    return documents


def import_documents(db):
    """Load and save all documents.

    Takes: db - the database session.
    Returns: None.
    """
    documents_data = read_plain_list("documents/registry.json")
    documents = build_documents(documents_data)

    db.add_all(documents)


# ---------------------------------------------------------------------------
# Table management
# ---------------------------------------------------------------------------
def reset_tables():
    """Drop and recreate all tables.

    Takes: none.
    Returns: None.
    Side effect: removes any existing data in the tables.
    """
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)


def import_all_data(db):
    """Import every data collection into the database.

    Takes: db - the database session.
    Returns: None.
    """
    import_employees(db)
    import_credentials(db)
    import_attendance(db)
    import_leave_balances(db)
    import_leave_history(db)
    import_payroll_structures(db)
    import_payslips(db)
    import_services(db)
    import_documents(db)


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------
def report_row_counts(db):
    """Print the row count for every table.

    Takes: db - the database session.
    Returns: None.
    """
    from sqlalchemy import func, select

    print(f"Database created: {DATA_DIR / 'hr-db.db'}")

    tables = [
        Employee,
        Credential,
        Attendance,
        LeaveBalance,
        LeaveRequest,
        PayrollStructure,
        Payslip,
        Service,
        Document,
    ]

    for table in tables:
        count = db.scalar(select(func.count()).select_from(table))
        print(f"  {table.__tablename__}: {count} rows")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main():
    """Rebuild the database from the JSON source files."""
    reset_tables()

    db = SessionLocal()
    try:
        import_all_data(db)
        db.commit()
    finally:
        db.close()

    with SessionLocal() as reporting_db:
        report_row_counts(reporting_db)


if __name__ == "__main__":
    main()
