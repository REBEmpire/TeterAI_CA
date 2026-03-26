from typing import Optional, List
from pydantic import BaseModel


class RFIExtraction(BaseModel):
    rfi_number_submitted: str
    contractor_name: str
    contractor_contact: Optional[str] = None
    question: str
    referenced_spec_sections: List[str] = []
    referenced_drawing_sheets: List[str] = []
    date_submitted: Optional[str] = None
    response_requested_by: Optional[str] = None
    attachments_analyzed: List[str] = []
    raw_response: str  # original AI output for audit


class KGLookupResult(BaseModel):
    spec_sections: List[dict] = []
    playbook_rules: List[dict] = []
    workflow_steps: List[dict] = []
    contract_clause: Optional[dict] = None


class RFIResponse(BaseModel):
    header: str            # formatted header block
    response_text: str
    references: List[str]
    confidence_score: float  # 0.0–1.0
    review_flag: Optional[str] = None  # None | "REVIEW_CAREFULLY" | "ESCALATED"
    raw_response: str  # original AI output for audit
    # Red Team audit trail (populated by RFIDrafter when Red Team pass runs)
    initial_review: Optional[dict] = None
    red_team_critique: Optional[dict] = None
    final_output: Optional[dict] = None


class RFIProcessingResult(BaseModel):
    task_id: str
    extraction: Optional[RFIExtraction] = None
    draft: Optional[RFIResponse] = None
    final_status: str  # STAGED_FOR_REVIEW | ESCALATED_TO_HUMAN | ERROR


class RFIExtractionParseError(Exception):
    pass
