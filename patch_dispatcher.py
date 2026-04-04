import re

with open('modified_agent.py', 'r') as f:
    modified = f.read()

# Wait, I added stuck_task recovery in `modified_agent.py`!
# Let's write a targeted script to extract just what we need and apply it cleanly to pristine_agent.py

with open('pristine_agent.py', 'r') as f:
    pristine = f.read()

target_stuck = """        # Load all pending ingests
        ingests = list(ingests_ref.where("status", "==", "PENDING_CLASSIFICATION").stream())
        if not ingests:
            return []"""

replacement_stuck = """        now = datetime.now(timezone.utc)

        # Area A3: Stuck task auto-recovery
        try:
            tasks_ref = db.collection("tasks")
            stuck_tasks = list(tasks_ref.where("status", "in", ["PENDING_CLASSIFICATION", "CLASSIFYING"]).stream())
            for task_doc in stuck_tasks:
                t_data = task_doc.to_dict()
                updated_str = t_data.get("updated_at")
                if not updated_str:
                    continue
                try:
                    updated_at = datetime.fromisoformat(updated_str)
                    # Configurable timeout, default 10 minutes
                    if (now - updated_at).total_seconds() > 600:
                        t_id = task_doc.id
                        i_id = t_data.get("ingest_id")
                        status = t_data.get("status")

                        if status == "PENDING_CLASSIFICATION":
                            logger.warning(f"[{t_id}] Task stuck in PENDING_CLASSIFICATION > 10m. Re-queueing.")
                            if i_id:
                                db.collection("email_ingests").document(i_id).update({"status": "PENDING_CLASSIFICATION"})
                            tasks_ref.document(t_id).update({"updated_at": now.isoformat()})
                        elif status == "CLASSIFYING":
                            logger.warning(f"[{t_id}] Task stuck in CLASSIFYING > 10m. Setting to ERROR.")
                            self._set_error(db, t_id, i_id, "Classification timed out — retried automatically", now)
                except Exception as e:
                    logger.error(f"Error checking stuck task {task_doc.id}: {e}")
        except Exception as e:
            logger.error(f"Failed to run stuck task recovery: {e}")

        # Load all pending ingests
        ingests = list(ingests_ref.where("status", "==", "PENDING_CLASSIFICATION").stream())
        if not ingests:
            return []"""

pristine = pristine.replace(target_stuck, replacement_stuck)

target_short = """            # Step 3: Classify via AI Engine
            task_start_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
            try:
                classification = self._classifier.classify(ingest)
            except AIEngineExhaustedError as e:
                logger.error(f"[{task_id}] AIEngine exhausted: {e}")
                self._set_error(db, task_id, ingest_id, str(e), now)
                audit_logger.log(ErrorLog(
                    component=AGENT_ID,
                    task_id=task_id,
                    error_code="AI_ENGINE_EXHAUSTED",
                    error_message=str(e),
                    severity=ErrorSeverity.ERROR,
                ))
                continue
            except ClassificationParseError as e:
                logger.error(f"[{task_id}] Classification parse error: {e}")
                self._set_error(db, task_id, ingest_id, str(e), now)
                audit_logger.log(ErrorLog(
                    component=AGENT_ID,
                    task_id=task_id,
                    error_code="CLASSIFICATION_PARSE_ERROR",
                    error_message=str(e),
                    severity=ErrorSeverity.ERROR,
                ))
                continue"""

replacement_short = """            # Step 3: Classify via AI Engine (or Short-Circuit)
            task_start_ms = int(datetime.now(timezone.utc).timestamp() * 1000)

            tool_type_hint = ingest.get("tool_type_hint")
            project_id_hint = ingest.get("project_id")

            if tool_type_hint and tool_type_hint not in ("unknown", "auto") and project_id_hint:
                from ai_engine.models import DimensionResult
                from agents.dispatcher.classifier import ClassificationResult

                logger.info(f"[{ingest_id}] Short-circuit: skipping AI classification (tool_type and project pre-specified)")
                classification = ClassificationResult(
                    project_id=DimensionResult(value=project_id_hint, confidence=1.0, reasoning="Pre-specified by user on upload"),
                    document_type=DimensionResult(value=tool_type_hint.upper(), confidence=1.0, reasoning="Pre-specified by user on upload"),
                    phase=DimensionResult(value="construction", confidence=0.8, reasoning="Default for manual upload"),
                    urgency=DimensionResult(value="MEDIUM", confidence=0.7, reasoning="Default for manual upload"),
                    ai_call_id=None
                )
            else:
                try:
                    classification = self._classifier.classify(ingest)
                except AIEngineExhaustedError as e:
                    logger.error(f"[{task_id}] AIEngine exhausted: {e}")
                    self._set_error(db, task_id, ingest_id, str(e), now)
                    audit_logger.log(ErrorLog(
                        component=AGENT_ID,
                        task_id=task_id,
                        error_code="AI_ENGINE_EXHAUSTED",
                        error_message=str(e),
                        severity=ErrorSeverity.ERROR,
                    ))
                    continue
                except ClassificationParseError as e:
                    logger.error(f"[{task_id}] Classification parse error: {e}")
                    self._set_error(db, task_id, ingest_id, str(e), now)
                    audit_logger.log(ErrorLog(
                        component=AGENT_ID,
                        task_id=task_id,
                        error_code="CLASSIFICATION_PARSE_ERROR",
                        error_message=str(e),
                        severity=ErrorSeverity.ERROR,
                    ))
                    continue"""

pristine = pristine.replace(target_short, replacement_short)

with open('src/agents/dispatcher/agent.py', 'w') as f:
    f.write(pristine)
