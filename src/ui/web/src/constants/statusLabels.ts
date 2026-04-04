export const STATUS_LABELS: Record<string, string> = {
  PENDING_CLASSIFICATION: "Waiting to process",
  CLASSIFYING: "Analyzing document...",
  ASSIGNED_TO_AGENT: "AI reviewing",
  PROCESSING: "AI reviewing",
  STAGED_FOR_REVIEW: "Ready for your review",
  ESCALATED_TO_HUMAN: "Needs attention",
  APPROVED: "Approved",
  REJECTED: "Returned for revision",
  DELIVERED: "Complete",
  ERROR: "Processing failed"
};

export const STATUS_COLORS: Record<string, string> = {
  PENDING_CLASSIFICATION: "bg-gray-100 text-gray-600 border-gray-200",
  CLASSIFYING: "bg-blue-50 text-blue-600 border-blue-200",
  ASSIGNED_TO_AGENT: "bg-blue-100 text-blue-700 border-blue-300 animate-pulse",
  PROCESSING: "bg-blue-100 text-blue-700 border-blue-300 animate-pulse",
  STAGED_FOR_REVIEW: "bg-green-100 text-green-700 border-green-300",
  ESCALATED_TO_HUMAN: "bg-orange-100 text-orange-700 border-orange-300",
  APPROVED: "bg-emerald-50 text-emerald-600 border-emerald-200",
  REJECTED: "bg-red-50 text-red-600 border-red-200",
  DELIVERED: "bg-gray-50 text-gray-500 border-gray-200",
  ERROR: "bg-red-100 text-red-800 border-red-300"
};

export const DOC_TYPE_LABELS: Record<string, string> = {
  RFI: "Request for Information",
  SUBMITTAL: "Submittal",
  COST_ANALYSIS: "Cost Analysis / PCO",
  PAY_APP_REVIEW: "Pay Application",
  SCHEDULE_REVIEW: "Schedule Review",
  CHANGE_ORDER: "Change Order",
  UNKNOWN: "Unclassified"
};
