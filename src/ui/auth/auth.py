from typing import Callable, Any, List
from fastapi import Request, HTTPException, Depends

from .service import AuthService
from .models import Role

auth_service = AuthService()

def require_role(allowed_roles: List[Role]):
    """
    FastAPI dependency to protect routes based on user role.
    It expects a 'uid' parameter to be passed in headers,
    but for a production system, this would likely be extracted
    from a verified JWT token.
    """
    def verify_role(request: Request):
        uid = request.headers.get("X-User-UID")

        if not uid:
            raise HTTPException(status_code=401, detail="Missing user UID header")

        user = auth_service.get_user(uid)
        if not user:
            raise HTTPException(status_code=401, detail="User not found")

        if user.role not in allowed_roles:
            raise HTTPException(status_code=403, detail=f"Requires one of {allowed_roles}")

        return user

    return Depends(verify_role)

def admin_required():
    return require_role([Role.ADMIN])

def staff_required():
    return require_role([Role.ADMIN, Role.CA_STAFF])

def reviewer_required():
    return require_role([Role.ADMIN, Role.CA_STAFF, Role.REVIEWER])
