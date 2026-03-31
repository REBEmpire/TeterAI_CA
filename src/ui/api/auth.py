"""
Google OAuth 2.0 + JWT authentication for TeterAI web app.

Flow:
  1. Frontend redirects user to Google OAuth consent screen.
  2. Google returns an authorization code to /auth/google/callback.
  3. Backend exchanges code for Google ID token.
  4. Backend validates the token and checks the email domain.
  5. Backend looks up (or provisions) the user in Firestore users/{uid}.
  6. Backend issues a signed JWT returned to the frontend as a bearer token.
  7. All subsequent requests pass the JWT in the Authorization header.
"""
import hashlib
import hmac
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration (resolved at import-time from env or Secret Manager)
# ---------------------------------------------------------------------------

ALLOWED_EMAIL_DOMAIN = os.environ.get("ALLOWED_EMAIL_DOMAIN", "teter.com")
GOOGLE_OAUTH_CLIENT_ID = os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "")
SESSION_SECRET = os.environ.get("SESSION_SECRET", "dev-secret-change-in-prod")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = 8


# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------

def create_jwt(uid: str, email: str, display_name: str, role: str) -> str:
    """Issue a signed JWT valid for JWT_EXPIRE_HOURS hours."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": uid,
        "email": email,
        "name": display_name,
        "role": role,
        "iat": now,
        "exp": now + timedelta(hours=JWT_EXPIRE_HOURS),
    }
    return jwt.encode(payload, SESSION_SECRET, algorithm=JWT_ALGORITHM)


def decode_jwt(token: str) -> Optional[dict]:
    """
    Decode and verify a JWT. Returns the payload dict or None if invalid/expired.
    """
    try:
        return jwt.decode(token, SESSION_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        logger.warning("JWT expired.")
        return None
    except jwt.InvalidTokenError as exc:
        logger.warning(f"Invalid JWT: {exc}")
        return None


# ---------------------------------------------------------------------------
# Google ID token verification
# ---------------------------------------------------------------------------

def verify_google_id_token(google_id_token_str: str) -> Optional[dict]:
    """
    Verify a Google ID token and return the claims dict, or None on failure.
    Enforces ALLOWED_EMAIL_DOMAIN.
    """
    if not GOOGLE_OAUTH_CLIENT_ID:
        logger.warning("GOOGLE_OAUTH_CLIENT_ID not configured — skipping token verification.")
        return None

    try:
        from google.auth.transport import requests as google_requests
        from google.oauth2 import id_token
        claims = id_token.verify_oauth2_token(
            google_id_token_str,
            google_requests.Request(),
            GOOGLE_OAUTH_CLIENT_ID,
        )
    except Exception as exc:
        logger.warning(f"Google ID token verification failed: {exc}")
        return None

    email: str = claims.get("email", "")
    if not email.endswith(f"@{ALLOWED_EMAIL_DOMAIN}"):
        logger.warning(f"Login rejected — email domain not allowed: {email}")
        return None

    if not claims.get("email_verified"):
        logger.warning(f"Login rejected — email not verified: {email}")
        return None

    return claims


# ---------------------------------------------------------------------------
# User provisioning helper (called from route handler)
# ---------------------------------------------------------------------------

def get_or_create_user(db, claims: dict) -> dict:
    """
    Look up the user in Firestore users/{uid}. If not found, create with
    default role CA_STAFF. Returns the user dict (with 'role' key).
    """
    uid: str = claims["sub"]
    users_ref = db.collection("users").document(uid)
    doc = users_ref.get()

    if doc.exists:
        return doc.to_dict()

    user_data = {
        "uid": uid,
        "email": claims.get("email", ""),
        "display_name": claims.get("name", claims.get("email", "Unknown")),
        "role": "CA_STAFF",
        "active": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    users_ref.set(user_data)
    logger.info(f"Provisioned new user: {uid} ({user_data['email']})")
    return user_data


# ---------------------------------------------------------------------------
# Username / password login (test users for initial rollout)
# ---------------------------------------------------------------------------

# Passwords stored as SHA-256 hex digests — plaintext never in repo.
_TEST_USERS: dict[str, dict] = {
    "russell": {
        "uid": "test-russell",
        "email": "russell@teter.com",
        "display_name": "Russell",
        "role": "CA_STAFF",
        "hash": "1364bdecf8746a591d990e0ba1aad92abcdbb1e351620fbfe23bec4f4465bc5a",
    },
    "dustin": {
        "uid": "test-dustin",
        "email": "dustin@teter.com",
        "display_name": "Dustin",
        "role": "CA_STAFF",
        "hash": "c6101587842ebe757be860ec8c6e80b33ea3181b02248a55e8cf98ede1ee6549",
    },
    "pete": {
        "uid": "test-pete",
        "email": "pete@teter.com",
        "display_name": "Pete",
        "role": "CA_STAFF",
        "hash": "07e05a464e248fe682024edd4c25fe50bb4ef0f145c0a5d9c6d7d9ec5048bdcc",
    },
    "david": {
        "uid": "test-david",
        "email": "david@teter.com",
        "display_name": "David",
        "role": "CA_STAFF",
        "hash": "bb91a605e6f6811b5af02934ed58c5151d0656114aade0d4e2013d5d0c6d421e",
    },
}


def verify_password_login(username: str, password: str) -> Optional[dict]:
    """
    Validate a username/password against the test user list.
    Returns the user dict (without 'hash') on success, or None on failure.
    Uses constant-time comparison to prevent timing attacks.
    """
    user = _TEST_USERS.get(username.lower())
    if not user:
        return None
    actual = hashlib.sha256(password.encode()).hexdigest()
    if not hmac.compare_digest(actual, user["hash"]):
        return None
    return {k: v for k, v in user.items() if k != "hash"}
