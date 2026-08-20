"""本地密钥加解密：基于 SECRET_KEY 派生的 Fernet 对称加密。"""
import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings as app_settings

ENCRYPTED_PREFIX = "enc:"


def _fernet() -> Fernet:
    digest = hashlib.sha256((app_settings.SECRET_KEY or "researchmate-fallback").encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(value: str) -> str:
    value = value or ""
    if not value or value.startswith(ENCRYPTED_PREFIX):
        return value
    return ENCRYPTED_PREFIX + _fernet().encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_secret(value: str) -> str:
    value = value or ""
    if not value.startswith(ENCRYPTED_PREFIX):
        return value
    try:
        raw = value[len(ENCRYPTED_PREFIX):]
        return _fernet().decrypt(raw.encode("utf-8")).decode("utf-8")
    except (InvalidToken, ValueError, TypeError):
        # 旧明文或密钥变更：原样返回，避免把用户配置锁死
        return value
