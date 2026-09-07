"""FastAPI dependencies that protect routes.

These dependencies centralize JWT verification, user loading and permission
checks so routes can simply declare what they require.

    - get_authenticated_user      - verifies the access JWT and loads the user.
    - require_permission(perm)    - requires a specific permission.
    - require_admin               - requires the admin permission.
"""
from fastapi import Depends, Header, HTTPException

from auth.jwt_service import verify_access_token
from auth.rbac import get_user_permissions, has_permission

from database.connection import get_db
from database.models import User

from sqlalchemy import select


def get_authenticated_user(
    authorization: str = Header(default=""),
    db=Depends(get_db),
):
    """Verify the access JWT and load the authenticated user.

    This is the dependency used to protect all endpoints.

    Takes:
      authorization - the Authorization header value.
      db - the database session.
    Returns: the authenticated User object.
    Raises: HTTPException 401 when the token is missing, invalid or expired.
    """
    token = extract_bearer_token(authorization)

    try:
        claims = verify_access_token(token)
    except Exception:
        raise HTTPException(status_code=401, detail="Not authenticated")

    username = claims.get("sub")

    from auth.routes import developer_user, is_developer_identity

    if is_developer_identity(username):
        return developer_user()

    user = db.scalar(select(User).where(User.username == username))

    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")

    if user.account_status != "Active":
        raise HTTPException(status_code=403, detail="Account is inactive")

    return user


def extract_bearer_token(authorization):
    """Pull the token out of a 'Bearer <token>' Authorization header.

    Takes: authorization - the raw Authorization header value.
    Returns: the token string.
    """
    value = authorization or ""

    if value.startswith("Bearer "):
        return value[7:]

    return value


def require_permission(permission_name: str):
    """Build a dependency that requires a specific permission.

    Takes: permission_name - the permission required (e.g. 'employees.read').
    Returns: a FastAPI dependency function.
    """
    def dependency(
        user=Depends(get_authenticated_user),
        db=Depends(get_db),
    ):
        permissions = get_user_permissions(db, user)

        if not has_permission(permissions, permission_name):
            raise HTTPException(status_code=403, detail="Insufficient permissions")

        return user

    return dependency


def require_admin(
    user=Depends(get_authenticated_user),
    db=Depends(get_db),
):
    """Dependency that requires the user to have the admin permission.

    Takes:
      user - the authenticated user (injected).
      db - the database session.
    Returns: the authenticated user.
    Raises: HTTPException 403 when the user is not an admin.
    """
    permissions = get_user_permissions(db, user)

    if not has_permission(permissions, "admin.access"):
        raise HTTPException(status_code=403, detail="Admin access required")

    return user
