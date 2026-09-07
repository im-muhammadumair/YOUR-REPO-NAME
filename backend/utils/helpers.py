"""General-purpose helpers used across the application.

Currently holds the short-lived signed file-link helpers and the bearer-token
extraction shared by authentication and file-serving endpoints.
"""
import hashlib
import hmac
import time

from config import (
    ALLOWED_STORAGE_ROOTS,
    FILE_LINK_SECRET,
    FILE_LINK_TTL_SECONDS,
)


def extract_token(authorization: str) -> str:
    """Strip a possible 'Bearer ' prefix from the Authorization header value.

    Takes:
      authorization - the raw value of the Authorization header.
    Returns: the token without the 'Bearer ' prefix (if it was present).
    """
    token = authorization or ""

    if token.startswith("Bearer "):
        token = token[7:]

    return token


def sign_file_link(relative_path: str) -> str:
    """Return a short-lived, signed token for opening a storage file.

    The token contains the raw (unescaped) relative path, an expiry timestamp,
    and a signature. The signature uses the raw path so it matches exactly what
    FastAPI passes in after decoding the query string.

    Takes: relative_path - the storage-relative path of the file.
    Returns: a token string of the form "<path>|<expiry>|<signature>".
    """
    expires_at = int(time.time()) + FILE_LINK_TTL_SECONDS

    unsigned_token = f"{relative_path}|{expires_at}"
    signature = compute_signature(unsigned_token)

    signed_token = f"{unsigned_token}|{signature}"
    return signed_token


def verify_file_link(token: str):
    """Validate a signed file token.

    Checks that the token is well formed, has not expired, carries a valid
    signature, and points inside an allowed storage root.

    Takes: token - the signed file token to check.
    Returns: the storage-relative path when valid, otherwise None.
    """
    parts = parse_token(token)

    if parts is None:
        return None

    relative_path = parts["path"]
    expires_at = parts["expires_at"]
    signature = parts["signature"]

    if is_expired(expires_at):
        return None

    if not has_valid_signature(relative_path, expires_at, signature):
        return None

    if not is_allowed_path(relative_path):
        return None

    return relative_path


def parse_token(token):
    """Split a signed file token into its three parts.

    Takes: token - the signed file token string.
    Returns: a dict with 'path', 'expires_at' and 'signature', or None when
    the token is missing or malformed.
    """
    if not token:
        return None

    pieces = token.rsplit("|", 2)

    if len(pieces) != 3:
        return None

    path, expiry_text, signature = pieces

    try:
        expires_at = int(expiry_text)
    except ValueError:
        return None

    return {
        "path": path,
        "expires_at": expires_at,
        "signature": signature,
    }


def is_expired(expires_at) -> bool:
    """Return True when the given expiry timestamp is already in the past.

    Takes: expires_at - the token expiry time in seconds.
    Returns: True when the token is expired, otherwise False.
    """
    current_time = time.time()
    return current_time > expires_at


def has_valid_signature(relative_path, expires_at, signature) -> bool:
    """Check that a signature matches the token content.

    Takes:
      relative_path - the storage-relative path embedded in the token.
      expires_at - the expiry timestamp embedded in the token.
      signature - the signature to compare against.
    Returns: True when the signature is valid, otherwise False.
    """
    unsigned_token = f"{relative_path}|{expires_at}"
    expected_signature = compute_signature(unsigned_token)

    return hmac.compare_digest(signature, expected_signature)


def is_allowed_path(relative_path) -> bool:
    """Check that a path points to a real folder inside storage/.

    Instead of relying on a static list that can go stale after a new
    category folder is created at runtime, this checks the actual filesystem
    so freshly created folders are accepted immediately.

    Takes: relative_path - the storage-relative path to check.
    Returns: True when the path is allowed, False otherwise.
    """
    from config import STORAGE_DIR

    top_level_folder = relative_path.split("/", 1)[0]

    if top_level_folder in ALLOWED_STORAGE_ROOTS:
        return True

    candidate = STORAGE_DIR / top_level_folder
    return candidate.is_dir()


def compute_signature(unsigned_token: str) -> str:
    """Compute the HMAC-SHA256 signature of an unsigned file token.

    Takes: unsigned_token - the token content to sign.
    Returns: the hex digest signature string.
    """
    secret_bytes = FILE_LINK_SECRET.encode()
    content_bytes = unsigned_token.encode()

    digest = hmac.new(secret_bytes, content_bytes, hashlib.sha256)
    return digest.hexdigest()
