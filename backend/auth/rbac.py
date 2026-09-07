"""Role-based access control (RBAC).

Roles map to permissions. Authorization is centralized here so routes never
scatter "if role == admin" checks. The role-to-permission mapping below is the
source of truth used both for seeding the database and for lookups.

Example role -> permissions:

    Employee -> profile.read, attendance.read, leaves.read, ...
    Admin    -> admin.access, employees.read_all, salary.read_all, ...
"""
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from database.models import Permission, Role

# Each role name maps to the list of permission names it grants.
ROLE_PERMISSIONS = {
    "Employee": [
        "profile.read",
        "employees.read",
        "attendance.read",
        "leaves.read",
        "salary.read",
        "services.read",
        "documents.read",
        "file.read",
    ],
    "Manager": [
        "profile.read",
        "employees.read",
        "attendance.read",
        "leaves.read",
        "salary.read",
        "services.read",
        "documents.read",
        "file.read",
        "employees.read_all",
        "attendance.read_all",
        "leaves.read_all",
    ],
    "HR": [
        "profile.read",
        "employees.read",
        "attendance.read",
        "leaves.read",
        "salary.read",
        "services.read",
        "documents.read",
        "file.read",
        "employees.read_all",
        "leaves.read_all",
        "documents.read_all",
    ],
    "Payroll": [
        "profile.read",
        "employees.read",
        "attendance.read",
        "leaves.read",
        "salary.read",
        "services.read",
        "documents.read",
        "file.read",
        "salary.read_all",
        "payroll.manage",
    ],
    "IT": [
        "profile.read",
        "employees.read",
        "attendance.read",
        "leaves.read",
        "salary.read",
        "services.read",
        "documents.read",
        "file.read",
        "employees.read_all",
        "admin.access",
    ],
    "Admin": [
        "admin.access",
        "profile.read",
        "employees.read",
        "employees.read_all",
        "attendance.read",
        "attendance.read_all",
        "leaves.read",
        "leaves.read_all",
        "salary.read",
        "salary.read_all",
        "payroll.manage",
        "services.read",
        "documents.read",
        "documents.read_all",
        "file.read",
    ],
}


def get_user_permissions(db, user):
    """Load the set of permission names granted to a user via their roles.

    Takes:
      db - the database session.
      user - the User object.
    Returns: a set of permission name strings.
    """
    permissions = set()

    for role in user.roles:
        for permission in role.permissions:
            permissions.add(permission.name)

    return permissions


def has_permission(permissions, required):
    """Check whether a permission set contains a required permission.

    Takes:
      permissions - a collection (set/list) of permission names.
      required - the single permission name required.
    Returns: True if granted, otherwise False.
    """
    return required in permissions


def assign_role(db, user, role_name):
    """Make a user's role exactly match the given role name.

    The user's existing roles are removed and replaced with the single role.
    This keeps `primary_role_name` (the login account_type) in sync with the
    admin-chosen account type.

    Takes:
      db - the database session.
      user - the User object to update.
      role_name - the role name to assign (e.g. 'Admin' or 'Employee').
    Returns: None.
    Side effect: updates the user's role links in the database.
    """
    if role_name not in ROLE_PERMISSIONS:
        raise ValueError(f"Unknown role: {role_name}")

    role = db.scalar(select(Role).where(Role.name == role_name))

    if role is None:
        raise ValueError(f"Role not seeded: {role_name}")

    assigned_names = {existing.name for existing in user.roles}

    if assigned_names != {role_name}:
        user.roles = [role]

    return user


def seed_roles_and_permissions(db):
    """Create the roles, permissions and their links if they do not exist.

    Safe to run from multiple workers at startup: if a concurrent worker inserts
    the same role/permission first, the unique-constraint error is swallowed and
    the existing row is reused.

    Takes: db - the database session.
    Returns: None.
    Side effect: inserts roles/permissions and their mapping into the database.
    """
    role_objects = {}

    for role_name in ROLE_PERMISSIONS:
        role = db.scalar(select(Role).where(Role.name == role_name))

        if role is None:
            try:
                role = Role(name=role_name)
                db.add(role)
                db.flush()
            except IntegrityError:
                db.rollback()
                role = db.scalar(select(Role).where(Role.name == role_name))

        role_objects[role_name] = role

    # Create each permission and link it to the roles that grant it.
    for role_name, permission_names in ROLE_PERMISSIONS.items():
        role = role_objects[role_name]

        for permission_name in permission_names:
            permission = db.scalar(
                select(Permission).where(Permission.name == permission_name)
            )

            if permission is None:
                try:
                    permission = Permission(name=permission_name)
                    db.add(permission)
                    db.flush()
                except IntegrityError:
                    db.rollback()
                    permission = db.scalar(
                        select(Permission).where(Permission.name == permission_name)
                    )

            if permission not in role.permissions:
                role.permissions.append(permission)

    db.commit()
