import logging

from .models import ClassificationResult, RoutingDecision, DocumentType, Phase

logger = logging.getLogger(__name__)

CONFIDENCE_THRESHOLD = 0.80

# Phase 0 routing table: (DocumentType, Phase) → agent_id
PHASE_0_ROUTING: dict[tuple, str] = {
    (DocumentType.RFI, Phase.CONSTRUCTION): "AGENT-RFI-001",
    (DocumentType.SUBMITTAL, Phase.CONSTRUCTION): "AGENT-SUBMITTAL-001",
    (DocumentType.COST_ANALYSIS, Phase.CONSTRUCTION): "AGENT-COST-001",
    (DocumentType.PAY_APP_REVIEW, Phase.CONSTRUCTION): "AGENT-PAYAPP-001",
    (DocumentType.SCHEDULE_REVIEW, Phase.CONSTRUCTION): "AGENT-SCHEDULE-001",
}


class DispatcherRouter:
    def route(self, result: ClassificationResult) -> RoutingDecision:
        # UNKNOWN project_id always escalates — cannot route without a known project
        if result.project_id.value == "UNKNOWN":
            return RoutingDecision(
                action="ESCALATE_TO_HUMAN",
                assigned_agent=None,
                reason="project_id is UNKNOWN — cannot route without a known project",
                all_confident=False,
            )

        dims = {
            "project_id": result.project_id,
            "phase": result.phase,
            "document_type": result.document_type,
            "urgency": result.urgency,
        }

        low_dims = [name for name, dim in dims.items() if dim.confidence < CONFIDENCE_THRESHOLD]
        all_confident = len(low_dims) == 0

        if not all_confident:
            return RoutingDecision(
                action="ESCALATE_TO_HUMAN",
                assigned_agent=None,
                reason=f"Confidence below {CONFIDENCE_THRESHOLD} on: {', '.join(low_dims)}",
                all_confident=False,
            )

        # All dimensions confident — look up routing table
        try:
            doc_type = DocumentType(result.document_type.value)
            phase = Phase(result.phase.value)
        except ValueError:
            return RoutingDecision(
                action="ESCALATE_TO_HUMAN",
                assigned_agent=None,
                reason=(
                    f"Unrecognised document_type '{result.document_type.value}' "
                    f"or phase '{result.phase.value}'"
                ),
                all_confident=True,
            )

        agent = PHASE_0_ROUTING.get((doc_type, phase))
        if agent:
            return RoutingDecision(
                action="ASSIGN_TO_AGENT",
                assigned_agent=agent,
                reason=(
                    f"High-confidence {doc_type.value} in {phase.value} phase — routed to {agent}"
                ),
                all_confident=True,
            )

        return RoutingDecision(
            action="ESCALATE_TO_HUMAN",
            assigned_agent=None,
            reason=f"No Phase 0 agent configured for {doc_type.value}/{phase.value}",
            all_confident=True,
        )
