"""Document Analysis Module — Multi-model document analysis service.

This module provides the DocumentAnalysisService which orchestrates
parallel analysis of documents across multiple AI models (Claude Opus 4.6,
Gemini 3.1 Pro, Grok 4.2) and provides comparison views.
"""
from .document_analysis_service import DocumentAnalysisService
from .model_response import (
    ModelAnalysisResponse,
    MultiModelAnalysisResult,
    AnalysisMetadata,
)
from .comparison_view import ComparisonViewFormatter

__all__ = [
    "DocumentAnalysisService",
    "ModelAnalysisResponse",
    "MultiModelAnalysisResult",
    "AnalysisMetadata",
    "ComparisonViewFormatter",
]
