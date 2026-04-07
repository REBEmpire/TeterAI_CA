import re

with open('src/embeddings/service.py', 'r') as f:
    content = f.read()

# Make VERTEX the default primary provider if not explicitly set
content = content.replace("self._primary = None", "self._primary = EmbeddingProvider.GOOGLE_VERTEX")

# We should make sure we always override VOYAGE with VERTEX for KG if the user specifically requested it
# The prompt says: "Using the gemini/vertex as primary and set to 768-dlm please."
override = """        # Determine primary provider
        if primary_provider:
            self._primary = primary_provider
        elif env_primary:
            try:
                self._primary = EmbeddingProvider(env_primary)
                # Override to VERTEX for 768-dim requirement
                if self._primary == EmbeddingProvider.VOYAGE:
                    logger.info("Overriding Voyage primary provider with Google Vertex to maintain 768-dim KG compatibility")
                    self._primary = EmbeddingProvider.GOOGLE_VERTEX
            except ValueError:
                logger.warning(f"Invalid EMBEDDING_PRIMARY_PROVIDER: {env_primary}")
                self._primary = EmbeddingProvider.GOOGLE_VERTEX
        else:
            self._primary = EmbeddingProvider.GOOGLE_VERTEX"""

content = re.sub(
    r"        # Determine primary provider\n        if primary_provider:\n            self\._primary = primary_provider\n        elif env_primary:\n            try:\n                self\._primary = EmbeddingProvider\(env_primary\)\n            except ValueError:\n                logger\.warning\(f\"Invalid EMBEDDING_PRIMARY_PROVIDER: \{env_primary\}\"\)\n                self\._primary = None\n        else:\n            self\._primary = None",
    override,
    content
)

with open('src/embeddings/service.py', 'w') as f:
    f.write(content)
