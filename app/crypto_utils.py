"""Helpers to encrypt/decrypt sensitive fields (e.g. SQL Server password)
before storing them in the local SQLite database.

The encryption key lives in instance/secret.key, generated automatically
on first run and never committed to version control.
"""
import os
from cryptography.fernet import Fernet
from flask import current_app


def _key_path():
    return os.path.join(current_app.instance_path, "secret.key")


def _get_fernet():
    path = _key_path()
    if not os.path.exists(path):
        key = Fernet.generate_key()
        with open(path, "wb") as f:
            f.write(key)
        os.chmod(path, 0o600)
    with open(path, "rb") as f:
        key = f.read()
    return Fernet(key)


def encrypt(value: str) -> str:
    if not value:
        return ""
    return _get_fernet().encrypt(value.encode()).decode()


def decrypt(token: str) -> str:
    if not token:
        return ""
    return _get_fernet().decrypt(token.encode()).decode()
