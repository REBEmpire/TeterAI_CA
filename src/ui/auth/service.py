from typing import Optional, List
from google.cloud import firestore
from datetime import datetime, timezone

from src.ai_engine.gcp import gcp_integration
from src.audit.logger import AuditLogger
from .models import Role, User

class AuthService:
    def __init__(self):
        # Using existing Firestore client from GCP integration
        self.db = gcp_integration.firestore_client
        # AuditLogger requires the GCPIntegration instance passed to it
        self.audit_logger = AuditLogger(gcp_integration)
        self.users_collection = "users"

    def get_user(self, uid: str) -> Optional[User]:
        """Fetch a user by their unique ID."""
        if not self.db:
            return None

        doc_ref = self.db.collection(self.users_collection).document(uid)
        doc = doc_ref.get()

        if doc.exists:
            return User.from_dict({"uid": uid, **doc.to_dict()})
        return None

    def create_user(self, user: User) -> bool:
        """Create a new user, defaults to REVIEWER if not specified."""
        if not self.db:
            return False

        doc_ref = self.db.collection(self.users_collection).document(user.uid)

        # Don't overwrite existing user
        if doc_ref.get().exists:
            return False

        data = user.to_dict()
        data["created_at"] = firestore.SERVER_TIMESTAMP
        data["role"] = user.role.value

        doc_ref.set(data)

        # Log user creation
        self.audit_logger.log_action(
            user_id="SYSTEM",
            action="USER_CREATED",
            resource_id=user.uid,
            details={"email": user.email, "role": user.role.value}
        )
        return True

    def get_role(self, uid: str) -> Optional[Role]:
        """Get the role of a user."""
        user = self.get_user(uid)
        if user:
            return user.role
        return None

    def update_role(self, admin_uid: str, target_uid: str, new_role: Role) -> bool:
        """
        Update a user's role.
        Requires the acting user (admin_uid) to be an ADMIN.
        """
        if not self.db:
            return False

        # Verify admin status
        admin_user = self.get_user(admin_uid)
        if not admin_user or admin_user.role != Role.ADMIN:
            self.audit_logger.log_action(
                user_id=admin_uid,
                action="ROLE_UPDATE_UNAUTHORIZED",
                resource_id=target_uid,
                details={"attempted_role": new_role.value}
            )
            return False

        target_ref = self.db.collection(self.users_collection).document(target_uid)
        target_doc = target_ref.get()

        if not target_doc.exists:
            return False

        old_role = target_doc.to_dict().get("role", "UNKNOWN")

        target_ref.update({"role": new_role.value})

        # Log role change per TETER-CA-AI-SEC-001 requirements
        self.audit_logger.log_action(
            user_id=admin_uid,
            action="USER_ROLE_UPDATED",
            resource_id=target_uid,
            details={"old_role": old_role, "new_role": new_role.value}
        )
        return True

    def list_users(self) -> List[User]:
        """List all users."""
        if not self.db:
            return []

        users = []
        docs = self.db.collection(self.users_collection).stream()
        for doc in docs:
            users.append(User.from_dict({"uid": doc.id, **doc.to_dict()}))
        return users
