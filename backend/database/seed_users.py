"""Seed the application users table from the existing credentials.

On startup this migrates each row of the legacy `credentials` table into the new
`users` authentication table and assigns a role (Admin for admin accounts,
Employee otherwise). It is idempotent: existing users are updated, not
duplicated.
"""
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from database.models import Credential, Role, User

from auth.creds import encrypt_password


def seed_users(db):
    """Create or update a user row for every credential.

    Safe to run from multiple workers at startup: if a concurrent worker inserts
    the same username first, the unique-constraint error is swallowed and the
    existing row is reused.

    Takes: db - the database session.
    Returns: None.
    Side effect: inserts/updates rows in the users table and assigns roles.
    """
    credentials = db.scalars(select(Credential)).all()

    for credential in credentials:
        user = db.scalar(select(User).where(User.username == credential.username))

        if user is None:
            try:
                user = User(
                    employee_id=credential.employee_id,
                    username=credential.username,
                    password=encrypt_password(credential.password),
                    password_hash=None,
                    account_status=credential.account_status or "Active",
                    created_at=datetime.utcnow(),
                )
                db.add(user)
                db.flush()
            except IntegrityError:
                db.rollback()
                user = db.scalar(select(User).where(User.username == credential.username))

        # Keep the stored credential in sync if it changed upstream.
        user.employee_id = credential.employee_id
        user.account_status = credential.account_status or "Active"
        user.password = encrypt_password(credential.password)

        assign_default_role(db, user, credential.account_type)

    db.commit()


def assign_default_role(db, user, account_type):
    """Assign the user a role based on their account type.

    Admin accounts get the Admin role; everyone else gets the Employee role.
    The existing admin role is preserved if it is already assigned.

    Takes:
      db - the database session.
      user - the User object.
      account_type - the legacy account type ('admin' or 'user').
    Returns: None.
    """
    if account_type == "admin":
        role_name = "Admin"
    else:
        role_name = "Employee"

    role = db.scalar(select(Role).where(Role.name == role_name))

    if role is None:
        return

    role_names = {existing.name for existing in user.roles}

    if role_name not in role_names:
        user.roles.append(role)
