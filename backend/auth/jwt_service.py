"""Creating and verifying short-lived JWT access tokens.

Access tokens are signed with RS256 using the private key and validated locally
(no external lookup) on every request by checking signature, expiry, issuer,
audience, token type and the presence of required claims.
"""
import time
import uuid

import jwt

from auth.keys import get_signing_key, get_verification_key

from config import (
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES,
    JWT_ALGORITHM,
    JWT_AUDIENCE,
    JWT_ISSUER,
)


def create_access_token(user, permissions):
    """Create and sign a short-lived JWT access token for a user.

    Takes:
      user - the authenticated User object.
      permissions - the list of permission names granted to the user.
    Returns: a signed JWT string.
    """
    now = int(time.time())
    expires_at = now + (JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60)

    claims = {
        "sub": user.username,
        "employee_id": user.employee_id,
        "role": primary_role_name(user),
        "permissions": permissions,
        "iat": now,
        "exp": expires_at,
        "iss": JWT_ISSUER,
        "aud": JWT_AUDIENCE,
        "jti": str(uuid.uuid4()),
        "token_type": "access",
    }

    signing_key = get_signing_key()
    token = jwt.encode(claims, signing_key, algorithm=JWT_ALGORITHM)
    return token


def primary_role_name(user):
    """Return the first role name for a user, or 'Employee' as a default.

    Takes: user - the authenticated User object.
    Returns: a role name string.
    """
    for role in user.roles:
        return role.name
    return "Employee"


def verify_access_token(token):
    """Verify a JWT access token and return its claims.

    The signature, expiry, issuer, audience, token type and required claims are
    all checked. The signing algorithm is fixed and never taken from the token
    header.

    Takes: token - the client's JWT access token.
    Returns: the decoded claims dict.
    Raises: jwt.PyJWTError subclasses when the token is invalid or expired.
    """
    verification_key = get_verification_key()

    claims = jwt.decode(
        token,
        verification_key,
        algorithms=[JWT_ALGORITHM],
        issuer=JWT_ISSUER,
        audience=JWT_AUDIENCE,
        options={"require": ["sub", "exp", "iat", "iss", "aud", "jti", "token_type"]},
    )

    is_access_token = claims.get("token_type") == "access"
    if not is_access_token:
        raise jwt.InvalidTokenError("Token is not an access token")

    return claims
