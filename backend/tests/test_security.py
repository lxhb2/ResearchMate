"""Password hashing and JWT token helpers."""
from datetime import timedelta

from app.utils.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


def test_password_roundtrip() -> None:
    hashed = hash_password("correct horse battery staple")
    assert hashed != "correct horse battery staple"
    assert verify_password("correct horse battery staple", hashed)
    assert not verify_password("wrong password", hashed)


def test_token_roundtrip() -> None:
    token = create_access_token(subject="user-123", expires_delta=timedelta(minutes=5))
    assert decode_access_token(token) == "user-123"


def test_token_rejects_invalid_payload() -> None:
    assert decode_access_token("not-a-jwt") is None
