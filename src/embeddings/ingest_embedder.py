import logging
from dataclasses import dataclass
from typing import Optional

from document_intelligence.storage.chunk_store import ChunkStore
from embeddings.service import get_embedding_service
from document_intelligence.extractors.pdf_extractor import PdfExtractor

logger = logging.getLogger(__name__)

@dataclass
class EmbedIngestResult:
    chunk_count: int
    embedding_provider: str
    error: Optional[str] = None  # None on success

def chunk_text(text: str, chunk_size: int = 1000, overlap: int = 50) -> list[str]:
    """Split text into chunks by sentence boundaries."""
    # Approximate 1 token ~= 4 chars
    char_chunk_size = chunk_size * 4
    char_overlap = overlap * 4

    sentences = text.split('. \n')
    chunks = []
    current_chunk = ""

    for sentence in sentences:
        if len(current_chunk) + len(sentence) < char_chunk_size:
            current_chunk += sentence + '. \n'
        else:
            chunks.append(current_chunk.strip())
            # Primitive overlap: just take the last few characters
            current_chunk = current_chunk[-char_overlap:] + sentence + '. \n' if current_chunk else sentence + '. \n'

    if current_chunk.strip():
        chunks.append(current_chunk.strip())

    return chunks

def embed_ingest(
    ingest: dict,
    task_id: str,
    project_id: str,
    tool_type: str,
    body_text: str,
    attachment_local_paths: list[str],
) -> EmbedIngestResult:

    try:
        from config.local_config import LocalConfig
        cfg = LocalConfig.ensure_exists()
        chunk_store = ChunkStore(db_path=cfg.db_path)

        all_text = body_text or ""

        # Area C2: If body_text is empty and we have a PDF, extract vision text
        if len(all_text) < 100 and attachment_local_paths:
            for path in attachment_local_paths:
                if path.lower().endswith('.pdf'):
                    extracted = extract_text_from_pdf(path)
                    all_text += "\n" + extracted

        chunks = chunk_text(all_text)
        embed_svc = get_embedding_service()

        provider = "unknown"
        if embed_svc and embed_svc.provider:
            provider = embed_svc.provider.name if hasattr(embed_svc.provider, 'name') else str(embed_svc.provider.__class__.__name__)

        success_count = 0
        for i, text_chunk in enumerate(chunks):
            if not text_chunk:
                continue

            try:
                embedding = embed_svc.embed(text_chunk)
                # Store the chunk with embedding bytes. Assuming `embedding` is a list of floats.
                # ChunkStore expects bytes for the embedding column
                import json
                emb_bytes = json.dumps(embedding).encode('utf-8')

                chunk_store.add_chunk(
                    project_id=project_id,
                    document_id=task_id,
                    chunk_index=i,
                    text_content=text_chunk,
                    chunk_type=tool_type,
                    embedding=emb_bytes,
                    metadata={"source": "ingest_embedder", "task_id": task_id}
                )
                success_count += 1
            except Exception as e:
                logger.warning(f"Failed to embed/store chunk {i} for task {task_id}: {e}")

        return EmbedIngestResult(
            chunk_count=success_count,
            embedding_provider=provider,
            error=None
        )

    except Exception as e:
        logger.error(f"embed_ingest failed: {e}")
        return EmbedIngestResult(
            chunk_count=0,
            embedding_provider="none",
            error=str(e)
        )
