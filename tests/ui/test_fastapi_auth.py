import pytest
from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.testclient import TestClient

from src.ui.auth.models import Role, User
from src.ui.auth.auth import require_role

# Create a test app
app = FastAPI()

# Mock auth service for testing the Dependency Injection
class MockAuthService:
    def __init__(self):
        self.users = {
            "admin_user": User(uid="admin_user", email="a@a.com", role=Role.ADMIN),
            "staff_user": User(uid="staff_user", email="s@s.com", role=Role.CA_STAFF),
        }

    def get_user(self, uid):
        return self.users.get(uid)

# Inject mock into the auth module
import src.ui.auth.auth as auth_mod
auth_mod.auth_service = MockAuthService()

# Need to redefine dependencies to pick up the mocked service
def admin_required():
    return require_role([Role.ADMIN])

def staff_required():
    return require_role([Role.ADMIN, Role.CA_STAFF])

@app.get("/admin-only")
def admin_route(user=admin_required()):
    return {"message": "success"}

@app.get("/staff-only")
def staff_route(user=staff_required()):
    return {"message": "success"}

client = TestClient(app)

def test_admin_route():
    # Admin accesses
    res = client.get("/admin-only", headers={"X-User-UID": "admin_user"})
    assert res.status_code == 200

    # Staff accesses
    res = client.get("/admin-only", headers={"X-User-UID": "staff_user"})
    assert res.status_code == 403

    # Missing header
    res = client.get("/admin-only")
    assert res.status_code == 401

def test_staff_route():
    # Admin accesses
    res = client.get("/staff-only", headers={"X-User-UID": "admin_user"})
    assert res.status_code == 200

    # Staff accesses
    res = client.get("/staff-only", headers={"X-User-UID": "staff_user"})
    assert res.status_code == 200

    # Missing user
    res = client.get("/staff-only", headers={"X-User-UID": "unknown"})
    assert res.status_code == 401
