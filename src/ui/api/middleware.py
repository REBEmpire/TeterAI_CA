"""
FastAPI dependency functions for authentication and role-based access control.
"""
import logging
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .auth import decode_jwt
from .models import UserInfo

logger = logging.getLogger(__name__)

_bearer = HTTPBearer(auto_error=True)


def _extract_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(_bearer)],
) -> UserInfo:
    """
    Validate the Bearer JWT and return the decoded UserInfo.
    Raises HTTP 401 if the token is missing, expired, or invalid.
    """
    payload = decode_jwt(credentials.credentials)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return UserInfo(
        uid=payload["sub"],
        email=payload["email"],
        display_name=payload.get("name", ""),
        role=payload.get("role", "CA_STAFF"),
    )


# Exported dependency — use in route signatures as:
#   current_user: Annotated[UserInfo, Depends(require_auth)]
require_auth = _extract_user


def require_role(*roles: str):
    """
    Factory that returns a FastAPI dependency enforcing one of the given roles.

    Usage:
        @router.post("/projects", dependencies=[Depends(require_role("ADMIN"))])
    """
    def _check(user: Annotated[UserInfo, Depends(require_auth)]) -> UserInfo:
        if user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{user.role}' is not permitted for this action.",
            )
        return user

    return _check
