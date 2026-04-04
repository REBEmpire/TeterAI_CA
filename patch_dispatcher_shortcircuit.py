with open('src/agents/dispatcher/agent.py', 'r') as f:
    content = f.read()

target = """            # Step 3: Classify via AI Engine
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

replacement = """            # Step 3: Classify via AI Engine (or Short-Circuit)
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

if "Area B1:" not in content and target in content:
    content = content.replace(target, replacement)
    with open('src/agents/dispatcher/agent.py', 'w') as f:
        f.write(content)
        print("Patched!")
else:
    print("Could not find target or already patched.")
