"""
crypto.py
---------
Symmetric encryption for sensitive fields (Sandpiper passwords) stored in the DB.

Uses Fernet (AES-128 in CBC + HMAC-SHA256) from `cryptography`. The key lives in
the SANDPIPER_ENCRYPTION_KEY env var — a URL-safe base64-encoded 32-byte key.
Generate one with:

    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

Rotating the key requires re-encrypting every account row (out of scope for now).
"""

import os
from typing import Optional
from cryptography.fernet import Fernet, InvalidToken


def _get_fernet() -> Fernet:
    key = os.getenv("SANDPIPER_ENCRYPTION_KEY")
    if not key:
        raise RuntimeError(
            "SANDPIPER_ENCRYPTION_KEY env var is not set. "
            "Generate one with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt(plaintext: Optional[str]) -> Optional[str]:
    """Encrypt a string for storage. Returns None unchanged so empty creds stay empty."""
    if plaintext is None or plaintext == "":
        return plaintext
    f = _get_fernet()
    return f.encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: Optional[str]) -> Optional[str]:
    """Decrypt a stored ciphertext. Returns None unchanged for empty values.

    Raises InvalidToken if the ciphertext was encrypted with a different key
    (e.g. after a key rotation without re-encryption)."""
    if ciphertext is None or ciphertext == "":
        return ciphertext
    f = _get_fernet()
    try:
        return f.decrypt(ciphertext.encode()).decode()
    except InvalidToken:
        raise RuntimeError(
            "Failed to decrypt — likely a key mismatch. "
            "If SANDPIPER_ENCRYPTION_KEY was rotated, re-encrypt account rows."
        )
