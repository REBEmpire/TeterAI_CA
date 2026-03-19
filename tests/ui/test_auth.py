import pytest
import os
from src.ui.auth.models import Role, User
from src.ui.auth.service import AuthService
from src.ai_engine.gcp import GCPIntegration

@pytest.fixture(scope="session")
def gcp():
    return GCPIntegration()

@pytest.fixture
def auth_service(gcp):
    if not gcp.firestore_client:
        pytest.skip("No Firestore credentials available")
    return AuthService()

def test_user_creation_and_retrieval(auth_service):
    # Setup
    uid = "test_user_123"
    email = "test1@example.com"
    user = User(uid=uid, email=email, role=Role.REVIEWER)

    # Clean up existing before test
    doc_ref = auth_service.db.collection(auth_service.users_collection).document(uid)
    doc_ref.delete()

    # Test creation
    assert auth_service.create_user(user) == True

    # Test duplicate creation returns False
    assert auth_service.create_user(user) == False

    # Test retrieval
    fetched_user = auth_service.get_user(uid)
    assert fetched_user is not None
    assert fetched_user.uid == uid
    assert fetched_user.email == email
    assert fetched_user.role == Role.REVIEWER

    # Cleanup
    doc_ref.delete()

def test_role_update_authorization(auth_service):
    # Setup users
    admin_uid = "test_admin"
    admin_user = User(uid=admin_uid, email="admin@example.com", role=Role.ADMIN)

    staff_uid = "test_staff"
    staff_user = User(uid=staff_uid, email="staff@example.com", role=Role.CA_STAFF)

    target_uid = "test_target"
    target_user = User(uid=target_uid, email="target@example.com", role=Role.REVIEWER)

    # Cleanup previous
    admin_ref = auth_service.db.collection(auth_service.users_collection).document(admin_uid)
    staff_ref = auth_service.db.collection(auth_service.users_collection).document(staff_uid)
    target_ref = auth_service.db.collection(auth_service.users_collection).document(target_uid)
    admin_ref.delete()
    staff_ref.delete()
    target_ref.delete()

    # Create users
    auth_service.create_user(admin_user)
    auth_service.create_user(staff_user)
    auth_service.create_user(target_user)

    # Test 1: Staff cannot update role
    assert auth_service.update_role(staff_uid, target_uid, Role.CA_STAFF) == False

    # Verify role didn't change
    assert auth_service.get_role(target_uid) == Role.REVIEWER

    # Test 2: Admin can update role
    assert auth_service.update_role(admin_uid, target_uid, Role.CA_STAFF) == True

    # Verify role changed
    assert auth_service.get_role(target_uid) == Role.CA_STAFF

    # Cleanup
    admin_ref.delete()
    staff_ref.delete()
    target_ref.delete()
