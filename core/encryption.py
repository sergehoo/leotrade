import base64
import hashlib

from cryptography.fernet import Fernet
from django.conf import settings


def _build_key(raw_secret: str) -> bytes:
    if not raw_secret:
        raise ValueError("FERNET_SECRET_KEY is missing.")
    digest = hashlib.sha256(raw_secret.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def get_fernet() -> Fernet:
    return Fernet(_build_key(settings.FERNET_SECRET_KEY))


def encrypt_value(value: str) -> str:
    if not value:
        return ""
    return get_fernet().encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_value(value: str) -> str:
    if not value:
        return ""
    return get_fernet().decrypt(value.encode("utf-8")).decode("utf-8")