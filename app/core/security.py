# app/core/security.py
import os
from datetime import datetime, timedelta
from typing import Any, Dict, Union

from jose import jwt
from passlib.context import CryptContext

# Em produção, sobrescrever via variável de ambiente
SECRET_KEY = os.getenv("SVPOS_SECRET_KEY", "change-me-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(
    os.getenv("SVPOS_ACCESS_TOKEN_EXPIRE_MINUTES", "1440")
)  # 24h

pwd_context = CryptContext(
    schemes=["bcrypt_sha256"],
    deprecated="auto",
)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def create_access_token(
    subject: Union[str, int],
    role: str,
    expires_delta: timedelta | None = None,
) -> str:
    if expires_delta is None:
        expires_delta = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)

    expire = datetime.utcnow() + expires_delta
    to_encode: Dict[str, Any] = {
        "sub": str(subject),
        "role": role,
        "exp": expire,
    }
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt
