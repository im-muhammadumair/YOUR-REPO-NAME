"""Loading and managing the RS256 JWT signing keys.

The private key is used to sign access tokens. The public key is used to verify
them and can be shared with other services that only need to verify tokens.

Keys are read from environment configuration (.env). If a key pair is missing,
one is generated in-memory at startup (useful for local development, though the
keys will change on restart).
"""
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from config import JWT_PRIVATE_KEY, JWT_PUBLIC_KEY


class MissingKeysError(Exception):
    """Raised when no usable RSA key pair is available."""


def generate_key_pair():
    """Generate a fresh RSA-2048 key pair.

    Takes: no arguments.
    Returns: a tuple (private_key_object, public_key_object).
    """
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()
    return private_key, public_key


def load_private_key(pem_text):
    """Load an RSA private key object from its PEM text.

    Takes: pem_text - the PEM-encoded private key (string or bytes).
    Returns: the private key object.
    Raises: ValueError if the PEM text cannot be parsed.
    """
    if isinstance(pem_text, str):
        pem_bytes = pem_text.encode()
    else:
        pem_bytes = pem_text

    private_key = serialization.load_pem_private_key(pem_bytes, password=None)
    return private_key


def load_public_key(pem_text):
    """Load an RSA public key object from its PEM text.

    Takes: pem_text - the PEM-encoded public key (string or bytes).
    Returns: the public key object.
    Raises: ValueError if the PEM text cannot be parsed.
    """
    if isinstance(pem_text, str):
        pem_bytes = pem_text.encode()
    else:
        pem_bytes = pem_text

    public_key = serialization.load_pem_public_key(pem_bytes)
    return public_key


def get_signing_key():
    """Return the private key used to sign JWTs.

    Takes: no arguments.
    Returns: the private key object.
    Raises: MissingKeysError if the configured key cannot be parsed.
    """
    if JWT_PRIVATE_KEY:
        try:
            return load_private_key(JWT_PRIVATE_KEY)
        except ValueError:
            raise MissingKeysError(
                "JWT_PRIVATE_KEY is set but could not be parsed."
            )

    private_key, _ = generate_key_pair()
    return private_key


def get_verification_key():
    """Return the public key used to verify JWTs.

    Takes: no arguments.
    Returns: the public key object.
    Raises: MissingKeysError if the configured key cannot be parsed.
    """
    if JWT_PUBLIC_KEY:
        try:
            return load_public_key(JWT_PUBLIC_KEY)
        except ValueError:
            raise MissingKeysError(
                "JWT_PUBLIC_KEY is set but could not be parsed."
            )

    private_key, public_key = generate_key_pair()
    return public_key
