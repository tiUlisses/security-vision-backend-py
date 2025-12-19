# app/core/security.py
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Union
from uuid import uuid4

from jose import jwt
from passlib.context import CryptContext

from app.core.config import settings

logger = logging.getLogger("app.security")

SECRET_KEY = settings.JWT_SECRET_KEY
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES

# Evita subir com a chave padrão em produção
if SECRET_KEY == "change-me-in-production":
    logger.warning(
        "JWT_SECRET_KEY está usando o valor padrão. Defina SVPOS_SECRET_KEY em produção."
    )

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

    expire = datetime.now(timezone.utc) + expires_delta
    to_encode: Dict[str, Any] = {
        "sub": str(subject),
        "role": role,
        "exp": expire,
        "iss": settings.JWT_ISSUER,
        "aud": settings.JWT_AUDIENCE,
        "jti": uuid4().hex,
    }
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt
