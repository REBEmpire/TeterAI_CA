import os
from typing import Dict, Any, Optional
from google.cloud import firestore
from google.cloud import secretmanager
from google.auth.exceptions import DefaultCredentialsError
from .models import ModelRegistry

class GCPIntegration:
    def __init__(self, project_id: str = "teterai-ca-prototype", database: str = "teterai-ca"):
        self.project_id = project_id
        self.database = database
        try:
            self.firestore_client = firestore.Client(project=project_id, database=database)
            self.secret_client = secretmanager.SecretManagerServiceClient()
        except DefaultCredentialsError:
            self.firestore_client = None
            self.secret_client = None

    def get_secret(self, secret_id: str, version_id: str = "latest") -> Optional[str]:
        if not self.secret_client:
            return None
        name = f"projects/{self.project_id}/secrets/{secret_id}/versions/{version_id}"
        try:
            response = self.secret_client.access_secret_version(request={"name": name})
            return response.payload.data.decode("UTF-8")
        except Exception as e:
            print(f"Error accessing secret {secret_id}: {e}")
            return None

    def load_secrets_to_env(self):
        secrets = {
            "anthropic-key": "ANTHROPIC_API_KEY",
            "google-ai-key": "GOOGLE_API_KEY",
            "xai-key": "XAI_API_KEY",
        }
        for secret_id, env_var in secrets.items():
            if not os.environ.get(env_var):
                val = self.get_secret(secret_id)
                if val:
                    os.environ[env_var] = val

    def get_model_registry(self, collection: str = "ai_engine", document: str = "model_registry") -> Optional[ModelRegistry]:
        if not self.firestore_client:
            return None
        try:
            doc_ref = self.firestore_client.collection(collection).document(document)
            doc = doc_ref.get()
            if doc.exists:
                return ModelRegistry(**doc.to_dict())
            return None
        except Exception as e:
            print(f"Error fetching model registry: {e}")
            return None

gcp_integration = GCPIntegration()
