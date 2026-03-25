"""
Storage service factory.

Returns LocalStorageService when DESKTOP_MODE=true,
otherwise falls back to DriveService (cloud).
"""
import os


def get_storage_service(config=None, db_client=None):
    """
    Factory: return the appropriate storage service for the current mode.

    In DESKTOP_MODE returns LocalStorageService; otherwise DriveService.
    Both expose the same public API.
    """
    if os.environ.get("DESKTOP_MODE", "").lower() in ("true", "1"):
        from storage.local.service import LocalStorageService
        if config is None:
            from config.local_config import LocalConfig
            config = LocalConfig.ensure_exists()
        return LocalStorageService(config, db_client)
    else:
        from integrations.drive.service import DriveService
        return DriveService()
