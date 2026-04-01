# src/knowledge_graph/models.py
"""
Python dataclasses for all Knowledge Graph node types.

These mirror the Neo4j node labels and properties used throughout
KnowledgeGraphClient, seed scripts, and ingestion pipelines.

Tier 1 — Agent Playbooks:   Agent, PlaybookRule, EscalationCriteria
Tier 2 — Workflow Process:  DocumentType, WorkflowStep
Tier 3 — Project Layer:     Project, CADocument, Party, RFI, CorrectionEvent
Tier 4 — Industry Knowledge: SpecSection, ContractClause
Analysis Layer:              DesignFlaw, CorrectiveAction
Document Processing:         Submittal, ScheduleReview, PayApp, CostAnalysis
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Tier 1 — Agent Playbooks
# ---------------------------------------------------------------------------

@dataclass
class Agent:
    """An AI agent registered in the system (e.g. Dispatcher, RFI Agent)."""
    agent_id: str
    name: str
    version: str = "1.0.0"
    phase: str = "phase-0"


@dataclass
class PlaybookRule:
    """A decision rule attached to an Agent via [:HAS_RULE]."""
    rule_id: str
    description: str
    condition: str = ""
    action: str = ""
    confidence_threshold: float = 0.0
    priority: int = 1
    embedding: list[float] = field(default_factory=list)
    embedding_model: str = ""


@dataclass
class EscalationCriteria:
    """Trigger conditions for escalating to human review."""
    criteria_id: str
    trigger: str
    escalation_type: str = "human_queue"


# ---------------------------------------------------------------------------
# Tier 2 — Workflow Process
# ---------------------------------------------------------------------------

@dataclass
class DocumentType:
    """A CA document category with workflow and deadline metadata."""
    type_id: str
    name: str
    phase: str = "construction"
    numbering_prefix: str = ""
    response_deadline_days: int = 0


@dataclass
class WorkflowStep:
    """A single step in a document-type workflow chain."""
    step_id: str
    name: str
    description: str = ""
    responsible_party: str = "ca_staff"
    sequence: int = 1


# ---------------------------------------------------------------------------
# Tier 3 — Project Document Layer
# ---------------------------------------------------------------------------

@dataclass
class Project:
    """A construction project tracked in the system."""
    project_id: str
    project_number: str = ""
    name: str = ""
    phase: str = "construction"
    drive_root_folder_id: str = ""


@dataclass
class CADocument:
    """A construction administration document ingested from Google Drive."""
    doc_id: str
    drive_file_id: str
    filename: str = ""
    drive_folder_path: str = ""
    doc_type: str = ""
    doc_number: Optional[str] = None
    phase: str = ""
    date_submitted: Optional[str] = None
    date_responded: Optional[str] = None
    summary: str = ""
    embedding: list[float] = field(default_factory=list)
    embedding_model: str = ""
    metadata_only: bool = False


@dataclass
class Party:
    """A project participant (contractor, owner, consultant)."""
    party_id: str
    name: str
    type: str = "contractor"


@dataclass
class RFI:
    """A Request for Information extracted and processed by the RFI Agent."""
    rfi_id: str
    project_id: str = ""
    rfi_number: Optional[str] = None
    contractor_name: Optional[str] = None
    question: str = ""
    response_text: str = ""
    status: str = ""
    date_submitted: Optional[str] = None
    referenced_spec_sections: Optional[list[str]] = None
    source_file_name: str = ""
    embedding: list[float] = field(default_factory=list)
    embedding_model: str = ""


@dataclass
class CorrectionEvent:
    """A human correction of an AI-generated output, used for learning."""
    event_id: str
    agent_id: str = ""
    task_id: str = ""
    original_text: str = ""
    corrected_text: str = ""
    correction_type: str = ""
    reviewed_by: str = ""


# ---------------------------------------------------------------------------
# Tier 4 — Industry Knowledge
# ---------------------------------------------------------------------------

@dataclass
class SpecSection:
    """A CSI MasterFormat specification section."""
    section_number: str
    title: str = ""
    csi_division: str = ""
    content_summary: str = ""
    keywords: list[str] = field(default_factory=list)
    project_id: Optional[str] = None
    embedding: list[float] = field(default_factory=list)
    embedding_model: str = ""


@dataclass
class DrawingSheet:
    """A drawing sheet from a project's drawing set."""
    sheet_number: str
    project_id: str = ""
    title: str = ""
    discipline: str = ""
    source_doc_id: str = ""
    content_summary: str = ""
    chunk_id: str = ""
    embedding: list[float] = field(default_factory=list)
    embedding_model: str = ""


@dataclass
class ContractClause:
    """An AIA contract clause (e.g. A201 sections)."""
    clause_id: str
    standard: str = ""
    clause_number: str = ""
    title: str = ""
    text: str = ""
    embedding: list[float] = field(default_factory=list)
    embedding_model: str = ""


# ---------------------------------------------------------------------------
# Analysis Layer (RFI pattern analysis)
# ---------------------------------------------------------------------------

@dataclass
class DesignFlaw:
    """A design flaw pattern identified from RFI analysis."""
    flaw_id: str
    project_id: str = ""
    category: str = ""
    description: str = ""


@dataclass
class CorrectiveAction:
    """A recommended corrective action linked to a DesignFlaw."""
    action_id: str
    project_id: str = ""
    action: str = ""


# ---------------------------------------------------------------------------
# Document Processing Nodes (agent outputs)
# ---------------------------------------------------------------------------

@dataclass
class Submittal:
    """A submittal review processed by the Submittal Agent."""
    task_id: str
    project_id: str = ""
    doc_number: Optional[str] = None
    status_outcome: str = ""
    key_finding: str = ""


@dataclass
class ScheduleReview:
    """A schedule review processed by the Schedule Agent."""
    task_id: str
    project_id: str = ""
    status_outcome: str = ""
    key_finding: str = ""


@dataclass
class PayApp:
    """A pay application review."""
    task_id: str
    project_id: str = ""
    app_number: Optional[str] = None
    status_outcome: str = ""
    key_finding: str = ""


@dataclass
class CostAnalysis:
    """A cost/change order analysis."""
    task_id: str
    project_id: str = ""
    change_order_num: Optional[str] = None
    status_outcome: str = ""
    key_finding: str = ""


# ---------------------------------------------------------------------------
# Mapping: dataclass → (Neo4j label, ID property)
# ---------------------------------------------------------------------------

NODE_REGISTRY: dict[type, tuple[str, str]] = {
    Agent:              ("Agent",              "agent_id"),
    PlaybookRule:       ("PlaybookRule",        "rule_id"),
    EscalationCriteria: ("EscalationCriteria",  "criteria_id"),
    DocumentType:       ("DocumentType",        "type_id"),
    WorkflowStep:       ("WorkflowStep",        "step_id"),
    Project:            ("Project",             "project_id"),
    CADocument:         ("CADocument",          "drive_file_id"),
    Party:              ("Party",               "party_id"),
    RFI:                ("RFI",                 "rfi_id"),
    CorrectionEvent:    ("CorrectionEvent",     "event_id"),
    SpecSection:        ("SpecSection",         "section_number"),
    DrawingSheet:       ("DrawingSheet",        "sheet_number"),
    ContractClause:     ("ContractClause",      "clause_id"),
    DesignFlaw:         ("DESIGN_FLAW",         "flaw_id"),
    CorrectiveAction:   ("CORRECTIVE_ACTION",   "action_id"),
    Submittal:          ("Submittal",           "task_id"),
    ScheduleReview:     ("ScheduleReview",      "task_id"),
    PayApp:             ("PayApp",              "task_id"),
    CostAnalysis:       ("CostAnalysis",        "task_id"),
}
