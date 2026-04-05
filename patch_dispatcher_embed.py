import re

with open('src/agents/dispatcher/agent.py', 'r') as f:
    content = f.read()

target = """            logger.info(
                f"[{task_id}] → {final_status} | "
                f"agent={routing.assigned_agent} | {routing.reason}"
            )
            processed_task_ids.append(task_id)"""

replacement = """            # Area C3: Wire embed_ingest into Dispatcher
            # Non-blocking embedding via asyncio/Thread
            def _run_embedding():
                try:
                    from embeddings.ingest_embedder import embed_ingest
                    attachment_paths = [
                        m.get("local_path", "")
                        for m in ingest.get("attachment_metadata", [])
                        if m.get("local_path")
                    ]

                    project_id_str = "unknown"
                    if classification and hasattr(classification, "project_id") and hasattr(classification.project_id, "value"):
                        project_id_str = classification.project_id.value

                    tool_type_str = "unknown"
                    if classification and hasattr(classification, "document_type") and hasattr(classification.document_type, "value"):
                        tool_type_str = classification.document_type.value

                    embed_result = embed_ingest(
                        ingest=ingest,
                        task_id=task_id,
                        project_id=project_id_str,
                        tool_type=tool_type_str,
                        body_text=ingest.get("body_text", ""),
                        attachment_local_paths=attachment_paths,
                    )
                    logger.info(
                        f"[{task_id}] Embedded {embed_result.chunk_count} chunks "
                        f"via {embed_result.embedding_provider}"
                    )
                except Exception as _ee:
                    logger.warning(f"[{task_id}] Embedding failed (non-fatal): {_ee}")

            import threading
            threading.Thread(target=_run_embedding, daemon=True, name=f"embed-{task_id[:12]}").start()

            logger.info(
                f"[{task_id}] → {final_status} | "
                f"agent={routing.assigned_agent} | {routing.reason}"
            )
            processed_task_ids.append(task_id)"""

if "Area C3:" not in content:
    content = content.replace(target, replacement)

with open('src/agents/dispatcher/agent.py', 'w') as f:
    f.write(content)
