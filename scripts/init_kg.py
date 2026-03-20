import os
import sys
import logging
from neo4j import GraphDatabase

# Add src to Python path so we can import from src
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from src.ai_engine.engine import engine
from src.ai_engine.gcp import gcp_integration

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def init_kg():
    logger.info("Starting Knowledge Graph initialization...")

    # Load secrets first
    gcp_integration.load_secrets_to_env()

    uri = os.environ.get("NEO4J_URI")
    user = os.environ.get("NEO4J_USERNAME")
    password = os.environ.get("NEO4J_PASSWORD")

    if not uri or not user or not password:
        logger.error("Neo4j credentials not found in environment variables. Initialization aborted.")
        return

    driver = GraphDatabase.driver(uri, auth=(user, password))

    with driver.session() as session:
        # 1. Create Constraints
        logger.info("Creating constraints...")
        session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (a:Agent) REQUIRE a.agent_id IS UNIQUE")
        session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (d:DocumentType) REQUIRE d.type_id IS UNIQUE")
        session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (s:SpecSection) REQUIRE s.section_number IS UNIQUE")
        session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (c:ContractClause) REQUIRE c.clause_id IS UNIQUE")
        session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (p:PlaybookRule) REQUIRE p.rule_id IS UNIQUE")

        # 2. Create Vector Indexes
        # Assuming 768 dimensions for vertex_ai/text-embedding-004
        logger.info("Creating vector indexes (768 dimensions for Gemini)...")
        # SpecSection Index
        session.run("""
        CREATE VECTOR INDEX spec_section_embeddings IF NOT EXISTS
        FOR (n:SpecSection) ON (n.embedding)
        OPTIONS {indexConfig: {
            `vector.dimensions`: 768,
            `vector.similarity_function`: 'cosine'
        }}
        """)
        # ContractClause Index
        session.run("""
        CREATE VECTOR INDEX contract_clause_embeddings IF NOT EXISTS
        FOR (n:ContractClause) ON (n.embedding)
        OPTIONS {indexConfig: {
            `vector.dimensions`: 768,
            `vector.similarity_function`: 'cosine'
        }}
        """)
        # PlaybookRule Index
        session.run("""
        CREATE VECTOR INDEX playbook_rule_embeddings IF NOT EXISTS
        FOR (n:PlaybookRule) ON (n.embedding)
        OPTIONS {indexConfig: {
            `vector.dimensions`: 768,
            `vector.similarity_function`: 'cosine'
        }}
        """)

        # Wait for indexes to come online
        logger.info("Waiting for indexes to become online...")
        session.run("CALL db.awaitIndexes(300)")

        # 3. Load Seed Data: Tier 2 (Workflow Process)
        logger.info("Loading Tier 2 Seed Data...")

        # Document Types
        session.run("""
        MERGE (rfi:DocumentType {type_id: "RFI"})
        SET rfi.name = "Request For Information",
            rfi.phase = "construction",
            rfi.numbering_prefix = "RFI-",
            rfi.response_deadline_days = 10

        MERGE (sub:DocumentType {type_id: "SUBMITTAL"})
        SET sub.name = "Submittal",
            sub.phase = "construction",
            sub.numbering_prefix = "SUB-",
            sub.response_deadline_days = 14

        MERGE (co:DocumentType {type_id: "CHANGE_ORDER"})
        SET co.name = "Change Order",
            co.phase = "construction",
            co.numbering_prefix = "CO-",
            co.response_deadline_days = 7
        """)

        # RFI Workflow Steps
        session.run("""
        MATCH (rfi:DocumentType {type_id: "RFI"})

        MERGE (s1:WorkflowStep {step_id: "RFI-01"})
        SET s1.name = "Receive and Log", s1.description = "Receive RFI and log into system.", s1.responsible_party = "ca_agent", s1.sequence = 1

        MERGE (s2:WorkflowStep {step_id: "RFI-02"})
        SET s2.name = "Initial Review", s2.description = "Agent reviews for completeness and context.", s2.responsible_party = "ca_agent", s2.sequence = 2

        MERGE (s3:WorkflowStep {step_id: "RFI-03"})
        SET s3.name = "Draft Response", s3.description = "Agent drafts proposed response based on contract/specs.", s3.responsible_party = "ca_agent", s3.sequence = 3

        MERGE (s4:WorkflowStep {step_id: "RFI-04"})
        SET s4.name = "Human Review", s4.description = "CA staff reviews and approves draft response.", s4.responsible_party = "ca_staff", s4.sequence = 4

        MERGE (rfi)-[:FOLLOWS_WORKFLOW]->(s1)
        MERGE (s1)-[:NEXT_STEP]->(s2)
        MERGE (s2)-[:NEXT_STEP]->(s3)
        MERGE (s3)-[:NEXT_STEP]->(s4)
        """)

        # 4. Load Seed Data: Tier 4 (Industry Knowledge)
        logger.info("Loading Tier 4 Seed Data and generating embeddings...")

        # AIA A201 Contract Clauses
        clauses = [
            {
                "clause_id": "AIA-A201-3.2",
                "standard": "AIA-A201",
                "clause_number": "3.2",
                "title": "Review of Contract Documents and Field Conditions by Contractor",
                "text": "Execution of the Contract by the Contractor is a representation that the Contractor has visited the site, become generally familiar with local conditions under which the Work is to be performed, and correlated personal observations with requirements of the Contract Documents."
            },
            {
                "clause_id": "AIA-A201-4.3",
                "standard": "AIA-A201",
                "clause_number": "4.3",
                "title": "Claims and Disputes",
                "text": "Pending final resolution of a Claim, except as otherwise agreed in writing or as provided in Section 9.7 and Article 14, the Contractor shall proceed diligently with performance of the Contract and the Owner shall continue to make payments in accordance with the Contract Documents."
            }
        ]

        for c in clauses:
            try:
                emb = engine.generate_embedding(c["text"])
                session.run("""
                MERGE (cc:ContractClause {clause_id: $id})
                SET cc.standard = $standard,
                    cc.clause_number = $num,
                    cc.title = $title,
                    cc.text = $text,
                    cc.embedding = $emb,
                    cc.embedding_model = 'vertex_ai/text-embedding-004',
                    cc.embedding_updated_at = datetime()
                """, id=c["clause_id"], standard=c["standard"], num=c["clause_number"],
                     title=c["title"], text=c["text"], emb=emb)
            except Exception as e:
                logger.error(f"Failed to process ContractClause {c['clause_id']}: {e}")

        # Spec Sections
        specs = [
            {
                "csi": "01", "num": "01 00 00", "title": "General Requirements",
                "content": "General administrative and procedural requirements for the project including project meetings, submittals, quality control, temporary facilities, and closeout procedures."
            },
            {
                "csi": "03", "num": "03 30 00", "title": "Cast-in-Place Concrete",
                "content": "This section covers all cast-in-place concrete work, including formwork, reinforcement, concrete mixture proportions, and placement procedures. Slump requirements must be strictly adhered to per ACI 318."
            },
            {
                "csi": "05", "num": "05 12 00", "title": "Structural Steel Framing",
                "content": "Requirements for structural steel framing including material specifications (ASTM A992), connection design, fabrication, and erection tolerances per AISC standards."
            },
            {
                "csi": "07", "num": "07 92 00", "title": "Joint Sealants",
                "content": "Requirements for joint sealants including materials, preparation, application, and curing. Sealants must be compatible with adjacent materials and meet specified movement capabilities."
            },
            {
                "csi": "08", "num": "08 11 13", "title": "Hollow Metal Doors and Frames",
                "content": "Requirements for hollow metal doors and frames including material gauge, hardware preparation, fire ratings, and installation tolerances per SDI standards."
            },
            {
                "csi": "09", "num": "09 29 00", "title": "Gypsum Board",
                "content": "Requirements for gypsum board assemblies including type, thickness, fire-resistance ratings, fastening patterns, and finishing levels per GA-216."
            },
            {
                "csi": "23", "num": "23 00 00", "title": "Heating, Ventilating, and Air-Conditioning (HVAC)",
                "content": "General requirements for HVAC systems including ductwork, piping, equipment, and controls. All equipment must meet specified efficiency ratings per ASHRAE 90.1."
            },
            {
                "csi": "26", "num": "26 05 00", "title": "Common Work Results for Electrical",
                "content": "General requirements for electrical work including conduit, wire, boxes, panels, and connections. All work must comply with NEC and local electrical code requirements."
            },
        ]

        for s in specs:
            try:
                emb = engine.generate_embedding(s["content"])
                session.run("""
                MERGE (ss:SpecSection {section_number: $num})
                SET ss.csi_division = $csi,
                    ss.title = $title,
                    ss.content_summary = $content,
                    ss.embedding = $emb,
                    ss.embedding_model = 'vertex_ai/text-embedding-004',
                    ss.embedding_updated_at = datetime()
                """, num=s["num"], csi=s["csi"], title=s["title"], content=s["content"], emb=emb)
            except Exception as e:
                logger.error(f"Failed to process SpecSection {s['num']}: {e}")

        # 5. Load Seed Data: Tier 1 (Agent Playbooks)
        logger.info("Loading Tier 1 Seed Data and generating embeddings...")

        rules = [
            {
                "agent_id": "AGENT-DISPATCH-001",
                "rule_id": "DISP-RULE-01",
                "desc": "Identify RFI emails",
                "cond": "Email subject contains 'RFI' or 'Request for Information'",
                "act": "Classify as RFI and route to AGENT-RFI-001",
                "conf": 0.85,
                "prio": 1,
                "text_for_embedding": "Identify RFI emails. If email subject contains 'RFI' or 'Request for Information', classify as RFI and route to AGENT-RFI-001."
            },
            {
                "agent_id": "AGENT-DISPATCH-001",
                "rule_id": "DISP-RULE-02",
                "desc": "Identify Submittal emails",
                "cond": "Email subject contains 'SUBMITTAL' or 'Shop Drawing'",
                "act": "Classify as SUBMITTAL and escalate to human review (Phase 0)",
                "conf": 0.85,
                "prio": 2,
                "text_for_embedding": "Identify Submittal emails. If email subject contains SUBMITTAL or Shop Drawing, classify as SUBMITTAL and escalate to human review."
            },
            {
                "agent_id": "AGENT-RFI-001",
                "rule_id": "RFI-RULE-01",
                "desc": "Missing Attachment",
                "cond": "RFI body references an attachment but none is attached",
                "act": "Draft a reply requesting the missing attachment. Set confidence 0.40 to trigger escalation.",
                "conf": 0.90,
                "prio": 1,
                "text_for_embedding": "Missing Attachment rule. If RFI body references an attachment but none is attached, draft a reply asking for the missing attachment and escalate to human review."
            },
            {
                "agent_id": "AGENT-RFI-001",
                "rule_id": "RFI-RULE-02",
                "desc": "Standard spec-backed RFI response",
                "cond": "RFI question can be answered by referencing contract documents or spec sections",
                "act": "Draft a response citing the relevant spec section or drawing. Target confidence >= 0.75.",
                "conf": 0.75,
                "prio": 2,
                "text_for_embedding": "Standard spec-backed RFI response. Draft a response citing the relevant spec section or drawing reference for questions answerable from contract documents."
            },
            {
                "agent_id": "AGENT-RFI-001",
                "rule_id": "RFI-RULE-03",
                "desc": "Design intent question requiring architect judgment",
                "cond": "RFI asks about design intent, aesthetics, or requires professional judgment beyond documented specs",
                "act": "Draft preliminary framing of the question and flag for CA staff review. Set confidence 0.55.",
                "conf": 0.55,
                "prio": 3,
                "text_for_embedding": "Design intent question requiring architect judgment. RFI asks about design intent, aesthetics, or requires professional judgment beyond documented specs. Flag for CA staff review."
            },
            {
                "agent_id": "AGENT-RFI-001",
                "rule_id": "RFI-RULE-04",
                "desc": "RFI references drawing sheet for clarification",
                "cond": "RFI references a specific drawing sheet number (e.g. A-101, S-201)",
                "act": "Include the referenced drawing sheet in the response context. Note the sheet reference in the draft header.",
                "conf": 0.80,
                "prio": 4,
                "text_for_embedding": "RFI references drawing sheet. When RFI references specific drawing sheet numbers like A-101 or S-201, include the referenced drawing sheet in response context."
            },
            {
                "agent_id": "AGENT-RFI-001",
                "rule_id": "RFI-RULE-05",
                "desc": "Duplicate RFI detection",
                "cond": "RFI question appears substantially similar to a previously answered RFI in the log",
                "act": "Draft response referencing the prior RFI number and answer. Set confidence 0.85.",
                "conf": 0.85,
                "prio": 5,
                "text_for_embedding": "Duplicate RFI detection. If RFI question appears substantially similar to a previously answered RFI in the log, reference the prior RFI number and answer in the response."
            },
        ]

        for r in rules:
            try:
                emb = engine.generate_embedding(r["text_for_embedding"])

                # Create Agent if not exists
                session.run("""
                MERGE (a:Agent {agent_id: $agent_id})
                SET a.name = "Agent " + $agent_id,
                    a.version = "1.0",
                    a.phase = "phase-0"
                """, agent_id=r["agent_id"])

                # Create Rule and relationship
                session.run("""
                MATCH (a:Agent {agent_id: $agent_id})
                MERGE (pr:PlaybookRule {rule_id: $rule_id})
                SET pr.description = $desc,
                    pr.condition = $cond,
                    pr.action = $act,
                    pr.confidence_threshold = $conf,
                    pr.priority = $prio,
                    pr.embedding = $emb,
                    pr.embedding_model = 'vertex_ai/text-embedding-004',
                    pr.embedding_updated_at = datetime()
                MERGE (a)-[:HAS_RULE]->(pr)
                """, agent_id=r["agent_id"], rule_id=r["rule_id"], desc=r["desc"], cond=r["cond"],
                     act=r["act"], conf=r["conf"], prio=r["prio"], emb=emb)
            except Exception as e:
                logger.error(f"Failed to process PlaybookRule {r['rule_id']}: {e}")

        # 6. Verify seed counts
        logger.info("Verifying seed data...")
        counts = {
            "Agent": session.run("MATCH (n:Agent) RETURN count(n) AS c").single()["c"],
            "PlaybookRule": session.run("MATCH (n:PlaybookRule) RETURN count(n) AS c").single()["c"],
            "DocumentType": session.run("MATCH (n:DocumentType) RETURN count(n) AS c").single()["c"],
            "WorkflowStep": session.run("MATCH (n:WorkflowStep) RETURN count(n) AS c").single()["c"],
            "SpecSection": session.run("MATCH (n:SpecSection) RETURN count(n) AS c").single()["c"],
            "ContractClause": session.run("MATCH (n:ContractClause) RETURN count(n) AS c").single()["c"],
        }
        for label, count in counts.items():
            logger.info(f"  {label}: {count} nodes")

    driver.close()
    logger.info("Knowledge Graph initialization complete.")
    return counts

if __name__ == "__main__":
    init_kg()
