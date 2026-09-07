"""Admin account-management endpoints.

Admins can list every login account, create new accounts, and edit existing
ones. Passwords are stored encrypted at rest (auth.creds) so the database never
holds plaintext; the admin endpoints decrypt on the way out so admins can still
view the credentials they manage. All routes here are admin-only.

Routes:
    GET  /api/admin/accounts        - list all accounts with their passwords.
    GET  /api/admin/accounts/{id}   - one account's full details.
    POST /api/admin/accounts        - create a new login account.
    PUT  /api/admin/accounts/{id}   - edit an account (partial update).
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException

from auth.creds import decrypt_password, encrypt_password
from auth.dependencies import require_admin
from auth.jwt_service import primary_role_name
from auth.rbac import assign_role

from database.connection import get_db
from database.models import Credential, Employee, User

from schemas import AccountCreateRequest, AccountUpdateRequest

from sqlalchemy import select

router = APIRouter(prefix="/api/admin/accounts")

VALID_ACCOUNT_TYPES = ("Admin", "Employee")
VALID_ACCOUNT_STATUSES = ("Active", "Inactive")


def _normalise_account_type(account_type):
    """Map an admin-supplied account type to a canonical role name.

    Accepts 'Admin'/'admin'/'Administrator' and 'Employee'/'employee'/'User'.
    Returns the canonical name, or None when unrecognised.
    """
    lowered = (account_type or "").strip().lower()

    if lowered in ("admin", "administrator"):
        return "Admin"

    if lowered in ("employee", "user"):
        return "Employee"

    return None


def _normalise_account_status(account_status):
    """Normalise an account status to 'Active' or 'Inactive'.

    Takes: account_status - the raw value.
    Returns: 'Active' or 'Inactive', or None when unrecognised.
    """
    lowered = (account_status or "").strip().lower()

    if lowered in ("active", "enabled"):
        return "Active"

    if lowered in ("inactive", "disabled", "deactivated", "deactivate"):
        return "Inactive"

    return None


def _account_dict(db, user):
    """Build the public-facing dict for one account.

    The password is decrypted from its stored ciphertext because admins are
    allowed to view the credentials they manage.

    Takes:
      db - the database session.
      user - the User object.
    Returns: a dict with the account's id, login details and employee name.
    """
    employee = db.get(Employee, user.employee_id)
    name = ""

    if employee:
        name = f"{employee.first_name or ''} {employee.last_name or ''}".strip()

    return {
        "user_id": user.id,
        "employee_id": user.employee_id,
        "name": name,
        "username": user.username,
        "password": decrypt_password(user.password) or "",
        "account_type": primary_role_name(user),
        "account_status": user.account_status,
        "created_at": user.created_at,
    }


# Returns every login account, including the password (decrypted for admins).
# Takes: none (requires the admin role).
# Returns: a dict whose "accounts" value is the list of account dicts.
@router.get("")
def list_accounts(_=Depends(require_admin), db=Depends(get_db)):
    users = db.scalars(select(User).order_by(User.id)).all()
    result = [_account_dict(db, user) for user in users]

    return {"accounts": result}


# Returns the full details of a single account, including the password.
# Takes: user_id - the id of the account to fetch.
# Returns: a dict with the account's details.
# Raises: HTTPException 404 if the account does not exist.
@router.get("/{user_id}")
def get_account(user_id: int, _=Depends(require_admin), db=Depends(get_db)):
    user = db.get(User, user_id)

    if user is None:
        raise HTTPException(status_code=404, detail="Account not found")

    return _account_dict(db, user)


def _ensure_employee(db, employee_id):
    """Return the employee row, creating one with a default name if missing.

    Account management should never reject a made-up ID: admins can create a
    login for any ID, and the Employee row is mocked with the ID itself as the
    default name for identification. The only conflict is a duplicate — the same
    employee ID cannot own two accounts.
    """
    employee = db.get(Employee, employee_id)

    if employee is None:
        employee = Employee(
            employee_id=employee_id,
            employee_number=employee_id,
            first_name=employee_id,
            last_name="",
            employment_status="Active",
        )
        db.add(employee)

    return employee


def _sync_credential(db, user, account_type):
    """Mirror an account into the legacy ``credentials`` table.

    ``credentials`` is the source of truth that reseeds the ``users`` table on
    startup (see ``database/seed_users.py``), so every credential change the
    admin makes here must be persisted there too. Admin-controlled changes stop
    at the credential; employee data (attendance, salary, etc.) is never touched.
    """
    credential_type = "admin" if account_type == "Admin" else "user"
    credential = db.get(Credential, user.employee_id)

    if credential is None:
        db.add(
            Credential(
                employee_id=user.employee_id,
                username=user.username,
                password=user.password,
                account_type=credential_type,
                account_status=user.account_status,
            )
        )
    else:
        credential.username = user.username
        credential.password = user.password
        credential.account_type = credential_type
        credential.account_status = user.account_status


# Creates a new login account. The employee row is auto-created with a default
# name when the given ID does not exist yet.
# Takes: body - the AccountCreateRequest with the account details.
# Returns: a dict with the new account's details.
# Raises: HTTPException 400/409 on invalid or duplicate input.
@router.post("")
def create_account(
    body: AccountCreateRequest,
    _=Depends(require_admin),
    db=Depends(get_db),
):
    account_type = _normalise_account_type(body.account_type)
    account_status = _normalise_account_status(body.account_status)

    if account_type is None:
        raise HTTPException(status_code=400, detail="account_type must be Admin or Employee")

    if account_status is None:
        raise HTTPException(status_code=400, detail="account_status must be Active or Inactive")

    username = body.username.strip()

    if not username:
        raise HTTPException(status_code=400, detail="Username is required")

    if not body.password:
        raise HTTPException(status_code=400, detail="Password is required")

    if db.scalar(select(User).where(User.username == username)) is not None:
        raise HTTPException(status_code=409, detail="Username already exists")

    if db.scalar(select(User).where(User.employee_id == body.employee_id)) is not None:
        raise HTTPException(
            status_code=409,
            detail="Duplicate employee ID — this employee already has an account",
        )

    _ensure_employee(db, body.employee_id)

    user = User(
        employee_id=body.employee_id,
        username=username,
        password=encrypt_password(body.password),
        password_hash=None,
        account_status=account_status,
        created_at=datetime.utcnow(),
    )

    db.add(user)
    db.flush()
    assign_role(db, user, account_type)
    _sync_credential(db, user, account_type)
    db.commit()
    db.refresh(user)

    return _account_dict(db, user)


# Deletes a login account. Only the credentials are removed: the users row,
# its role links, refresh sessions and the credentials-table mirror. The
# employee business record (profile, attendance, salary, …) is left untouched.
# Takes: user_id - the id of the account to delete.
# Returns: a dict confirming the deletion.
# Raises: HTTPException 400/404 on invalid input or deleting yourself.
@router.delete("/{user_id}")
def delete_account(user_id: int, admin=Depends(require_admin), db=Depends(get_db)):
    user = db.get(User, user_id)

    if user is None:
        raise HTTPException(status_code=404, detail="Account not found")

    if user.id == admin.id:
        raise HTTPException(status_code=400, detail="You cannot delete your own account")

    employee_id = user.employee_id
    username = user.username

    credential = db.get(Credential, employee_id)

    if credential is not None:
        db.delete(credential)

    for session in list(user.refresh_sessions):
        db.delete(session)

    db.delete(user)
    db.commit()

    return {"status": "deleted", "user_id": user_id, "employee_id": employee_id, "username": username}


# Edits an account: username, password, account type, status or employee link.
# Takes: user_id - the account id; body - the AccountUpdateRequest (partial).
# Returns: a dict with the updated account's details.
# Raises: HTTPException 400/404/409 on invalid input.
@router.put("/{user_id}")
def update_account(
    user_id: int,
    body: AccountUpdateRequest,
    admin=Depends(require_admin),
    db=Depends(get_db),
):
    user = db.get(User, user_id)

    if user is None:
        raise HTTPException(status_code=404, detail="Account not found")

    changed = False
    old_employee_id = user.employee_id

    if body.username is not None:
        new_username = body.username.strip()

        if not new_username:
            raise HTTPException(status_code=400, detail="Username cannot be empty")

        existing = db.scalar(select(User).where(User.username == new_username))

        if existing is not None and existing.id != user.id:
            raise HTTPException(status_code=409, detail="Username already exists")

        user.username = new_username
        changed = True

    if body.password is not None:
        if not body.password:
            raise HTTPException(status_code=400, detail="Password cannot be empty")

        user.password = encrypt_password(body.password)
        user.password_hash = None
        changed = True

    if body.account_status is not None:
        account_status = _normalise_account_status(body.account_status)

        if account_status is None:
            raise HTTPException(status_code=400, detail="account_status must be Active or Inactive")

        if user.id == admin.id and account_status == "Inactive":
            raise HTTPException(status_code=400, detail="You cannot deactivate your own account")

        user.account_status = account_status
        changed = True

    if body.employee_id is not None:
        if body.employee_id != user.employee_id:
            existing = db.scalar(
                select(User).where(
                    User.employee_id == body.employee_id,
                    User.id != user.id,
                )
            )

            if existing is not None:
                raise HTTPException(
                    status_code=409,
                    detail="Duplicate employee ID — this employee already has an account",
                )

            _ensure_employee(db, body.employee_id)
            user.employee_id = body.employee_id
            changed = True

    if body.account_type is not None:
        account_type = _normalise_account_type(body.account_type)

        if account_type is None:
            raise HTTPException(status_code=400, detail="account_type must be Admin or Employee")

        if user.id == admin.id and account_type != "Admin":
            raise HTTPException(status_code=400, detail="You cannot remove your own admin access")

        assign_role(db, user, account_type)
        changed = True

    if not changed:
        raise HTTPException(status_code=400, detail="Nothing to update")

    if user.employee_id != old_employee_id:
        old_credential = db.get(Credential, old_employee_id)

        if old_credential is not None:
            db.delete(old_credential)

    _sync_credential(db, user, primary_role_name(user))
    db.commit()
    db.refresh(user)

    return _account_dict(db, user)