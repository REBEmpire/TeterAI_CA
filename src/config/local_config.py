"""
Local configuration for desktop mode.
Reads/writes ~/.teterai/config.env (plain key=value file).
"""
import os
import logging
from dataclasses import dataclass, field, fields
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = Path.home() / ".teterai" / "config.env"
DEFAULT_PROJECTS_ROOT = str(Path.home() / "TeterAI" / "Projects")
DEFAULT_DB_PATH = str(Path.home() / "TeterAI" / "DB" / "teterai.db")
DEFAULT_INBOX_PATH = str(Path.home() / "TeterAI" / "Inbox")


@dataclass
class LocalConfig:
    # AI providers
    anthropic_api_key: str = ""
    google_api_key: str = ""
    google_ai_api_key: str = ""  # For Gemini embeddings
    xai_api_key: str = ""

    # GCP service account key file (Drive, Vertex AI, Secret Manager)
    google_application_credentials: str = ""

    # Embedding configuration
    voyage_api_key: str = ""       # Voyage-3 embeddings (1536-dim, recommended)
    huggingface_token: str = ""    # HuggingFace embeddings (BGE-large, local option)
    embedding_primary_provider: str = ""  # voyage/gemini/google_vertex/huggingface
    embedding_fallback_providers: str = ""  # comma-separated fallback order

    # Knowledge Graph (optional)
    neo4j_uri: str = ""
    neo4j_username: str = ""
    neo4j_password: str = ""

    # Supabase (pgvector storage)
    supabase_url: str = ""
    supabase_api_key: str = ""

    # Storage paths
    projects_root: str = DEFAULT_PROJECTS_ROOT
    db_path: str = DEFAULT_DB_PATH
    inbox_path: str = DEFAULT_INBOX_PATH

    # Desktop behaviour
    desktop_mode: bool = True
    watch_inbox_folder: bool = True
    poll_interval_seconds: int = 30

    @classmethod
    def from_env_file(cls, path: str | Path = DEFAULT_CONFIG_PATH) -> "LocalConfig":
        cfg = cls()
        p = Path(path)
        if p.exists():
            for line in p.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip().lower()
                value = value.strip()
                for f in fields(cls):
                    if f.name == key:
                        if f.type in ("bool", bool):
                            setattr(cfg, f.name, value.lower() in ("true", "1", "yes"))
                        elif f.type in ("int", int):
                            try:
                                setattr(cfg, f.name, int(value))
                            except ValueError:
                                pass
                        else:
                            setattr(cfg, f.name, value)
                        break
        return cfg

    def save(self, path: str | Path = DEFAULT_CONFIG_PATH) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        lines = ["# TeterAI CA — local desktop configuration\n"]
        for f in fields(self):
            lines.append(f"{f.name}={getattr(self, f.name)}\n")
        p.write_text("".join(lines))

    def push_to_env(self) -> None:
        """Push API keys into os.environ so LiteLLM / Neo4j / EmbeddingService pick them up."""
        mapping = {
            "anthropic_api_key": "ANTHROPIC_API_KEY",
            "google_api_key": "GOOGLE_API_KEY",
            "google_ai_api_key": "GOOGLE_AI_API_KEY",
            "xai_api_key": "XAI_API_KEY",
            "google_application_credentials": "GOOGLE_APPLICATION_CREDENTIALS",
            "voyage_api_key": "VOYAGE_API_KEY",
            "huggingface_token": "HUGGINGFACE_TOKEN",
            "embedding_primary_provider": "EMBEDDING_PRIMARY_PROVIDER",
            "embedding_fallback_providers": "EMBEDDING_FALLBACK_PROVIDERS",
            "neo4j_uri": "NEO4J_URI",
            "neo4j_username": "NEO4J_USERNAME",
            "neo4j_password": "NEO4J_PASSWORD",
            "supabase_url": "SUPABASE_URL",
            "supabase_api_key": "SB_API_KEY",
        }
        for attr, env_var in mapping.items():
            val = getattr(self, attr, "")
            if val and not os.environ.get(env_var):
                os.environ[env_var] = val

    @classmethod
    def ensure_exists(cls, path: str | Path = DEFAULT_CONFIG_PATH) -> "LocalConfig":
        """Load existing config or create a default one on first launch."""
        p = Path(path)
        if not p.exists():
            logger.info(f"First launch — creating config at {p}")
            cfg = cls()
            cfg.save(p)
        else:
            cfg = cls.from_env_file(p)
        return cfg
