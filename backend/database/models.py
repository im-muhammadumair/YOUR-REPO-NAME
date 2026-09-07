"""SQLAlchemy ORM models for the MTM HR Agent database.

Each model maps one row (record) to the columns (cells) of its table, matching
the structure of the original JSON data.
"""
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Table,
)
from sqlalchemy.orm import relationship

from database.connection import Base


class Employee(Base):
    __tablename__ = "employees"

    employee_id = Column(String, primary_key=True)
    employee_number = Column(String)
    first_name = Column(String)
    last_name = Column(String)
    department_id = Column(String)
    department = Column(String)
    job_title = Column(String)
    employment_type = Column(String)
    employment_status = Column(String)
    joining_date = Column(String)
    email = Column(String)
    phone = Column(String)
    extension = Column(String)
    floor = Column(Integer)
    desk_number = Column(String)
    seat_status = Column(String)

    credential = relationship("Credential", back_populates="employee")
    attendance = relationship("Attendance", back_populates="employee")
    leave_balance = relationship("LeaveBalance", back_populates="employee")
    leave_requests = relationship("LeaveRequest", back_populates="employee")
    payroll_structure = relationship("PayrollStructure", back_populates="employee")
    payslips = relationship("Payslip", back_populates="employee")


class Credential(Base):
    __tablename__ = "credentials"

    employee_id = Column(String, ForeignKey("employees.employee_id"), primary_key=True)
    username = Column(String)
    password = Column(String)
    account_type = Column(String)
    account_status = Column(String)

    employee = relationship("Employee", back_populates="credential")


class Attendance(Base):
    __tablename__ = "attendance"

    id = Column(Integer, primary_key=True, autoincrement=True)
    year = Column(Integer)
    month = Column(Integer)
    employee_id = Column(String, ForeignKey("employees.employee_id"))
    date = Column(String)
    check_in = Column(String)
    check_out = Column(String)
    status = Column(String)
    working_hours = Column(Float)

    employee = relationship("Employee", back_populates="attendance")


class LeaveBalance(Base):
    __tablename__ = "leave_balances"

    employee_id = Column(String, ForeignKey("employees.employee_id"), primary_key=True)
    annual = Column(Integer)
    sick = Column(Integer)
    casual = Column(Integer)
    unpaid = Column(Integer)

    employee = relationship("Employee", back_populates="leave_balance")


class LeaveRequest(Base):
    __tablename__ = "leave_history"

    leave_id = Column(String, primary_key=True)
    year = Column(Integer)
    month = Column(Integer)
    employee_id = Column(String, ForeignKey("employees.employee_id"))
    type = Column(String)
    from_date = Column(String)
    to_date = Column(String)
    days = Column(Integer)
    status = Column(String)

    employee = relationship("Employee", back_populates="leave_requests")


class PayrollStructure(Base):
    __tablename__ = "payroll_structures"

    employee_id = Column(String, ForeignKey("employees.employee_id"), primary_key=True)
    currency = Column(String)
    basic = Column(Integer)
    housing_allowance = Column(Integer)
    transport_allowance = Column(Integer)
    other_allowances = Column(Integer)
    deductions = Column(Integer)

    employee = relationship("Employee", back_populates="payroll_structure")


class Payslip(Base):
    __tablename__ = "payslips"

    payslip_id = Column(String, primary_key=True)
    year = Column(Integer)
    month = Column(Integer)
    employee_id = Column(String, ForeignKey("employees.employee_id"))
    deductions = Column(Integer)
    status = Column(String)
    file = Column(String)

    employee = relationship("Employee", back_populates="payslips")


class Service(Base):
    __tablename__ = "services"

    service_id = Column(String, primary_key=True)
    name = Column(String)
    role = Column(String)
    department = Column(String)
    extension = Column(String)
    email = Column(String)
    location = Column(String)
    hours = Column(String)


class Document(Base):
    __tablename__ = "documents"

    document_id = Column(String, primary_key=True)
    name = Column(String)
    category = Column(String)
    file = Column(String)
    type = Column(String)
    # AI / RAG state. The PDF file itself stays in storage/ and its mapping in
    # this table; these columns only track whether it is enabled for AI and the
    # current indexing state. They are added by an idempotent migration so the
    # existing DB is upgraded in place without dropping or rewriting tables.
    ai_enabled = Column(Boolean, default=False, nullable=False)
    ai_status = Column(String, default="not_indexed", nullable=False)
    ai_updated_at = Column(String, nullable=True)


# ---------------------------------------------------------------------------
# Authentication tables
# ---------------------------------------------------------------------------
# Join table linking users to their roles.
user_roles = Table(
    "user_roles",
    Base.metadata,
    Column("user_id", Integer, ForeignKey("users.id"), primary_key=True),
    Column("role_id", Integer, ForeignKey("roles.id"), primary_key=True),
)

# Join table linking roles to their permissions.
role_permissions = Table(
    "role_permissions",
    Base.metadata,
    Column("role_id", Integer, ForeignKey("roles.id"), primary_key=True),
    Column("permission_id", Integer, ForeignKey("permissions.id"), primary_key=True),
)


class User(Base):
    """An application login account.

    Links to the employee business record through employee_id. Authentication
    (credentials, roles, sessions) is kept logically separate from employee
    business data.
    """

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    employee_id = Column(String, ForeignKey("employees.employee_id"))
    username = Column(String, unique=True, index=True)
    password = Column(String)
    password_hash = Column(String)
    account_status = Column(String, default="Active")
    created_at = Column(DateTime)

    roles = relationship("Role", secondary=user_roles, back_populates="users")
    refresh_sessions = relationship("RefreshSession", back_populates="user")


class Role(Base):
    """A named role that groups a set of permissions."""

    __tablename__ = "roles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, unique=True)

    users = relationship("User", secondary=user_roles, back_populates="roles")
    permissions = relationship(
        "Permission",
        secondary=role_permissions,
        back_populates="roles",
    )


class Permission(Base):
    """A single fine-grained permission (e.g. 'employees.read')."""

    __tablename__ = "permissions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, unique=True)

    roles = relationship(
        "Role",
        secondary=role_permissions,
        back_populates="permissions",
    )


class RefreshSession(Base):
    """A long-lived, revocable refresh-token session for one user.

    Only a hash of the refresh token is stored, never the raw token.
    """

    __tablename__ = "refresh_sessions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    token_hash = Column(String, unique=True, index=True)
    created_at = Column(DateTime)
    expires_at = Column(DateTime)
    revoked_at = Column(DateTime)
    last_used_at = Column(DateTime)
    device_info = Column(String)

    user = relationship("User", back_populates="refresh_sessions")
