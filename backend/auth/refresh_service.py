"""Managing long-lived, revocable refresh-token sessions.

A refresh token is a cryptographically random opaque string. Only its SHA-256
hash is stored in the database so a leaked database cannot be used to forge
refresh tokens. Tokens are rotated on every refresh and sessions can be revoked
individually (logout or device management).
"""
import hashlib
import logging
import secrets
from datetime import datetime, timedelta

from config import REFRESH_TOKEN_EXPIRE_DAYS
from database.models import RefreshSession

from sqlalchemy import select, delete

log = logging.getLogger(__name__)


def generate_refresh_token():
    """Generate a cryptographically secure random refresh token.

    Takes: no arguments.
    Returns: a random refresh token string.
    """
    return secrets.token_urlsafe(64)


def hash_token(token):
    """Compute the SHA-256 hash of a refresh token for storage.

    Takes: token - the raw refresh token string.
    Returns: the hex digest of the token.
    """
    raw_bytes = token.encode()
    digest = hashlib.sha256(raw_bytes)
    return digest.hexdigest()


def create_refresh_session(db, user, device_info=None):
    """Create and persist a new refresh session for a user.

    Takes:
      db - the database session.
      user - the User object the session belongs to.
      device_info - optional client/device description string.
    Returns: the newly created RefreshSession object.
    """
    token = generate_refresh_token()

    now = datetime.utcnow()
    expires_at = now + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)

    session = RefreshSession(
        user_id=user.id,
        token_hash=hash_token(token),
        created_at=now,
        expires_at=expires_at,
        revoked_at=None,
        last_used_at=now,
        device_info=device_info,
    )

    db.add(session)
    db.commit()
    db.refresh(session)

    # Attach the raw token to the object so the caller can return it to the client.
    session.raw_token = token

    return session


def validate_refresh_token(db, token):
    """Validate a raw refresh token and return its session.

    Checks that the token hash matches an existing, non-revoked, non-expired
    session.  If the token is found but expired or revoked, the row is
    hard-deleted immediately so the table stays clean.

    Takes:
      db - the database session.
      token - the client's raw refresh token.
    Returns: the RefreshSession object, or None when invalid.
    """
    token_hash = hash_token(token)

    now = datetime.utcnow()

    session = db.scalar(
        select(RefreshSession).where(RefreshSession.token_hash == token_hash)
    )

    if session is None:
        return None

    if session.revoked_at is not None:
        db.delete(session)
        db.commit()
        return None

    if session.expires_at is None or session.expires_at <= now:
        db.delete(session)
        db.commit()
        return None

    return session


def rotate_refresh_session(db, session, device_info=None):
    """Invalidate a session's current token and issue a new one.

    The old session is revoked and a fresh session row is created, then
    committed together so rotation is atomic.

    Takes:
      db - the database session.
      session - the current RefreshSession being rotated.
      device_info - optional client/device description string.
    Returns: the new RefreshSession object (with .raw_token set).
    """
    session.revoked_at = datetime.utcnow()
    session.last_used_at = datetime.utcnow()
    db.add(session)

    user_id = session.user_id
    db.commit()

    # Build a fresh session row for the same user.
    token = generate_refresh_token()
    now = datetime.utcnow()
    expires_at = now + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)

    new_session = RefreshSession(
        user_id=user_id,
        token_hash=hash_token(token),
        created_at=now,
        expires_at=expires_at,
        revoked_at=None,
        last_used_at=now,
        device_info=device_info,
    )

    db.add(new_session)
    db.commit()
    db.refresh(new_session)

    new_session.raw_token = token

    return new_session


def revoke_session(db, session):
    """Revoke a single refresh session.

    Takes:
      db - the database session.
      session - the RefreshSession to revoke.
    Returns: None.
    """
    session.revoked_at = datetime.utcnow()
    db.add(session)
    db.commit()


def revoke_all_sessions(db, user_id):
    """Revoke every refresh session belonging to a user.

    Takes:
      db - the database session.
      user_id - the id of the user whose sessions to revoke.
    Returns: None.
    """
    now = datetime.utcnow()

    sessions = db.scalars(
        select(RefreshSession).where(RefreshSession.user_id == user_id)
    ).all()

    for session in sessions:
        session.revoked_at = now

    db.commit()


def list_sessions(db, user_id):
    """List all non-revoked refresh sessions for a user.

    Takes:
      db - the database session.
      user_id - the id of the user.
    Returns: a list of active RefreshSession objects.
    """
    sessions = db.scalars(
        select(RefreshSession)
        .where(RefreshSession.user_id == user_id)
        .where(RefreshSession.revoked_at.is_(None))
    ).all()

    return sessions


def cleanup_expired(db, max_active_per_user=5):
    """Delete revoked, expired, and excess refresh sessions. Runs every hour.

    Revoked sessions are old tokens already rotated out — dead rows.
    Expired sessions are past their 14-day window — useless.
    Excess active sessions per user are capped to keep the table lean.

    Returns the number of rows deleted.
    """
    now = datetime.utcnow()

    # 1. Revoked sessions — the old token was already rotated; dead row.
    revoked = db.execute(
        delete(RefreshSession).where(RefreshSession.revoked_at.isnot(None))
    )

    # 2. Expired sessions — past their expires_at window.
    expired = db.execute(
        delete(RefreshSession).where(
            RefreshSession.expires_at.isnot(None),
            RefreshSession.expires_at <= now,
        )
    )

    # 3. Orphan sessions — user_id is NULL (invalid FK).
    orphans = db.execute(
        delete(RefreshSession).where(RefreshSession.user_id.is_(None))
    )

    db.commit()

    # 4. Cap active sessions per user — keep only the N most recent.
    excess = 0
    users = db.scalars(
        select(RefreshSession.user_id)
        .where(RefreshSession.revoked_at.is_(None))
        .where(RefreshSession.user_id.isnot(None))
        .distinct()
    ).all()

    for uid in users:
        recent_ids = db.scalars(
            select(RefreshSession.id)
            .where(RefreshSession.user_id == uid)
            .where(RefreshSession.revoked_at.is_(None))
            .order_by(RefreshSession.created_at.desc())
            .limit(max_active_per_user)
        ).all()

        if len(recent_ids) >= max_active_per_user:
            old = db.execute(
                delete(RefreshSession).where(
                    RefreshSession.user_id == uid,
                    RefreshSession.id.notin_(recent_ids),
                )
            )
            excess += old.rowcount

    if excess:
        db.commit()

    total = revoked.rowcount + expired.rowcount + orphans.rowcount + excess
    if total:
        log.info(
            "refresh_sessions periodic cleanup: deleted %d rows "
            "(revoked=%d, expired=%d, orphans=%d, excess=%d)",
            total, revoked.rowcount, expired.rowcount, orphans.rowcount, excess,
        )
    return total


def cleanup_sessions(db, max_active_per_user=5):
    """Hard-delete refresh sessions that are no longer useful.

    Deletes:
      - revoked sessions (old tokens already rotated out)
      - expired sessions (past their expires_at)
      - orphan sessions (user_id is NULL — invalid FK)
      - excess active sessions per user (keeps only the N most recent)

    Called once at app startup so the table doesn't grow forever.
    """
    now = datetime.utcnow()

    # 1. Revoked sessions — the old token was already rotated; dead row.
    revoked = db.execute(
        delete(RefreshSession).where(RefreshSession.revoked_at.isnot(None))
    )
    # 2. Expired sessions — past their expires_at window; useless even if not revoked.
    expired = db.execute(
        delete(RefreshSession).where(
            RefreshSession.expires_at.isnot(None),
            RefreshSession.expires_at <= now,
        )
    )
    # 3. Orphan sessions — user_id is NULL (invalid FK, shouldn't exist).
    orphans = db.execute(
        delete(RefreshSession).where(RefreshSession.user_id.is_(None))
    )
    db.commit()

    # 4. Cap active sessions per user — keep only the N most recent.
    excess = 0
    users = db.scalars(
        select(RefreshSession.user_id)
        .where(RefreshSession.revoked_at.is_(None))
        .where(RefreshSession.user_id.isnot(None))
        .distinct()
    ).all()

    for uid in users:
        recent_ids = db.scalars(
            select(RefreshSession.id)
            .where(RefreshSession.user_id == uid)
            .where(RefreshSession.revoked_at.is_(None))
            .order_by(RefreshSession.created_at.desc())
            .limit(max_active_per_user)
        ).all()

        if len(recent_ids) >= max_active_per_user:
            old = db.execute(
                delete(RefreshSession).where(
                    RefreshSession.user_id == uid,
                    RefreshSession.id.notin_(recent_ids),
                )
            )
            excess += old.rowcount

    if excess:
        db.commit()

    total = revoked.rowcount + expired.rowcount + orphans.rowcount + excess

    if total:
        log.info(
            "refresh_sessions cleanup: deleted %d rows "
            "(revoked=%d, expired=%d, orphans=%d, excess=%d)",
            total, revoked.rowcount, expired.rowcount, orphans.rowcount, excess,
        )

    return total
