"""
FastAPI dependency functions for authentication and role-based access control.

In DESKTOP_MODE (env DESKTOP_MODE=true) all auth checks are bypassed and a
hardcoded local ADMIN user is returned. This removes the need for Google OAuth
or JWT management when running as a single-user desktop application.
"""
import logging
import os
from typing import Annotated, Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .auth import decode_jwt
from .models import UserInfo

logger = logging.getLogger(__name__)

_DESKTOP_MODE = os.environ.get("DESKTOP_MODE", "").lower() in ("true", "1")

_DESKTOP_USER = UserInfo(
    uid="local",
    email="local@desktop",
    display_name="Desktop User",
    role="ADMIN",
)

_bearer = HTTPBearer(auto_error=not _DESKTOP_MODE)


def _extract_user(
    request: Request,
    credentials: Annotated[Optional[HTTPAuthorizationCredentials], Depends(_bearer)],
) -> UserInfo:
    """
    Validate the Bearer JWT and return the decoded UserInfo.
    In DESKTOP_MODE returns a hardcoded ADMIN user without any token check.
    """
    if _DESKTOP_MODE:
        return _DESKTOP_USER

    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated.",
            headers={"WWW-Authenticate": "Bearer"},
        )

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
    In DESKTOP_MODE the user is always ADMIN so all role checks pass.

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
