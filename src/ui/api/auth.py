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
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

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
