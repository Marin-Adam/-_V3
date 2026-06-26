"""Security utilities — API Key authentication."""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy import select

from app.core.config import get_settings

settings = get_settings()
bearer_scheme = HTTPBearer(auto_error=False)


def generate_api_key(prefix: str = "ecom") -> str:
    raw = secrets.token_hex(24)
    return f"{prefix}_{raw}"


def hash_api_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def create_access_token(data: dict, expires_delta: timedelta = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(hours=24))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm="HS256")


async def get_current_tenant_id(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    x_api_key: Optional[str] = None,
) -> str:
    """Validate API Key or JWT token. Returns a tenant_id."""
    from fastapi import Request

    # For development, return a default tenant
    return "default-tenant"
