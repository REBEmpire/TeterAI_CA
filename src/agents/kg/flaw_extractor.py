"""
Extracts design flaw categories from approved RFI tasks and upserts them
into the Neo4j knowledge graph for pattern analysis.

Called after a task reaches APPROVED status (from workflow engine or routes.py).
"""
import logging
import uuid
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Cypher helpers for upserting design-flaw nodes/relationships
# ---------------------------------------------------------------------------

_UPSERT_RFI_NODE = """
MERGE (r:RFI {rfi_id: $rfi_id})
ON CREATE SET
    r.project_id = $project_id,
    r.created_at = datetime()
ON MATCH SET
    r.project_id = $project_id
"""

_UPSERT_FLAW_NODE = """
MERGE (f:DESIGN_FLAW {category: $category, project_id: $project_id})
ON CREATE SET
    f.flaw_id    = $flaw_id,
    f.description = $description,
    f.created_at = datetime()
ON MATCH SET
    f.description = $description
"""

_UPSERT_ACTION_NODE = """
MERGE (a:CORRECTIVE_ACTION {action: $action, project_id: $project_id})
ON CREATE SET
    a.action_id  = $action_id,
    a.created_at = datetime()
"""

_EDGE_RFI_REVEALS_FLAW = """
MATCH (r:RFI {rfi_id: $rfi_id})
MATCH (f:DESIGN_FLAW {category: $category, project_id: $project_id})
MERGE (r)-[:REVEALS]->(f)
"""

_EDGE_FLAW_SUGGESTS_ACTION = """
MATCH (f:DESIGN_FLAW {category: $category, project_id: $project_id})
MATCH (a:CORRECTIVE_ACTION {action: $action, project_id: $project_id})
MERGE (f)-[:SUGGESTS]->(a)
"""

_UPSERT_SPEC_SECTION_NODE = """
MERGE (s:SpecSection {section_number: $section_number, project_id: $project_id})
ON CREATE SET
    s.title      = $section_number,
    s.created_at = datetime()
"""

_EDGE_RFI_REFERENCES_SPEC = """
MATCH (r:RFI {rfi_id: $rfi_id})
MATCH (s:SpecSection {section_number: $section_number, project_id: $project_id})
MERGE (r)-[:REFERENCES_SPEC]->(s)
"""


def _parse_flaw_response(text: str) -> tuple[str, str, str]:
    """
    Parse a structured AI response into (flaw_category, flaw_description, corrective_action).

    Expected format (flexible — lines starting with the key labels):
        FLAW_CATEGORY: <value>
        FLAW_DESCRIPTION: <value>
        CORRECTIVE_ACTION: <value>

    Falls back to returning the full text as the description if parsing fails.
    """
    category = ""
    description = ""
    corrective_action = ""

    for line in text.splitlines():
        stripped = line.strip()
        lower = stripped.lower()
        if lower.startswith("flaw_category:") or lower.startswith("flaw category:"):
            category = stripped.split(":", 1)[1].strip()
        elif lower.startswith("flaw_description:") or lower.startswith("flaw description:"):
            description = stripped.split(":", 1)[1].strip()
        elif lower.startswith("corrective_action:") or lower.startswith("corrective action:"):
            corrective_action = stripped.split(":", 1)[1].strip()

    # Graceful fallback
    if not category:
        category = "Unclassified Design Flaw"
    if not description:
        description = text[:500] if text else "No description available."
    if not corrective_action:
        corrective_action = "Review and clarify design intent with the engineer of record."

    return category, description, corrective_action


def extract_and_store_flaw(
    task_id: str,
    rfi_question: str,
    rfi_response: str,
    spec_sections: list,
    project_id: str,
    ai_engine=None,
) -> None:
    """
    Extract a design flaw category from an approved RFI and upsert the
    resulting nodes/relationships into Neo4j.

    Parameters
    ----------
    task_id       : Firestore task document ID (used as rfi_id in KG)
    rfi_question  : Original question text from the RFI
    rfi_response  : Approved response text
    spec_sections : List of spec section strings cited in the task (e.g. ["08 41 13", "03 30 00"])
    project_id    : Firestore project ID
    ai_engine     : An instantiated AIEngine; if None the module-level singleton is used
    """
    # ------------------------------------------------------------------
    # 1. Resolve AI engine
    # ------------------------------------------------------------------
    if ai_engine is None:
        try:
            from ai_engine.engine import engine as _engine
            ai_engine = _engine
        except Exception as e:
            logger.warning(f"[{task_id}] KG extractor: could not load AI engine — {e}")
            return

    # ------------------------------------------------------------------
    # 2. Ask the AI to classify the design flaw
    # ------------------------------------------------------------------
    system_prompt = (
        "You are a construction administration expert. "
        "Analyse the RFI question and approved response below and identify:\n"
        "1. The primary design flaw category revealed (e.g. 'Incomplete Details', "
        "'Coordination Conflict', 'Specification Ambiguity', 'Omitted Requirement', "
        "'Constructability Issue').\n"
        "2. A brief description of the specific flaw.\n"
        "3. A recommended corrective action to prevent recurrence.\n\n"
        "Respond ONLY in this exact format:\n"
        "FLAW_CATEGORY: <short category name>\n"
        "FLAW_DESCRIPTION: <one sentence>\n"
        "CORRECTIVE_ACTION: <one sentence>\n"
    )
    user_prompt = (
        f"RFI QUESTION:\n{rfi_question}\n\n"
        f"APPROVED RESPONSE:\n{rfi_response}"
    )

    try:
        from ai_engine.models import AIRequest, CapabilityClass
        request = AIRequest(
            capability_class=CapabilityClass.CLASSIFY,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=0.1,
            calling_agent="kg_flaw_extractor",
            task_id=task_id,
        )
        ai_response = ai_engine.generate_response(request)
        raw_text = ai_response.content
    except Exception as e:
        logger.warning(f"[{task_id}] KG extractor: AI call failed — {e}")
        return

    flaw_category, flaw_description, corrective_action = _parse_flaw_response(raw_text)
    logger.info(
        f"[{task_id}] KG extractor: category='{flaw_category}' action='{corrective_action[:60]}...'"
    )

    # ------------------------------------------------------------------
    # 3. Upsert into Neo4j
    # ------------------------------------------------------------------
    try:
        from knowledge_graph.client import kg_client
        driver = kg_client._driver
        if driver is None:
            logger.warning(f"[{task_id}] KG extractor: Neo4j driver not available — skipping upsert.")
            return

        flaw_id = str(uuid.uuid4())
        action_id = str(uuid.uuid4())

        with driver.session() as session:
            # RFI node (ensure it exists)
            session.run(_UPSERT_RFI_NODE, rfi_id=task_id, project_id=project_id)

            # DESIGN_FLAW node
            session.run(
                _UPSERT_FLAW_NODE,
                flaw_id=flaw_id,
                category=flaw_category,
                description=flaw_description,
                project_id=project_id,
            )

            # CORRECTIVE_ACTION node
            session.run(
                _UPSERT_ACTION_NODE,
                action_id=action_id,
                action=corrective_action,
                project_id=project_id,
            )

            # RFI -[REVEALS]-> DESIGN_FLAW
            session.run(
                _EDGE_RFI_REVEALS_FLAW,
                rfi_id=task_id,
                category=flaw_category,
                project_id=project_id,
            )

            # DESIGN_FLAW -[SUGGESTS]-> CORRECTIVE_ACTION
            session.run(
                _EDGE_FLAW_SUGGESTS_ACTION,
                category=flaw_category,
                action=corrective_action,
                project_id=project_id,
            )

            # SpecSection nodes + RFI -[REFERENCES_SPEC]-> SpecSection
            for section in spec_sections:
                if not section:
                    continue
                section_str = str(section).strip()
                session.run(
                    _UPSERT_SPEC_SECTION_NODE,
                    section_number=section_str,
                    project_id=project_id,
                )
                session.run(
                    _EDGE_RFI_REFERENCES_SPEC,
                    rfi_id=task_id,
                    section_number=section_str,
                    project_id=project_id,
                )

        logger.info(f"[{task_id}] KG extractor: upsert complete.")

    except Exception as e:
        logger.warning(f"[{task_id}] KG extractor: Neo4j upsert failed (non-fatal) — {e}")
