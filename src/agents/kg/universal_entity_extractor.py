"""
Universal KG entity extractor — writes structured entities from ALL 5 document
types (RFI, Submittal, ScheduleReview, PayApp, CostAnalysis) into Neo4j.

Called from routes.py after any task reaches APPROVED status, regardless of
document type.  Falls back gracefully if Neo4j is unavailable or the AI call
fails — never raises to the caller.

Pattern mirrors flaw_extractor.py: uses the existing AIEngine CLASSIFY
capability with a structured prompt, then writes directly via Cypher MERGE.
No GCP dependencies — desktop-mode compatible.
"""
import logging
import uuid
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Cypher helpers
# ---------------------------------------------------------------------------

_UPSERT_PARTY = """
MERGE (p:Party {name: $name, party_type: $party_type})
ON CREATE SET p.created_at = datetime()
"""

_UPSERT_PROJECT = """
MERGE (proj:Project {project_id: $project_id})
ON CREATE SET proj.created_at = datetime()
"""

_UPSERT_SUBMITTAL = """
MERGE (s:Submittal {task_id: $task_id})
ON CREATE SET
    s.submittal_id     = $task_id,
    s.project_id       = $project_id,
    s.submittal_number = $doc_number,
    s.status_outcome   = $status_outcome,
    s.key_finding      = $key_finding,
    s.key_date         = $key_date,
    s.created_at       = datetime()
ON MATCH SET
    s.status_outcome   = $status_outcome,
    s.key_finding      = $key_finding
"""

_UPSERT_SCHEDULE_REVIEW = """
MERGE (sr:ScheduleReview {task_id: $task_id})
ON CREATE SET
    sr.schedule_review_id = $task_id,
    sr.project_id         = $project_id,
    sr.doc_number         = $doc_number,
    sr.status_outcome     = $status_outcome,
    sr.key_finding        = $key_finding,
    sr.key_date           = $key_date,
    sr.created_at         = datetime()
ON MATCH SET
    sr.status_outcome = $status_outcome,
    sr.key_finding    = $key_finding
"""

_UPSERT_PAY_APP = """
MERGE (pa:PayApp {task_id: $task_id})
ON CREATE SET
    pa.payapp_id       = $task_id,
    pa.project_id      = $project_id,
    pa.app_number      = $doc_number,
    pa.status_outcome  = $status_outcome,
    pa.key_finding     = $key_finding,
    pa.amount          = $amount,
    pa.period_date     = $key_date,
    pa.created_at      = datetime()
ON MATCH SET
    pa.status_outcome = $status_outcome,
    pa.key_finding    = $key_finding,
    pa.amount         = $amount
"""

_UPSERT_COST_ANALYSIS = """
MERGE (ca:CostAnalysis {task_id: $task_id})
ON CREATE SET
    ca.cost_analysis_id = $task_id,
    ca.project_id       = $project_id,
    ca.change_order_num = $doc_number,
    ca.status_outcome   = $status_outcome,
    ca.key_finding      = $key_finding,
    ca.amount           = $amount,
    ca.created_at       = datetime()
ON MATCH SET
    ca.status_outcome = $status_outcome,
    ca.key_finding    = $key_finding,
    ca.amount         = $amount
"""

_EDGE_DOC_SUBMITTED_BY = """
MATCH (d {task_id: $task_id})
MATCH (p:Party {name: $party_name, party_type: $party_type})
MERGE (d)-[:SUBMITTED_BY]->(p)
"""

_EDGE_PROJECT_HAS_DOC = {
    "submittal":        "MERGE (proj:Project {project_id: $project_id})-[:HAS_SUBMITTAL]->(d:Submittal {task_id: $task_id})",
    "schedule_review":  "MERGE (proj:Project {project_id: $project_id})-[:HAS_SCHEDULE_REVIEW]->(d:ScheduleReview {task_id: $task_id})",
    "pay_app":          "MERGE (proj:Project {project_id: $project_id})-[:HAS_PAY_APP]->(d:PayApp {task_id: $task_id})",
    "cost_analysis":    "MERGE (proj:Project {project_id: $project_id})-[:HAS_COST_ANALYSIS]->(d:CostAnalysis {task_id: $task_id})",
}

_UPSERT_SPEC_SECTION = """
MERGE (s:SpecSection {section_number: $section_number, project_id: $project_id})
ON CREATE SET s.created_at = datetime()
"""

_EDGE_DOC_REFERENCES_SPEC = """
MATCH (d {task_id: $task_id})
MATCH (s:SpecSection {section_number: $section_number, project_id: $project_id})
MERGE (d)-[:REFERENCES_SPEC]->(s)
"""

_BATCH_UPSERT_SPEC_SECTIONS = """
MATCH (d)
WHERE (d:RFI AND d.rfi_id = $task_id)
   OR (d:Submittal AND d.task_id = $task_id)
   OR (d:ScheduleReview AND d.task_id = $task_id)
   OR (d:PayApp AND d.task_id = $task_id)
   OR (d:CostAnalysis AND d.task_id = $task_id)
WITH d
UNWIND $sections AS section
MERGE (s:SpecSection {section_number: section, project_id: $project_id})
ON CREATE SET s.created_at = datetime()
MERGE (d)-[:REFERENCES_SPEC]->(s)
"""

# For RFI: also link Party as contractor
_UPSERT_RFI_PARTY_EDGE = """
MATCH (r:RFI {rfi_id: $task_id})
MATCH (p:Party {name: $party_name, party_type: $party_type})
MERGE (r)-[:SUBMITTED_BY]->(p)
"""

# ---------------------------------------------------------------------------
# Per-doc-type system prompts
# ---------------------------------------------------------------------------

_SYSTEM_PROMPTS = {
    "rfi": (
        "You are a construction administration expert. Extract structured entities from the "
        "RFI question and approved response below.\n\n"
        "Respond ONLY in this exact format (one value per line):\n"
        "PARTY_NAME: <contractor or firm name who submitted the RFI>\n"
        "PARTY_TYPE: <Contractor|Subcontractor|Owner>\n"
        "SPEC_SECTIONS: <comma-separated CSI section numbers, e.g. '08 41 13, 07 19 00', or empty>\n"
        "DOC_NUMBER: <RFI number, e.g. RFI-042, or empty>\n"
        "STATUS_OUTCOME: <Answered|Pending|Escalated>\n"
        "KEY_FINDING: <one sentence: what design issue or question was resolved>\n"
        "AMOUNT: \n"
        "KEY_DATE: <ISO date if a deadline or due date was mentioned, else empty>\n"
    ),
    "submittal": (
        "You are a construction administration expert. Extract structured entities from the "
        "submittal review below.\n\n"
        "Respond ONLY in this exact format (one value per line):\n"
        "PARTY_NAME: <vendor or subcontractor who submitted>\n"
        "PARTY_TYPE: <Vendor|Subcontractor|Contractor>\n"
        "SPEC_SECTIONS: <comma-separated CSI section numbers, or empty>\n"
        "DOC_NUMBER: <submittal number, e.g. SUB-042, or empty>\n"
        "STATUS_OUTCOME: <Approved|Rejected|ReviseResubmit|ApprovedAsNoted|NoteAction>\n"
        "KEY_FINDING: <one sentence: what product/material was reviewed and what was the outcome>\n"
        "AMOUNT: \n"
        "KEY_DATE: <ISO date if mentioned, else empty>\n"
    ),
    "schedule_review": (
        "You are a construction administration expert. Extract structured entities from the "
        "schedule review document below.\n\n"
        "Respond ONLY in this exact format (one value per line):\n"
        "PARTY_NAME: <contractor who submitted the schedule>\n"
        "PARTY_TYPE: <Contractor|Subcontractor>\n"
        "SPEC_SECTIONS: <comma-separated CSI section numbers if referenced, or empty>\n"
        "DOC_NUMBER: <schedule period or update number, e.g. SCH-003, or empty>\n"
        "STATUS_OUTCOME: <Approved|Rejected|ReviseResubmit|NoteAction>\n"
        "KEY_FINDING: <one sentence: key schedule finding, delay, or milestone status>\n"
        "AMOUNT: \n"
        "KEY_DATE: <ISO date of schedule period end or projected completion, or empty>\n"
    ),
    "pay_app": (
        "You are a construction administration expert. Extract structured entities from the "
        "payment application review below.\n\n"
        "Respond ONLY in this exact format (one value per line):\n"
        "PARTY_NAME: <contractor who submitted the pay application>\n"
        "PARTY_TYPE: <Contractor|Subcontractor>\n"
        "SPEC_SECTIONS: <comma-separated CSI section numbers if referenced, or empty>\n"
        "DOC_NUMBER: <application number, e.g. APP-007, or empty>\n"
        "STATUS_OUTCOME: <Approved|Rejected|ReviseResubmit|PartiallyApproved>\n"
        "KEY_FINDING: <one sentence: total amount requested, amount approved, any issues>\n"
        "AMOUNT: <dollar amount approved, e.g. 125000.00, or empty>\n"
        "KEY_DATE: <ISO date of period to date or payment date, or empty>\n"
    ),
    "cost_analysis": (
        "You are a construction administration expert. Extract structured entities from the "
        "cost analysis or change order review below.\n\n"
        "Respond ONLY in this exact format (one value per line):\n"
        "PARTY_NAME: <contractor or vendor who submitted the cost proposal>\n"
        "PARTY_TYPE: <Contractor|Subcontractor|Vendor>\n"
        "SPEC_SECTIONS: <comma-separated CSI section numbers if referenced, or empty>\n"
        "DOC_NUMBER: <change order or PCO number, e.g. PCO-012, or empty>\n"
        "STATUS_OUTCOME: <Approved|Rejected|NegotiationRequired|Pending>\n"
        "KEY_FINDING: <one sentence: scope of work and cost outcome>\n"
        "AMOUNT: <dollar amount, e.g. 34500.00, or empty>\n"
        "KEY_DATE: <ISO date if mentioned, else empty>\n"
    ),
}

# Mapping from doc_type → upsert Cypher
_DOC_UPSERTS = {
    "submittal":        _UPSERT_SUBMITTAL,
    "schedule_review":  _UPSERT_SCHEDULE_REVIEW,
    "pay_app":          _UPSERT_PAY_APP,
    "cost_analysis":    _UPSERT_COST_ANALYSIS,
}


# ---------------------------------------------------------------------------
# Response parser
# ---------------------------------------------------------------------------

def _parse_entity_response(text: str) -> dict:
    """Parse the structured AI response into a dict of entity fields."""
    fields = {
        "party_name": "",
        "party_type": "Contractor",
        "spec_sections": [],
        "doc_number": "",
        "status_outcome": "Pending",
        "key_finding": "",
        "amount": "",
        "key_date": "",
    }
    key_map = {
        "party_name":    "party_name",
        "party type":    "party_type",
        "party_type":    "party_type",
        "spec_sections": "spec_sections",
        "spec sections": "spec_sections",
        "doc_number":    "doc_number",
        "doc number":    "doc_number",
        "status_outcome":"status_outcome",
        "status outcome":"status_outcome",
        "key_finding":   "key_finding",
        "key finding":   "key_finding",
        "amount":        "amount",
        "key_date":      "key_date",
        "key date":      "key_date",
    }
    for line in text.splitlines():
        if ":" not in line:
            continue
        raw_key, _, raw_val = line.partition(":")
        field = key_map.get(raw_key.strip().lower())
        if not field:
            continue
        val = raw_val.strip()
        if field == "spec_sections":
            fields["spec_sections"] = [s.strip() for s in val.split(",") if s.strip()]
        else:
            if val:
                fields[field] = val

    # Normalise party_type
    pt = fields["party_type"].lower()
    if "vendor" in pt:
        fields["party_type"] = "Vendor"
    elif "subcontractor" in pt or "sub" in pt:
        fields["party_type"] = "Subcontractor"
    elif "owner" in pt:
        fields["party_type"] = "Owner"
    else:
        fields["party_type"] = "Contractor"

    if not fields["party_name"]:
        fields["party_name"] = "Unknown Party"
    if not fields["key_finding"]:
        fields["key_finding"] = text[:200] if text else "No finding recorded."

    return fields


# ---------------------------------------------------------------------------
# Main public function
# ---------------------------------------------------------------------------

def extract_and_store_entities(
    task_id: str,
    document_text: str,
    document_type: str,
    project_id: str,
    metadata: Optional[dict] = None,
    ai_engine=None,
) -> None:
    """
    Extract structured entities from any approved CA document and upsert
    them into Neo4j.

    Parameters
    ----------
    task_id        : Firestore / SQLite task ID (used as the node's task_id)
    document_text  : Combined question + response text (or full review text)
    document_type  : One of: "rfi", "submittal", "schedule_review",
                     "pay_app", "cost_analysis"
    project_id     : Project identifier
    metadata       : Optional dict with pre-known values (contractor_name,
                     doc_number, etc.) to supplement or override extraction
    ai_engine      : AIEngine instance; falls back to module singleton
    """
    doc_type = document_type.lower().replace(" ", "_").replace("-", "_")

    if doc_type not in _SYSTEM_PROMPTS:
        logger.debug(f"[{task_id}] universal extractor: unsupported doc_type '{doc_type}' — skipping.")
        return

    metadata = metadata or {}

    # ------------------------------------------------------------------
    # 1. Resolve AI engine
    # ------------------------------------------------------------------
    if ai_engine is None:
        try:
            from ai_engine.engine import engine as _engine
            ai_engine = _engine
        except Exception as e:
            logger.warning(f"[{task_id}] universal extractor: could not load AI engine — {e}")
            return

    # ------------------------------------------------------------------
    # 2. LLM extraction
    # ------------------------------------------------------------------
    system_prompt = _SYSTEM_PROMPTS[doc_type]
    user_prompt = f"DOCUMENT TEXT:\n{document_text[:4000]}"

    try:
        from ai_engine.models import AIRequest, CapabilityClass
        request = AIRequest(
            capability_class=CapabilityClass.CLASSIFY,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=0.0,
            calling_agent="kg_universal_extractor",
            task_id=task_id,
        )
        ai_response = ai_engine.generate_response(request)
        entities = _parse_entity_response(ai_response.content)
    except Exception as e:
        logger.warning(f"[{task_id}] universal extractor: AI call failed — {e}")
        return

    # Apply metadata overrides (pre-known values take precedence)
    if metadata.get("contractor_name"):
        entities["party_name"] = metadata["contractor_name"]
    if metadata.get("vendor_name"):
        entities["party_name"] = metadata["vendor_name"]
        entities["party_type"] = "Vendor"
    if metadata.get("doc_number"):
        entities["doc_number"] = metadata["doc_number"]

    logger.info(
        f"[{task_id}] universal extractor: doc_type={doc_type} "
        f"party='{entities['party_name']}' outcome='{entities['status_outcome']}'"
    )

    # ------------------------------------------------------------------
    # 3. Write to Neo4j
    # ------------------------------------------------------------------
    try:
        from knowledge_graph.client import kg_client
        driver = kg_client._driver
        if driver is None:
            logger.warning(f"[{task_id}] universal extractor: Neo4j driver not available — skipping.")
            return

        with driver.session() as session:
            # Ensure Project node exists
            session.run(_UPSERT_PROJECT, project_id=project_id)

            # Upsert Party node
            session.run(
                _UPSERT_PARTY,
                name=entities["party_name"],
                party_type=entities["party_type"],
            )

            params = dict(
                task_id=task_id,
                project_id=project_id,
                doc_number=entities["doc_number"],
                status_outcome=entities["status_outcome"],
                key_finding=entities["key_finding"],
                amount=entities["amount"],
                key_date=entities["key_date"],
            )

            if doc_type == "rfi":
                # RFI node already created/managed by flaw_extractor.
                # Just add SUBMITTED_BY edge to the Party.
                session.run(
                    _UPSERT_RFI_PARTY_EDGE,
                    task_id=task_id,
                    party_name=entities["party_name"],
                    party_type=entities["party_type"],
                )
            else:
                # Upsert the typed document node
                session.run(_DOC_UPSERTS[doc_type], **params)

                # Project → Document edge
                edge_cypher = _EDGE_PROJECT_HAS_DOC[doc_type]
                session.run(edge_cypher, project_id=project_id, task_id=task_id)

                # Document → Party edge
                session.run(
                    _EDGE_DOC_SUBMITTED_BY,
                    task_id=task_id,
                    party_name=entities["party_name"],
                    party_type=entities["party_type"],
                )

            # Spec section nodes + REFERENCES_SPEC edges (batched)
            if entities["spec_sections"]:
                session.run(
                    _BATCH_UPSERT_SPEC_SECTIONS,
                    sections=[s.strip() for s in entities["spec_sections"] if s.strip()],
                    project_id=project_id,
                    task_id=task_id,
                )

        logger.info(f"[{task_id}] universal extractor: Neo4j upsert complete.")

    except Exception as e:
        logger.warning(f"[{task_id}] universal extractor: Neo4j write failed (non-fatal) — {e}")
