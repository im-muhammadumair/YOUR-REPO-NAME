"""Password verification and login rate limiting.

Passwords are stored encrypted at rest (see auth.creds) — the database never
holds plaintext. ``verify_password`` decrypts the stored value (or compares a
legacy plaintext directly) and is used by the login route.
"""
import threading
import time

from config import LOGIN_LOCKOUT_SECONDS, LOGIN_MAX_ATTEMPTS

from auth.creds import decrypt_password, is_encrypted


def verify_password(password, stored_password, stored_hash=None):
    """Check whether a supplied password matches the stored credential.

    Takes:
      password - the plaintext password supplied at login.
      stored_password - the stored credential (encrypted ciphertext, or
                        legacy plaintext before migration).
      stored_hash - an optional stored hash (reserved for future use).
    Returns: True if the password is acceptable, otherwise False.
    """
    if stored_hash:
        return False

    if stored_password is None:
        return False

    if is_encrypted(stored_password):
        stored = decrypt_password(stored_password)
        if stored is None:
            return False
        return constant_time_equals(password or "", stored)

    return constant_time_equals(password or "", stored_password)


def constant_time_equals(left, right):
    """Compare two strings in constant time to avoid timing attacks.

    Takes:
      left - the first string.
      right - the second string.
    Returns: True when the strings are equal, otherwise False.
    """
    if not isinstance(left, str) or not isinstance(right, str):
        return False

    if len(left) != len(right):
        return False

    result = 0
    for left_char, right_char in zip(left, right):
        result |= ord(left_char) ^ ord(right_char)

    return result == 0


class LoginThrottle:
    """Tracks failed login attempts per client and temporarily locks them out.

    The key is a combination of the client IP and the attempted username, so a
    single device cannot hammer one account without being blocked.
    """

    def __init__(self):
        # Maps a client::username key to counters and lockout state.
        self.failures = {}

        # Protects concurrent access to self.failures.
        self.lock = threading.Lock()

    def _key(self, request, username):
        """Build the unique key identifying one client + username pair.

        Takes:
          request - the FastAPI Request object.
          username - the attempted login username.
        Returns: a string key used to track failures.
        """
        client_host = request.client.host if request.client else "unknown"
        return f"{client_host}::{username}"

    def is_locked(self, request, username):
        """Check whether a client is currently locked out.

        Takes:
          request - the FastAPI Request object.
          username - the attempted login username.
        Returns: True if locked out, otherwise False.
        """
        with self.lock:
            key = self._key(request, username)
            record = self.failures.get(key)

            if not record:
                return False

            lockout_until = record.get("lockout_until", 0.0)

            if lockout_until and time.time() < lockout_until:
                return True

            if lockout_until and time.time() >= lockout_until:
                self.failures.pop(key, None)

            return False

    def record_failure(self, request, username):
        """Record one failed login attempt for a client.

        Takes:
          request - the FastAPI Request object.
          username - the attempted login username.
        Returns: None.
        Side effect: starts a lockout once the attempt limit is reached.
        """
        with self.lock:
            key = self._key(request, username)
            record = self.failures.get(key, {"count": 0, "lockout_until": 0.0})

            record["count"] += 1

            if record["count"] >= LOGIN_MAX_ATTEMPTS:
                record["lockout_until"] = time.time() + LOGIN_LOCKOUT_SECONDS
                record["count"] = 0

            self.failures[key] = record

    def reset(self, request, username):
        """Clear all failure tracking for a client after a successful login.

        Takes:
          request - the FastAPI Request object.
          username - the successfully authenticated username.
        Returns: None.
        """
        with self.lock:
            key = self._key(request, username)
            self.failures.pop(key, None)


# Single shared throttle used across the whole application.
login_throttle = LoginThrottle()
