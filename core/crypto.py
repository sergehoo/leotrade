from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings


class CryptoService:
    @staticmethod
    def get_fernet() -> Fernet:
        key = settings.FERNET_SECRET_KEY
        if not key:
            raise RuntimeError("FERNET_SECRET_KEY non configurée.")
        return Fernet(key.encode())

    @classmethod
    def encrypt(cls, value: str) -> str:
        if not value:
            return ""
        return cls.get_fernet().encrypt(value.encode()).decode()

    @classmethod
    def decrypt(cls, value: str) -> str:
        if not value:
            return ""
        try:
            return cls.get_fernet().decrypt(value.encode()).decode()
        except InvalidToken as exc:
            raise ValueError("Impossible de déchiffrer la valeur.") from exc