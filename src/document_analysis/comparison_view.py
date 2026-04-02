"""Comparison view formatting for multi-model document analysis.

Provides utilities to format side-by-side comparisons of model outputs
for both web UI display and markdown export.
"""
import json
from dataclasses import dataclass
from typing import List, Dict, Any, Optional

from .model_response import (
    MultiModelAnalysisResult,
    ModelAnalysisResponse,
    AnalysisStatus,
)


@dataclass
class ComparisonColumn:
    """A single column in the comparison view."""
    model_name: str
    provider: str
    tier: int
    status: str
    latency_ms: int
    tokens_used: int
    content: Optional[str]
    summary: Optional[str]
    key_findings: List[str]
    recommendations: List[str]
    confidence_score: Optional[float]
    error: Optional[str]


class ComparisonViewFormatter:
    """Formats multi-model analysis results for side-by-side comparison."""
    
    # Display names for each tier
    MODEL_DISPLAY_NAMES = {
        1: "Claude Opus 4.6",
        2: "Gemini 3.1 Pro",
        3: "Grok 4.2",
    }
    
    def __init__(self, result: MultiModelAnalysisResult):
        """Initialize with a multi-model analysis result."""
        self.result = result
        self._columns: List[ComparisonColumn] = []
        self._build_columns()
    
    def _build_columns(self) -> None:
        """Build comparison columns from the result."""
        responses = [
            (1, self.result.tier_1_response),
            (2, self.result.tier_2_response),
            (3, self.result.tier_3_response),
        ]
        
        for tier, resp in responses:
            if resp is None:
                col = ComparisonColumn(
                    model_name=self.MODEL_DISPLAY_NAMES[tier],
                    provider="",
                    tier=tier,
                    status="pending",
                    latency_ms=0,
                    tokens_used=0,
                    content=None,
                    summary=None,
                    key_findings=[],
                    recommendations=[],
                    confidence_score=None,
                    error=None,
                )
            else:
                col = ComparisonColumn(
                    model_name=self.MODEL_DISPLAY_NAMES[tier],
                    provider=resp.metadata.provider if resp.metadata else "",
                    tier=tier,
                    status=resp.status.value,
                    latency_ms=resp.metadata.latency_ms if resp.metadata else 0,
                    tokens_used=resp.metadata.total_tokens if resp.metadata else 0,
                    content=resp.content,
                    summary=resp.summary,
                    key_findings=resp.key_findings or [],
                    recommendations=resp.recommendations or [],
                    confidence_score=resp.confidence_score,
                    error=resp.error,
                )
            self._columns.append(col)
    
    def to_json(self) -> Dict[str, Any]:
        """Convert comparison view to JSON-serializable dictionary.
        
        Returns a structure optimized for web UI rendering.
        """
        return {
            "analysis_id": self.result.analysis_id,
            "document": {
                "id": self.result.document_id,
                "name": self.result.document_name,
                "type": self.result.document_type,
            },
            "timing": {
                "started_at": self.result.started_at.isoformat() if self.result.started_at else None,
                "completed_at": self.result.completed_at.isoformat() if self.result.completed_at else None,
                "total_latency_ms": self.result.total_latency_ms,
            },
            "summary": {
                "successful_models": self.result.successful_models,
                "failed_models": self.result.failed_models,
                "all_succeeded": self.result.all_models_succeeded,
            },
            "columns": [
                {
                    "tier": col.tier,
                    "model_name": col.model_name,
                    "provider": col.provider,
                    "status": col.status,
                    "latency_ms": col.latency_ms,
                    "tokens_used": col.tokens_used,
                    "content": col.content,
                    "summary": col.summary,
                    "key_findings": col.key_findings,
                    "recommendations": col.recommendations,
                    "confidence_score": col.confidence_score,
                    "error": col.error,
                }
                for col in self._columns
            ],
        }
    
    def to_markdown(self) -> str:
        """Convert comparison view to markdown format.
        
        Generates a formatted markdown document suitable for export or display.
        """
        lines = [
            f"# Multi-Model Document Analysis",
            f"",
            f"**Analysis ID:** {self.result.analysis_id}  ",
            f"**Document:** {self.result.document_name or 'Unknown'}  ",
            f"**Type:** {self.result.document_type or 'Unknown'}  ",
            f"**Total Time:** {self.result.total_latency_ms}ms  ",
            f"**Models Succeeded:** {self.result.successful_models}/3  ",
            f"",
            "---",
            f"",
        ]
        
        # Add each model's analysis as a section
        for col in self._columns:
            lines.extend(self._format_column_markdown(col))
            lines.append("")
            lines.append("---")
            lines.append("")
        
        # Add comparison summary
        lines.extend(self._format_comparison_summary())
        
        return "\n".join(lines)
    
    def _format_column_markdown(self, col: ComparisonColumn) -> List[str]:
        """Format a single column as markdown."""
        lines = [
            f"## {col.model_name} (Tier {col.tier})",
            f"",
            f"**Status:** {col.status}  ",
            f"**Latency:** {col.latency_ms}ms  ",
            f"**Tokens Used:** {col.tokens_used}  ",
        ]
        
        if col.confidence_score is not None:
            lines.append(f"**Confidence:** {col.confidence_score:.1%}  ")
        
        if col.error:
            lines.extend([
                f"",
                f"### ⚠️ Error",
                f"",
                f"```",
                col.error,
                f"```",
            ])
            return lines
        
        if col.summary:
            lines.extend([
                f"",
                f"### Summary",
                f"",
                col.summary,
            ])
        
        if col.key_findings:
            lines.extend([
                f"",
                f"### Key Findings",
                f"",
            ])
            for finding in col.key_findings:
                lines.append(f"- {finding}")
        
        if col.recommendations:
            lines.extend([
                f"",
                f"### Recommendations",
                f"",
            ])
            for rec in col.recommendations:
                lines.append(f"- {rec}")
        
        if col.content and not col.summary:
            # If no structured summary, show raw content
            lines.extend([
                f"",
                f"### Analysis",
                f"",
                col.content[:2000] + ("..." if len(col.content) > 2000 else ""),
            ])
        
        return lines
    
    def _format_comparison_summary(self) -> List[str]:
        """Generate a comparison summary across all models."""
        lines = [
            f"## Cross-Model Comparison",
            f"",
        ]
        
        # Find common themes across models
        all_findings = []
        all_recommendations = []
        
        for col in self._columns:
            if col.status == "success":
                all_findings.extend(col.key_findings)
                all_recommendations.extend(col.recommendations)
        
        if all_findings:
            # Count finding frequency
            finding_counts: Dict[str, int] = {}
            for f in all_findings:
                key = f.lower().strip()
                finding_counts[key] = finding_counts.get(key, 0) + 1
            
            # Findings mentioned by multiple models
            common_findings = [k for k, v in finding_counts.items() if v > 1]
            if common_findings:
                lines.extend([
                    f"### Consensus Findings (mentioned by multiple models)",
                    f"",
                ])
                for finding in common_findings[:5]:
                    lines.append(f"- {finding.capitalize()}")
                lines.append("")
        
        # Performance comparison table
        lines.extend([
            f"### Performance Comparison",
            f"",
            f"| Model | Status | Latency | Tokens | Confidence |",
            f"|-------|--------|---------|--------|------------|",
        ])
        
        for col in self._columns:
            conf_str = f"{col.confidence_score:.1%}" if col.confidence_score is not None else "N/A"
            lines.append(
                f"| {col.model_name} | {col.status} | {col.latency_ms}ms | {col.tokens_used} | {conf_str} |"
            )
        
        return lines
    
    def to_html_table(self) -> str:
        """Generate an HTML table for embedding in web views."""
        rows = []
        
        # Header row
        rows.append("<tr>")
        rows.append("<th></th>")  # Row label column
        for col in self._columns:
            status_class = "success" if col.status == "success" else "error"
            rows.append(f'<th class="model-header {status_class}">')
            rows.append(f'<div class="model-name">{col.model_name}</div>')
            rows.append(f'<div class="model-meta">{col.latency_ms}ms | {col.tokens_used} tokens</div>')
            rows.append("</th>")
        rows.append("</tr>")
        
        # Status row
        rows.append("<tr>")
        rows.append("<td><strong>Status</strong></td>")
        for col in self._columns:
            icon = "✅" if col.status == "success" else "❌"
            rows.append(f"<td>{icon} {col.status}</td>")
        rows.append("</tr>")
        
        # Summary row
        rows.append("<tr>")
        rows.append("<td><strong>Summary</strong></td>")
        for col in self._columns:
            summary = col.summary or col.error or "No analysis available"
            rows.append(f"<td>{summary[:500]}</td>")
        rows.append("</tr>")
        
        # Key findings row
        rows.append("<tr>")
        rows.append("<td><strong>Key Findings</strong></td>")
        for col in self._columns:
            if col.key_findings:
                findings_html = "<ul>" + "".join(f"<li>{f}</li>" for f in col.key_findings[:5]) + "</ul>"
            else:
                findings_html = "<em>None</em>"
            rows.append(f"<td>{findings_html}</td>")
        rows.append("</tr>")
        
        # Recommendations row
        rows.append("<tr>")
        rows.append("<td><strong>Recommendations</strong></td>")
        for col in self._columns:
            if col.recommendations:
                recs_html = "<ul>" + "".join(f"<li>{r}</li>" for r in col.recommendations[:5]) + "</ul>"
            else:
                recs_html = "<em>None</em>"
            rows.append(f"<td>{recs_html}</td>")
        rows.append("</tr>")
        
        rows_str = "\n".join(rows)
        return f'<table class="comparison-table">{rows_str}</table>'
