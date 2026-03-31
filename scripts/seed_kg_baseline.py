"""
Seed the Neo4j Knowledge Graph with Tier 1 (Agent Playbooks),
Tier 2 (Workflow Process), and Tier 4 (Industry Knowledge) baseline data.

Usage:
    python scripts/seed_kg_baseline.py              # seed everything
    python scripts/seed_kg_baseline.py --dry-run    # preview counts only
    python scripts/seed_kg_baseline.py --tier 2     # seed only Tier 2
    python scripts/seed_kg_baseline.py --no-embed   # skip embedding generation
"""
import sys
import os
import argparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import neo4j
from ai_engine.engine import engine as ai_engine

# ===========================================================================
# TIER 2 — Workflow Process
# ===========================================================================

DOCUMENT_TYPES = [
    {"type_id": "RFI",            "name": "Request for Information",              "phase": "construction", "numbering_prefix": "RFI-",     "response_deadline_days": 10},
    {"type_id": "SUBMITTAL",      "name": "Submittal",                            "phase": "construction", "numbering_prefix": "SUB-",     "response_deadline_days": 14},
    {"type_id": "SUB_REQ",        "name": "Substitution Request",                 "phase": "construction", "numbering_prefix": "SUB-REQ-", "response_deadline_days": 10},
    {"type_id": "PCO_COR",        "name": "Proposed Change Order / COR",          "phase": "construction", "numbering_prefix": "PCO-",     "response_deadline_days": 21},
    {"type_id": "BULLETIN",       "name": "Bulletin",                             "phase": "construction", "numbering_prefix": "BUL-",     "response_deadline_days": 0},
    {"type_id": "CHANGE_ORDER",   "name": "Change Order",                         "phase": "construction", "numbering_prefix": "CO-",      "response_deadline_days": 14},
    {"type_id": "PAY_APP",        "name": "Pay Application",                      "phase": "construction", "numbering_prefix": "PAY-",     "response_deadline_days": 7},
    {"type_id": "MEETING_MINUTES","name": "Meeting Minutes",                      "phase": "construction", "numbering_prefix": "MM-",      "response_deadline_days": 3},
    {"type_id": "PB_RFI",         "name": "Pre-Bid Request for Information",      "phase": "bid",          "numbering_prefix": "PB-RFI-",  "response_deadline_days": 5},
    {"type_id": "ADDENDUM",       "name": "Addendum",                             "phase": "bid",          "numbering_prefix": "ADD-",     "response_deadline_days": 0},
]

RFI_WORKFLOW_STEPS = [
    {"step_id": "RFI-WF-01", "name": "Receipt",            "description": "Email received and parsed by Gmail Integration. Attachments saved to Holding Folder.",  "responsible_party": "ca_agent",  "sequence": 1},
    {"step_id": "RFI-WF-02", "name": "Acknowledge",        "description": "Send acknowledgment to contractor within 24 hours confirming receipt of RFI.",           "responsible_party": "ca_agent",  "sequence": 2},
    {"step_id": "RFI-WF-03", "name": "Route to Architect", "description": "Forward to responsible architect of record for technical review.",                        "responsible_party": "ca_staff",  "sequence": 3},
    {"step_id": "RFI-WF-04", "name": "Draft Response",     "description": "RFI Agent drafts a response referencing contract drawings and specifications.",           "responsible_party": "ca_agent",  "sequence": 4},
    {"step_id": "RFI-WF-05", "name": "CA Review",          "description": "CA staff reviews and approves or revises the drafted response before issue.",             "responsible_party": "ca_staff",  "sequence": 5},
    {"step_id": "RFI-WF-06", "name": "Issue Response",     "description": "Approved response sent to contractor via email; document filed in project Drive folder.", "responsible_party": "ca_agent",  "sequence": 6},
    {"step_id": "RFI-WF-07", "name": "Close",              "description": "RFI marked closed in system. Final document archived in 02 - Construction/RFIs/.",        "responsible_party": "ca_agent",  "sequence": 7},
]

OTHER_DOC_TYPE_STEP_TEMPLATE = {
    "name": "Human Processing",
    "description": "Document type handled manually by CA staff in Phase 0. Agent automation planned for Phase 1.",
    "responsible_party": "ca_staff",
    "sequence": 1,
}

# ===========================================================================
# TIER 4 — Industry Knowledge
# ===========================================================================

CSI_DIVISIONS = [
    {"csi_division": "01", "section_number": "01 00 00", "title": "General Requirements",           "content_summary": "Project management, administrative procedures, temporary facilities, quality requirements, and project closeout.", "keywords": ["general requirements", "administrative", "project management", "closeout", "quality"]},
    {"csi_division": "02", "section_number": "02 00 00", "title": "Existing Conditions",            "content_summary": "Subsurface investigation, hazardous material assessment, existing structure demolition, and utility identification.", "keywords": ["existing conditions", "subsurface", "demolition", "hazardous materials", "utilities"]},
    {"csi_division": "03", "section_number": "03 00 00", "title": "Concrete",                       "content_summary": "Cast-in-place concrete, precast concrete, grout, and concrete restoration. Includes mix design, reinforcement, and formwork.", "keywords": ["concrete", "reinforcement", "rebar", "formwork", "precast", "slab", "footing"]},
    {"csi_division": "04", "section_number": "04 00 00", "title": "Masonry",                        "content_summary": "Unit masonry, stone assemblies, and masonry restoration. Includes CMU, brick, mortar, and grout specifications.", "keywords": ["masonry", "CMU", "brick", "mortar", "block", "stone"]},
    {"csi_division": "05", "section_number": "05 00 00", "title": "Metals",                         "content_summary": "Structural steel, steel joists, metal decking, cold-formed metal framing, and miscellaneous metals.", "keywords": ["steel", "structural steel", "metal decking", "joists", "fabrication", "welding"]},
    {"csi_division": "06", "section_number": "06 00 00", "title": "Wood, Plastics, and Composites", "content_summary": "Rough carpentry, finish carpentry, architectural woodwork, structural panels, and composite materials.", "keywords": ["wood", "carpentry", "lumber", "plywood", "millwork", "cabinets"]},
    {"csi_division": "07", "section_number": "07 00 00", "title": "Thermal and Moisture Protection","content_summary": "Waterproofing, dampproofing, insulation, roofing, flashing, sheet metal, and joint sealants.", "keywords": ["waterproofing", "roofing", "insulation", "flashing", "sealant", "vapor barrier"]},
    {"csi_division": "08", "section_number": "08 00 00", "title": "Openings",                       "content_summary": "Doors, frames, hardware, windows, curtain walls, glazing, and storefronts.", "keywords": ["doors", "windows", "hardware", "glazing", "curtain wall", "storefront", "frames"]},
    {"csi_division": "09", "section_number": "09 00 00", "title": "Finishes",                       "content_summary": "Plaster, gypsum board, tiling, flooring, acoustical ceilings, painting, and wall coverings.", "keywords": ["finishes", "drywall", "gypsum", "tile", "flooring", "paint", "ceiling", "acoustical"]},
    {"csi_division": "10", "section_number": "10 00 00", "title": "Specialties",                    "content_summary": "Visual display boards, compartments, lockers, fire protection specialties, and signage.", "keywords": ["specialties", "signage", "lockers", "toilet partitions", "fire extinguisher"]},
    {"csi_division": "11", "section_number": "11 00 00", "title": "Equipment",                      "content_summary": "Foodservice equipment, laboratory equipment, athletic equipment, and other owner-furnished items.", "keywords": ["equipment", "foodservice", "laboratory", "athletic"]},
    {"csi_division": "12", "section_number": "12 00 00", "title": "Furnishings",                    "content_summary": "Window treatments, furniture, and furnishing accessories.", "keywords": ["furnishings", "furniture", "window treatment", "blinds"]},
    {"csi_division": "13", "section_number": "13 00 00", "title": "Special Construction",           "content_summary": "Pre-engineered structures, swimming pools, aquariums, and special purpose rooms.", "keywords": ["special construction", "pre-engineered", "modular"]},
    {"csi_division": "14", "section_number": "14 00 00", "title": "Conveying Equipment",            "content_summary": "Elevators, escalators, moving walks, and conveying equipment.", "keywords": ["elevator", "escalator", "conveying", "lift"]},
    {"csi_division": "21", "section_number": "21 00 00", "title": "Fire Suppression",               "content_summary": "Fire suppression piping, sprinkler systems, and fire-extinguishing systems.", "keywords": ["fire suppression", "sprinkler", "fire protection"]},
    {"csi_division": "22", "section_number": "22 00 00", "title": "Plumbing",                       "content_summary": "Plumbing piping, plumbing equipment, plumbing fixtures, and domestic water supply.", "keywords": ["plumbing", "piping", "fixtures", "domestic water", "drain"]},
    {"csi_division": "23", "section_number": "23 00 00", "title": "HVAC",                           "content_summary": "Heating, ventilating, and air conditioning systems including ductwork, equipment, and controls.", "keywords": ["HVAC", "mechanical", "ductwork", "air handling", "chiller", "boiler"]},
    {"csi_division": "26", "section_number": "26 00 00", "title": "Electrical",                     "content_summary": "Medium and low voltage electrical distribution, lighting, and branch circuit wiring.", "keywords": ["electrical", "lighting", "wiring", "panel", "conduit", "power"]},
    {"csi_division": "27", "section_number": "27 00 00", "title": "Communications",                 "content_summary": "Structured cabling, data networks, audio-visual systems, and communications infrastructure.", "keywords": ["communications", "data", "network", "AV", "cabling", "low voltage"]},
    {"csi_division": "28", "section_number": "28 00 00", "title": "Electronic Safety and Security", "content_summary": "Access control, video surveillance, intrusion detection, and fire alarm systems.", "keywords": ["security", "access control", "cameras", "fire alarm", "intrusion"]},
]

AIA_CLAUSES = [
    {
        "clause_id": "AIA-A201-3.2",
        "standard": "AIA-A201-2017",
        "clause_number": "3.2",
        "title": "Review of Contract Documents and Field Conditions by Contractor",
        "text": (
            "The Contractor shall carefully study and compare the Contract Documents with each other "
            "and with information furnished by the Owner pursuant to Section 2.3.3 and shall at once "
            "report to the Architect errors, inconsistencies or omissions discovered. If the Contractor "
            "performs any construction activity knowing it involves a recognized error, inconsistency, "
            "or omission in the Contract Documents without such notice to the Architect, the Contractor "
            "shall assume appropriate responsibility for such performance and shall bear an appropriate "
            "amount of the attributable costs for correction."
        ),
    },
    {
        "clause_id": "AIA-A201-15.1",
        "standard": "AIA-A201-2017",
        "clause_number": "15.1",
        "title": "Claims",
        "text": (
            "A Claim is a demand or assertion by one of the parties seeking, as a matter of right, "
            "payment of money, a change in the Contract Time, or other relief with respect to the "
            "terms of the Contract. Claims must be initiated by written notice to the other party and "
            "to the Initial Decision Maker within 21 days after occurrence of the event giving rise to "
            "such Claim or within 21 days after the claimant first recognizes the condition giving rise "
            "to the Claim."
        ),
    },
    {
        "clause_id": "AIA-A201-9.3",
        "standard": "AIA-A201-2017",
        "clause_number": "9.3",
        "title": "Applications for Payment",
        "text": (
            "At least ten days before the date established for each progress payment, the Contractor "
            "shall submit to the Architect an itemized Application for Payment prepared in accordance "
            "with the schedule of values, if required under Section 9.2, for completed portions of the "
            "Work. The application shall be notarized, if required, and supported by all data "
            "substantiating the Contractor's right to payment that the Owner or Architect require."
        ),
    },
]

# ===========================================================================
# TIER 1 — Agent Playbooks
# ===========================================================================

AGENTS = [
    {"agent_id": "AGENT-DISPATCH-001", "name": "Dispatcher Agent", "version": "1.0.0", "phase": "phase-0"},
    {"agent_id": "AGENT-RFI-001",      "name": "RFI Agent",        "version": "1.0.0", "phase": "phase-0"},
]

DISPATCHER_RULES = [
    {"rule_id": "DISPATCH-RULE-001", "description": "Auto-route task when all four classification dimensions meet the confidence threshold", "condition": "All of project_id, phase, document_type, urgency classification confidence >= 0.80", "action": "Assign task to specialist agent per document type routing table", "confidence_threshold": 0.80, "priority": 1},
    {"rule_id": "DISPATCH-RULE-002", "description": "Escalate to human review when any classification dimension falls below threshold", "condition": "Any one of project_id, phase, document_type, or urgency confidence < 0.80", "action": "Set task status to ESCALATED_TO_HUMAN with best-guess classification and reasoning notes attached", "confidence_threshold": 0.80, "priority": 2},
    {"rule_id": "DISPATCH-RULE-003", "description": "Route RFI construction documents to AGENT-RFI-001 in Phase 0", "condition": "document_type=RFI AND phase=construction AND all dimensions confidence >= 0.80", "action": "Assign to AGENT-RFI-001", "confidence_threshold": 0.80, "priority": 3},
    {"rule_id": "DISPATCH-RULE-004", "description": "Escalate all non-RFI construction documents to human in Phase 0", "condition": "document_type NOT IN [RFI] AND phase=construction", "action": "Set task status to ESCALATED_TO_HUMAN; Phase 0 only handles RFI automatically", "confidence_threshold": 0.0, "priority": 4},
    {"rule_id": "DISPATCH-RULE-005", "description": "Escalate when project cannot be identified from email", "condition": "project_id classified as UNKNOWN (confidence=0.0)", "action": "Set task status to ESCALATED_TO_HUMAN; project not found in registry", "confidence_threshold": 0.0, "priority": 5},
]

RFI_RULES = [
    {"rule_id": "RFI-RULE-001", "description": "Extract structured RFI fields from email subject, body, and attachments", "condition": "Task assigned to AGENT-RFI-001 with status ASSIGNED_TO_AGENT", "action": "Run RFIExtractor on full email body (first 3000 chars) and attachment filenames", "confidence_threshold": 0.0, "priority": 1},
    {"rule_id": "RFI-RULE-002", "description": "Draft RFI response referencing applicable contract documents and spec sections", "condition": "RFI extraction complete and question field is non-empty", "action": "Run RFIDrafter using extracted question, spec section references, and KG SpecSection lookup", "confidence_threshold": 0.0, "priority": 2},
    {"rule_id": "RFI-RULE-003", "description": "Annotate draft when referenced spec section is not found in knowledge graph", "condition": "referenced_spec_sections contains a section number with no matching SpecSection node in KG", "action": "Include note in draft: 'Spec section X not found in KG -- CA staff should verify manually'", "confidence_threshold": 0.0, "priority": 3},
    {"rule_id": "RFI-RULE-004", "description": "Escalate if AI draft confidence is below threshold", "condition": "Draft response confidence score < 0.70 (e.g. question is ambiguous or references unknown drawings)", "action": "Attach low-confidence flag and escalation note; set task to ESCALATED_TO_HUMAN", "confidence_threshold": 0.70, "priority": 4},
]

DISPATCHER_ESCALATION = {
    "criteria_id": "DISPATCH-ESC-001",
    "trigger": "Any classification dimension confidence < 0.80 or project_id = UNKNOWN",
    "escalation_type": "human_queue",
}

RFI_ESCALATION = {
    "criteria_id": "RFI-ESC-001",
    "trigger": "Draft response confidence < 0.70 or question field empty after extraction",
    "escalation_type": "human_queue",
}

# ===========================================================================
# Seeding helpers
# ===========================================================================

_VALID_LABELS = frozenset({
    "Agent", "PlaybookRule", "EscalationCriteria", "DocumentType", "WorkflowStep",
    "SpecSection", "ContractClause", "Project", "CADocument", "Party", "CorrectionEvent",
})

def _merge_node(session, label: str, id_key: str, data: dict) -> None:
    if label not in _VALID_LABELS:
        raise ValueError(f"Invalid node label: {label!r}. Must be one of: {sorted(_VALID_LABELS)}")
    props_set = ", ".join(f"n.{k} = ${k}" for k in data if k != id_key)
    if props_set:
        cypher = f"MERGE (n:{label} {{{id_key}: ${id_key}}}) SET {props_set}"
    else:
        cypher = f"MERGE (n:{label} {{{id_key}: ${id_key}}})"
    session.run(cypher, **data)


def seed_tier2(driver: neo4j.Driver, embed: bool = True) -> dict:
    counts = {"document_types": 0, "workflow_steps": 0, "workflow_edges": 0}
    with driver.session() as session:
        for dt in DOCUMENT_TYPES:
            _merge_node(session, "DocumentType", "type_id", dt)
            counts["document_types"] += 1

        prev_step_id = None
        for step in RFI_WORKFLOW_STEPS:
            _merge_node(session, "WorkflowStep", "step_id", step)
            session.run(
                "MATCH (dt:DocumentType {type_id: 'RFI'}) "
                "MATCH (ws:WorkflowStep {step_id: $step_id}) "
                "MERGE (dt)-[:FOLLOWS_WORKFLOW]->(ws)",
                step_id=step["step_id"],
            )
            if prev_step_id:
                session.run(
                    "MATCH (a:WorkflowStep {step_id: $a}) "
                    "MATCH (b:WorkflowStep {step_id: $b}) "
                    "MERGE (a)-[:NEXT_STEP]->(b)",
                    a=prev_step_id, b=step["step_id"],
                )
                counts["workflow_edges"] += 1
            prev_step_id = step["step_id"]
            counts["workflow_steps"] += 1

        for dt in DOCUMENT_TYPES:
            if dt["type_id"] == "RFI":
                continue
            step_id = f"{dt['type_id']}-WF-01"
            step_data = {**OTHER_DOC_TYPE_STEP_TEMPLATE, "step_id": step_id}
            _merge_node(session, "WorkflowStep", "step_id", step_data)
            session.run(
                "MATCH (d:DocumentType {type_id: $type_id}) "
                "MATCH (ws:WorkflowStep {step_id: $step_id}) "
                "MERGE (d)-[:FOLLOWS_WORKFLOW]->(ws)",
                type_id=dt["type_id"], step_id=step_id,
            )
            counts["workflow_steps"] += 1

    return counts


def seed_tier4(driver: neo4j.Driver, embed: bool = True) -> dict:
    counts = {"spec_sections": 0, "contract_clauses": 0}
    with driver.session() as session:
        for div in CSI_DIVISIONS:
            data = {**div}
            if embed:
                text = f"{div['title']}: {div['content_summary']}"
                try:
                    emb = ai_engine.generate_embedding(text)
                    data["embedding"] = emb
                    data["embedding_model"] = "text-embedding"
                except Exception as e:
                    print(f"    ! Embedding failed for {div['section_number']}: {e}")
            _merge_node(session, "SpecSection", "section_number", data)
            counts["spec_sections"] += 1

        for clause in AIA_CLAUSES:
            data = {**clause}
            if embed:
                try:
                    emb = ai_engine.generate_embedding(f"{clause['title']}: {clause['text'][:500]}")
                    data["embedding"] = emb
                    data["embedding_model"] = "text-embedding"
                except Exception as e:
                    print(f"    ! Embedding failed for {clause['clause_id']}: {e}")
            _merge_node(session, "ContractClause", "clause_id", data)
            counts["contract_clauses"] += 1

    return counts


def seed_tier1(driver: neo4j.Driver, embed: bool = True) -> dict:
    counts = {"agents": 0, "rules": 0, "escalation_criteria": 0}
    with driver.session() as session:
        for agent in AGENTS:
            _merge_node(session, "Agent", "agent_id", agent)
            counts["agents"] += 1

        all_rules = [
            ("AGENT-DISPATCH-001", DISPATCHER_RULES),
            ("AGENT-RFI-001", RFI_RULES),
        ]
        for agent_id, rules in all_rules:
            for rule in rules:
                data = {**rule}
                if embed:
                    try:
                        emb = ai_engine.generate_embedding(rule["description"])
                        data["embedding"] = emb
                        data["embedding_model"] = "text-embedding"
                    except Exception as e:
                        print(f"    ! Embedding failed for {rule['rule_id']}: {e}")
                _merge_node(session, "PlaybookRule", "rule_id", data)
                session.run(
                    "MATCH (a:Agent {agent_id: $agent_id}) "
                    "MATCH (r:PlaybookRule {rule_id: $rule_id}) "
                    "MERGE (a)-[:HAS_RULE]->(r)",
                    agent_id=agent_id, rule_id=rule["rule_id"],
                )
                counts["rules"] += 1

        for esc in [DISPATCHER_ESCALATION, RFI_ESCALATION]:
            _merge_node(session, "EscalationCriteria", "criteria_id", esc)
            counts["escalation_criteria"] += 1
        session.run(
            "MATCH (a:Agent {agent_id: 'AGENT-DISPATCH-001'}) "
            "MATCH (e:EscalationCriteria {criteria_id: 'DISPATCH-ESC-001'}) "
            "MERGE (a)-[:ESCALATES_ON]->(e)"
        )
        session.run(
            "MATCH (a:Agent {agent_id: 'AGENT-RFI-001'}) "
            "MATCH (e:EscalationCriteria {criteria_id: 'RFI-ESC-001'}) "
            "MERGE (a)-[:ESCALATES_ON]->(e)"
        )

    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed KG baseline data.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--tier", choices=["1", "2", "4"], help="Seed only one tier")
    parser.add_argument("--no-embed", action="store_true", help="Skip embedding generation (faster, for testing)")
    args = parser.parse_args()

    embed = not args.no_embed

    if args.dry_run:
        print("=== DRY RUN ===")
        print(f"  Tier 2: {len(DOCUMENT_TYPES)} DocumentType + {len(RFI_WORKFLOW_STEPS) + len(DOCUMENT_TYPES) - 1} WorkflowStep nodes")
        print(f"  Tier 4: {len(CSI_DIVISIONS)} SpecSection + {len(AIA_CLAUSES)} ContractClause nodes")
        print(f"  Tier 1: {len(AGENTS)} Agent + {len(DISPATCHER_RULES) + len(RFI_RULES)} PlaybookRule + 2 EscalationCriteria nodes")
        return

    uri      = os.environ.get("NEO4J_URI")
    username = os.environ.get("NEO4J_USERNAME")
    password = os.environ.get("NEO4J_PASSWORD")

    if not all([uri, username, password]):
        print("ERROR: NEO4J_URI, NEO4J_USERNAME, and NEO4J_PASSWORD must be set.")
        sys.exit(1)

    driver = neo4j.GraphDatabase.driver(uri, auth=(username, password))
    try:
        if not args.tier or args.tier == "2":
            print("Seeding Tier 2 (Workflow Process)...")
            c = seed_tier2(driver, embed=embed)
            print(f"  v {c['document_types']} DocumentType, {c['workflow_steps']} WorkflowStep, {c['workflow_edges']} NEXT_STEP edges")

        if not args.tier or args.tier == "4":
            print("Seeding Tier 4 (Industry Knowledge)...")
            c = seed_tier4(driver, embed=embed)
            print(f"  v {c['spec_sections']} SpecSection, {c['contract_clauses']} ContractClause")

        if not args.tier or args.tier == "1":
            print("Seeding Tier 1 (Agent Playbooks)...")
            c = seed_tier1(driver, embed=embed)
            print(f"  v {c['agents']} Agent, {c['rules']} PlaybookRule, {c['escalation_criteria']} EscalationCriteria")

        print("\nDone. Verify at: https://console.neo4j.io")
    finally:
        driver.close()


if __name__ == "__main__":
    main()
