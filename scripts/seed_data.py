"""
Seed script: generates ~30 employees and a full year (2026) of data across the
MTM HR database, matching the existing JSON schemas.

Running it will OVERWRITE the generated datasets. Use with care.
"""
import json
import os
import random
from datetime import date, timedelta

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "database")
YEAR = 2026

# ---------------------------------------------------------------------------
# Deterministic randomness (reproducible) but different each run is fine too.
# ---------------------------------------------------------------------------
random.seed(2026)

FIRST = [
    "Ali", "Ahmed", "Sara", "Usman", "Hina", "Bilal", "Ayesha", "Farhan",
    "Rabia", "Hamza", "Maryam", "Zain", "Nadia", "Tahir", "Sana", "Omar",
    "Iqra", "Salman", "Mahnoor", "Waleed", "Nimra", "Danish", "Areej",
    "Shahzaib", "Hira", "Muhammed", "Anum", "Kashif", "Amna", "Yasir", "Laiba",
]
LAST = [
    "Raza", "Khan", "Malik", "Ahmed", "Shah", "Hussain", "Iqbal", "Ali",
    "Sheikh", "Baig", "Qureshi", "Awan", "Butt", "Chaudhry", "Mirza", "Siddiqui",
    "Farooq", "Hashmi", "Javed", "Akhtar", "Abbas", "Rana", "Aslam", "Gill",
    "Nawaz", "Tariq", "Zaidi", "Haider", "Rafiq", "Yousaf", "Anwar",
]

# Departments and a few job titles each
DEPTS = [
    ("Information Technology", "DEPT-IT", ["Software Engineer", "DevOps Engineer", "Systems Admin", "QA Engineer"]),
    ("Human Resources", "DEPT-HR", ["HR Officer", "HR Manager", "Recruiter", "HR Executive"]),
    ("Finance", "DEPT-FIN", ["Accountant", "Finance Analyst", "Payroll Officer", "Auditor"]),
    ("Marketing", "DEPT-MKT", ["Marketing Specialist", "Content Writer", "SEO Analyst", "Brand Manager"]),
    ("Sales", "DEPT-SLS", ["Sales Executive", "Business Development Manager", "Account Manager"]),
    ("Operations", "DEPT-OPS", ["Operations Coordinator", "Supply Chain Analyst", "Logistics Officer"]),
    ("Administration", "DEPT-ADM", ["Admin Officer", "Office Manager", "Receptionist"]),
    ("Customer Support", "DEPT-CS", ["Support Agent", "Support Lead", "Customer Success Manager"]),
    ("Product", "DEPT-PRD", ["Product Manager", "Product Analyst", "UX Designer"]),
    ("Legal", "DEPT-LGL", ["Legal Advisor", "Compliance Officer", "Paralegal"]),
]

ETYPES = ["Full-Time", "Full-Time", "Full-Time", "Part-Time", "Contract"]

# Existing employees to PRESERVE (person + credentials + salaries etc.)
PRESERVE_PROFILES = {
    "EMP001": {"employee_id": "EMP001", "employee_number": "10001", "first_name": "Ali", "last_name": "Raza",
               "department_id": "DEPT-IT", "department": "Information Technology", "job_title": "Software Engineer",
               "employment_type": "Full-Time", "employment_status": "Active", "joining_date": "2025-01-15"},
    "EMP002": {"employee_id": "EMP002", "employee_number": "10002", "first_name": "Ahmed", "last_name": "Khan",
               "department_id": "DEPT-HR", "department": "Human Resources", "job_title": "HR Officer",
               "employment_type": "Full-Time", "employment_status": "Active", "joining_date": "2024-08-10"},
    "EMP003": {"employee_id": "EMP003", "employee_number": "10003", "first_name": "Sara", "last_name": "Malik",
               "department_id": "DEPT-FIN", "department": "Finance", "job_title": "Accountant",
               "employment_type": "Full-Time", "employment_status": "Active", "joining_date": "2025-03-01"},
}
PRESERVE_CONTACTS = {
    "EMP001": {"email": "ali.raza@company.com", "phone": "+92-300-1111111", "extension": "204"},
    "EMP002": {"email": "ahmed.khan@company.com", "phone": "+92-300-2222222", "extension": "205"},
    "EMP003": {"email": "sara.malik@company.com", "phone": "+92-300-3333333", "extension": "206"},
}
PRESERVE_LOCATIONS = {
    "EMP001": {"floor": 2, "desk_number": "IT-24", "seat_status": "Assigned"},
    "EMP002": {"floor": 1, "desk_number": "HR-12", "seat_status": "Assigned"},
    "EMP003": {"floor": 2, "desk_number": "FIN-18", "seat_status": "Assigned"},
}
PRESERVE_CREDS = {
    "EMP001": {"username": "umair", "password": "umair", "account_type": "user", "account_status": "Active"},
    "EMP002": {"username": "ahmed.khan", "password": "Ahmed@123", "account_type": "user", "account_status": "Active"},
    "EMP003": {"username": "sara.malik", "password": "Sara@123", "account_type": "admin", "account_status": "Active"},
}

# ---------------------------------------------------------------------------
# Build 30 employees (EMP001..EMP030), first 3 preserved
# ---------------------------------------------------------------------------
employees = {}
credentials = {}
structures = {}
leave_balances = {}

floor_map = {}
dept_floor = list(range(1, 5))
desk_counter = [0]

def desk_for(department_id, dept_index):
    floor = (dept_index % 4) + 1
    desk_counter[0] += 1
    return floor, f"{department_id.split('-')[1]}-{desk_counter[0]:02d}"

def base_basic(dept_index):
    # Different pay bands per department for variety
    band = [72000, 90000, 58000, 62000, 68000, 66000, 82000, 70000, 92000, 88000]
    return random.choice(range(band[dept_index % len(band)] - 8000, band[dept_index % len(band)] + 8001, 1000))

for i in range(1, 31):
    emp = f"EMP{i:03d}"
    if emp in PRESERVE_PROFILES:
        dept, did, title = None, None, None
        for d, did_, titles in DEPTS:
            if did_ == PRESERVE_PROFILES[emp]["department_id"]:
                dept, did, title = d, did_, PRESERVE_PROFILES[emp]["job_title"]
                break
        employees[emp] = {
            "profiles": PRESERVE_PROFILES[emp],
            "contacts": PRESERVE_CONTACTS[emp],
            "locations": PRESERVE_LOCATIONS[emp],
        }
        structure = {
            "currency": "PKR",
            "basic": 60000 if emp == "EMP001" else 55000 if emp == "EMP002" else 58000,
            "housing_allowance": 10000 if emp == "EMP001" else 8000 if emp == "EMP002" else 9000,
            "transport_allowance": 10000 if emp == "EMP001" else 7000 if emp == "EMP002" else 8000,
            "other_allowances": 5000,
            "deductions": 5000 if emp == "EMP001" else 4000 if emp == "EMP002" else 4000,
        }
        structures[emp] = structure
        leave_balances[emp] = {"annual": 14 if emp == "EMP001" else 12 if emp == "EMP002" else 15,
                               "sick": 8 if emp == "EMP001" else 7 if emp == "EMP002" else 8,
                               "casual": 6 if emp == "EMP001" else 5 if emp == "EMP002" else 6, "unpaid": 0}
        credentials[emp] = PRESERVE_CREDS[emp]
        continue

    idx = i - 1
    fname = FIRST[idx % len(FIRST)]
    lname = LAST[(idx * 7) % len(LAST)]
    while (fname, lname) in {(employees.get(e, {}).get("profiles", {}).get("first_name"),
                             employees.get(e, {}).get("profiles", {}).get("last_name")) for e in employees}:
        lname = LAST[random.randrange(len(LAST))]

    dept, did, titles = DEPTS[idx % len(DEPTS)]
    title = titles[(idx // len(DEPTS)) % len(titles)]
    etype = ETYPES[idx % len(ETYPES)]
    floor, desk = desk_for(did, idx)
    join_d = date(2024, 3, 1) + timedelta(days=random.randint(0, 700))
    if join_d > date(2026, 6, 30):
        join_d = date(2025, 1, 1) + timedelta(days=random.randint(0, 540))

    username = f"{fname.lower()}.{lname.lower()}"
    password = f"{fname}@{random.randint(100, 999)}"
    is_admin = (i % 9 == 0)  # ~3 admins among the new ones

    employees[emp] = {
        "profiles": {
            "employee_id": emp,
            "employee_number": str(10000 + i),
            "first_name": fname,
            "last_name": lname,
            "department_id": did,
            "department": dept,
            "job_title": title,
            "employment_type": etype,
            "employment_status": "Active",
            "joining_date": join_d.isoformat(),
        },
        "contacts": {
            "email": f"{fname.lower()}.{lname.lower()}@company.com",
            "phone": f"+92-3{random.randint(0, 9)}0-{random.randint(1000000, 9999999)}",
            "extension": str(200 + i),
        },
        "locations": {"floor": floor, "desk_number": desk, "seat_status": "Assigned"},
    }
    credentials[emp] = {
        "username": username,
        "password": password,
        "account_type": "admin" if is_admin else "user",
        "account_status": "Active",
    }
    basic = base_basic(idx)
    housing = int(basic * random.uniform(0.12, 0.20))
    transport = int(basic * random.uniform(0.08, 0.14))
    other = int(basic * random.uniform(0.04, 0.08))
    ded = int(basic * random.uniform(0.05, 0.09))
    structures[emp] = {
        "currency": "PKR",
        "basic": basic,
        "housing_allowance": housing,
        "transport_allowance": transport,
        "other_allowances": other,
        "deductions": ded,
    }
    leave_balances[emp] = {
        "annual": random.randint(8, 18),
        "sick": random.randint(6, 10),
        "casual": random.randint(4, 8),
        "unpaid": random.randint(0, 2),
    }

# ---------------------------------------------------------------------------
# Attendance: weekdays across 2026 for all 30 employees
# ---------------------------------------------------------------------------
def workdays_in(year, month):
    """All calendar days of the month (Mon–Sun inclusive) so weekly and monthly
    views show every day, including weekends."""
    first = date(year, month, 1)
    if month == 12:
        nxt = date(year + 1, 1, 1)
    else:
        nxt = date(year, month + 1, 1)
    day = first
    out = []
    while day < nxt:
        out.append(day)
        day += timedelta(days=1)
    return out

STATUS_POOL = ["Present"] * 74 + ["Late"] * 14 + ["Leave"] * 5 + ["Absent"] * 7

def gen_attendance_day(day, emp_idx):
    # Sunday is a weekly holiday — always "Off".
    if day.weekday() == 6:
        return {"date": day.isoformat(), "check_in": None, "check_out": None, "status": "Off", "working_hours": 0}
    status = random.choice(STATUS_POOL)
    if status in ("Leave", "Absent"):
        return {"date": day.isoformat(), "check_in": None, "check_out": None, "status": status, "working_hours": 0}
    late = status == "Late"
    # Standard arrival ~08:55 (on time), late arrival ~09:05-09:30
    h_in, m_in = (8, random.randint(50, 59)) if not late else (9, random.randint(3, 28))
    ch_in = f"{h_in:02d}:{m_in:02d}"
    # ~12% still in office (check_out null, hours null)
    if random.random() < 0.12:
        return {"date": day.isoformat(), "check_in": ch_in, "check_out": None, "status": status, "working_hours": None}
    # Departure between 17:00 and 18:00
    h_out = random.randint(17, 18)
    m_out = random.randint(0, 30)
    ch_out = f"{h_out:02d}:{m_out:02d}"
    hours = round((h_out + m_out / 60) - (h_in + m_in / 60), 2)
    return {"date": day.isoformat(), "check_in": ch_in, "check_out": ch_out, "status": status, "working_hours": hours}

attendance_by_month = {}
for month in range(1, 13):
    days = workdays_in(YEAR, month)
    records = []
    for i in range(1, 31):
        emp = f"EMP{i:03d}"
        emp_records = [gen_attendance_day(d, i) for d in days]
        records.append({"employee_id": emp, "attendance": emp_records})
    attendance_by_month[month] = {"year": YEAR, "month": month, "records": records}

# ---------------------------------------------------------------------------
# Leaves history: a few requests per employee spread across the year
# ---------------------------------------------------------------------------
LEAVE_TYPES = ["Annual", "Annual", "Annual", "Sick", "Sick", "Casual", "Casual", "Unpaid"]
LEAVE_STATUS = ["Approved", "Approved", "Approved", "Pending", "Rejected"]
leave_history = {}
for month in range(1, 13):
    requests = []
    lid = 1
    days_in_month = workdays_in(YEAR, month)
    for i in range(1, 31):
        emp = f"EMP{i:03d}"
        # each employee has 0-2 requests per month
        for _ in range(random.choice([0, 0, 1, 1, 2])):
            if not days_in_month:
                break
            ltype = random.choice(LEAVE_TYPES)
            days = 1 if ltype == "Casual" else random.choice([1, 1, 2, 2, 3, 5])
            from_day = random.choice(days_in_month)
            to_day = from_day + timedelta(days=days - 1)
            if to_day.month != month:
                to_day = date(YEAR, month, min(days_in_month[-1].day, 28))
                days = (to_day - from_day).days + 1
            requests.append({
                "leave_id": f"LV{month:02d}{lid:03d}",
                "employee_id": emp,
                "type": ltype,
                "from": from_day.isoformat(),
                "to": to_day.isoformat(),
                "days": max(1, days),
                "status": random.choice(LEAVE_STATUS),
            })
            lid += 1
    leave_history[month] = {"year": YEAR, "month": month, "requests": requests}

# ---------------------------------------------------------------------------
# Payslips per month
# ---------------------------------------------------------------------------
payslips = {}
for month in range(1, 13):
    slips = []
    for i in range(1, 31):
        emp = f"EMP{i:03d}"
        slips.append({
            "payslip_id": f"PAY-{YEAR}-{month:02d}-{i:03d}",
            "employee_id": emp,
            "status": "Generated",
            "file": f"payslips/{emp}/{YEAR}-{month:02d}.pdf",
        })
    payslips[month] = {"year": YEAR, "month": month, "payslips": slips}

# ---------------------------------------------------------------------------
# Write everything
# ---------------------------------------------------------------------------
def write(path, obj):
    full = os.path.join(BASE, path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2)

write("employees/employees.json", employees)
write("credentials/private.json", {"credentials": credentials})
write("payroll/structures.json", {"employees": structures})
write("leaves/balances.json", {"employees": leave_balances})

for m in range(1, 13):
    write(f"attendance/{YEAR}/{m:02d}.json", attendance_by_month[m])
    write(f"leaves/history/{YEAR}/{m:02d}.json", leave_history[m])
    write(f"payroll/payslips/{YEAR}/{m:02d}.json", payslips[m])

print("Done seeding.")
print(f"Employees: {len(employees)}")
print(f"Credentials: {len(credentials)}")
admins = [e for e, c in credentials.items() if c["account_type"] == "admin"]
print(f"Admins: {admins}")
for m in range(1, 13):
    print(f"  Month {m:02d}: attendance records={len(attendance_by_month[m]['records'])}, "
          f"leave requests={len(leave_history[m]['requests'])}, payslips={len(payslips[m]['payslips'])}")
