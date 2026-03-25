"""
LocalIntegration — drop-in replacement for GCPIntegration in desktop mode.

Exposes the same public interface as GCPIntegration so that no agent code
needs to know which backend is in use:
  - firestore_client  → SQLiteClient (Firestore-compatible API)
  - get_secret(...)   → reads from LocalConfig
  - load_secrets_to_env() → pushes API keys to os.environ
  - get_model_registry()  → reads from SQLite model_registry table
"""
import json
import logging
import os
from pathlib import Path
from typing import Optional

from config.local_config import LocalConfig
from db.sqlite.client import SQLiteClient

logger = logging.getLogger(__name__)

# Path to the bundled default model registry (committed to repo)
_DEFAULT_REGISTRY_PATH = Path(__file__).parent.parent / "ai_engine" / "default_registry.json"

_SECRET_MAP = {
    "anthropic-key": "anthropic_api_key",
    "google-ai-key": "google_api_key",
    "xai-key": "xai_api_key",
    "neo4j-uri": "neo4j_uri",
    "neo4j-username": "neo4j_username",
    "neo4j-password": "neo4j_password",
    "integrations/gmail/oauth-client-id": None,
    "integrations/gmail/oauth-client-secret": None,
    "integrations/gmail/oauth-refresh-token": None,
    "drive-service-account": None,
}


class LocalIntegration:
    """Desktop-mode replacement for GCPIntegration."""

    def __init__(self, config: LocalConfig, db_client: Optional[SQLiteClient] = None):
        self._config = config
        self.secret_client = None  # no Secret Manager in desktop mode
        self.project_id = "local"

        if db_client is None:
            db_client = SQLiteClient(config.db_path)
        self.firestore_client = db_client

    def get_secret(self, secret_id: str, version_id: str = "latest") -> Optional[str]:
        attr = _SECRET_MAP.get(secret_id)
        if attr is None:
            return None
        return getattr(self._config, attr, None) or None

    def load_secrets_to_env(self) -> None:
        self._config.push_to_env()

    def get_model_registry(self, collection: str = "ai_engine", document: str = "model_registry"):
        """Read model registry from SQLite; fall back to bundled default_registry.json."""
        from ai_engine.models import ModelRegistry

        # Try SQLite first
        try:
            row = self.firestore_client._conn().execute(
                "SELECT config FROM model_registry WHERE id=1"
            ).fetchone()
            if row:
                return ModelRegistry(**json.loads(row["config"]))
        except Exception as e:
            logger.debug(f"SQLite model_registry read failed: {e}")

        # Fall back to bundled default
        if _DEFAULT_REGISTRY_PATH.exists():
            try:
                data = json.loads(_DEFAULT_REGISTRY_PATH.read_text())
                return ModelRegistry(**data)
            except Exception as e:
                logger.warning(f"Failed to load default_registry.json: {e}")

        return None
