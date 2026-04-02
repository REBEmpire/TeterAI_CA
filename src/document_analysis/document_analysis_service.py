"""Document Analysis Service — Multi-model document analysis orchestrator.

This service:
1. Accepts documents (PDF, Word, Excel, etc.) for analysis
2. Uses the document_intelligence pipeline to extract content
3. Sends extracted content to all three models in parallel
4. Returns structured responses from all models with metadata
5. Provides comparison views for side-by-side analysis

Architecture
------------
The service extends the existing AIEngine.generate_all_models() capability
with document-specific preprocessing and structured output parsing.

Usage
-----
    from document_analysis import DocumentAnalysisService
    
    service = DocumentAnalysisService()
    result = await service.analyze_document(
        file_path="/path/to/document.pdf",
        analysis_prompt="Analyze this construction specification...",
    )
    
    # Get side-by-side comparison
    comparison = service.get_comparison_view(result)
"""
import asyncio
import json
import logging
import os
import re
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any, List, Callable

from ai_engine.engine import engine as ai_engine
from ai_engine.models import (
    AIRequest,
    AIResponse,
    CapabilityClass,
)

from .model_response import (
    AnalysisMetadata,
    AnalysisStatus,
    ModelAnalysisResponse,
    MultiModelAnalysisResult,
)
from .comparison_view import ComparisonViewFormatter

logger = logging.getLogger(__name__)

# Default analysis prompt template
_DEFAULT_ANALYSIS_PROMPT = """Analyze the following document content and provide:

1. **Executive Summary**: A 2-3 sentence overview of the document's purpose and main content.

2. **Key Findings**: List 3-5 important points, observations, or issues identified in the document.

3. **Recommendations**: List any recommendations or action items based on the analysis.

4. **Confidence Score**: Rate your confidence in this analysis from 0.0 to 1.0.

Please structure your response in the following JSON format:
```json
{
    "summary": "...",
    "key_findings": ["...", "..."],
    "recommendations": ["...", "..."],
    "confidence_score": 0.85
}
```

Document Content:
---
{content}
---
"""

_CONSTRUCTION_ANALYSIS_PROMPT = """You are an expert construction document analyst. Analyze the following construction document and provide:

1. **Executive Summary**: Overview of the document's scope, purpose, and key specifications.

2. **Key Findings**: Identify 3-5 critical items including:
   - Specification requirements
   - Material requirements
   - Installation procedures
   - Testing/inspection requirements
   - Compliance considerations

3. **Recommendations**: Action items for:
   - Submittal requirements
   - Quality control points
   - Potential coordination issues
   - Items requiring clarification

4. **Confidence Score**: Rate your confidence in this analysis (0.0 to 1.0).

Structure your response as JSON:
```json
{
    "summary": "...",
    "key_findings": ["...", "..."],
    "recommendations": ["...", "..."],
    "confidence_score": 0.85
}
```

Document Content:
---
{content}
---
"""


class DocumentAnalysisService:
    """Orchestrates multi-model document analysis.
    
    This service coordinates parallel analysis of documents across multiple
    AI models and aggregates their responses for comparison.
    """
    
    def __init__(
        self,
        ai_engine_instance=None,
        document_intelligence_service=None,
        max_content_length: int = 100000,
    ):
        """Initialize the document analysis service.
        
        Args:
            ai_engine_instance: AIEngine instance (uses global engine if None)
            document_intelligence_service: DocumentIntelligenceService for extraction
            max_content_length: Maximum document content length to send to models
        """
        self._engine = ai_engine_instance or ai_engine
        self._doc_intelligence = document_intelligence_service
        self._max_content_length = max_content_length
        
        # Try to import document intelligence service if not provided
        if self._doc_intelligence is None:
            try:
                from document_intelligence.extractors.pdf_extractor import PdfExtractor
                self._pdf_extractor = PdfExtractor()
            except ImportError:
                self._pdf_extractor = None
                logger.warning("PDF extractor not available")
    
    def analyze_document(
        self,
        file_path: Optional[str] = None,
        content: Optional[str] = None,
        document_name: Optional[str] = None,
        document_type: Optional[str] = None,
        analysis_prompt: Optional[str] = None,
        system_prompt: Optional[str] = None,
        task_id: Optional[str] = None,
        calling_agent: str = "document_analysis_service",
        use_construction_prompt: bool = False,
    ) -> MultiModelAnalysisResult:
        """Analyze a document using all three AI models in parallel.
        
        Args:
            file_path: Path to the document file (PDF, Word, etc.)
            content: Pre-extracted document content (alternative to file_path)
            document_name: Display name for the document
            document_type: Document type (e.g., "PDF", "DOCX")
            analysis_prompt: Custom analysis prompt template (use {content} placeholder)
            system_prompt: Custom system prompt
            task_id: Task ID for tracking
            calling_agent: Agent identifier for audit logging
            use_construction_prompt: Use construction-specific analysis prompt
            
        Returns:
            MultiModelAnalysisResult with responses from all three models
        """
        start_time = time.time()
        task_id = task_id or str(uuid.uuid4())
        
        # Initialize result
        result = MultiModelAnalysisResult(
            document_id=task_id,
            document_name=document_name or (Path(file_path).name if file_path else "Unknown"),
            document_type=document_type or self._detect_document_type(file_path),
            started_at=datetime.now(timezone.utc),
        )
        
        # Extract content if file path provided
        if content is None and file_path:
            content = self._extract_content(file_path)
            if content is None:
                # Return result with all failures
                error_msg = f"Failed to extract content from {file_path}"
                result.tier_1_response = ModelAnalysisResponse.from_error(error_msg, "anthropic", "claude-opus-4-6", 1)
                result.tier_2_response = ModelAnalysisResponse.from_error(error_msg, "google", "gemini-3.1-pro", 2)
                result.tier_3_response = ModelAnalysisResponse.from_error(error_msg, "xai", "grok-4.2", 3)
                result.failed_models = 3
                result.completed_at = datetime.now(timezone.utc)
                result.total_latency_ms = int((time.time() - start_time) * 1000)
                return result
        
        if content is None:
            raise ValueError("Either file_path or content must be provided")
        
        # Truncate content if too long
        if len(content) > self._max_content_length:
            content = content[:self._max_content_length] + "\n\n[Content truncated...]"
        
        # Select and format the analysis prompt
        if analysis_prompt:
            user_prompt = analysis_prompt.format(content=content)
        elif use_construction_prompt:
            user_prompt = _CONSTRUCTION_ANALYSIS_PROMPT.format(content=content)
        else:
            user_prompt = _DEFAULT_ANALYSIS_PROMPT.format(content=content)
        
        # Default system prompt
        if system_prompt is None:
            system_prompt = (
                "You are an expert document analyst. Analyze documents thoroughly "
                "and provide structured, actionable insights. Always respond with "
                "valid JSON as specified in the prompt."
            )
        
        # Build the AI request
        request = AIRequest(
            capability_class=CapabilityClass.DOCUMENT_ANALYSIS,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=0.1,  # Low temperature for consistent analysis
            calling_agent=calling_agent,
            task_id=task_id,
        )
        
        # Call all models in parallel using the engine's generate_all_models
        try:
            model_results = self._engine.generate_all_models(request)
        except Exception as e:
            logger.error(f"Failed to call generate_all_models: {e}")
            error_msg = str(e)
            result.tier_1_response = ModelAnalysisResponse.from_error(error_msg, "anthropic", "claude-opus-4-6", 1)
            result.tier_2_response = ModelAnalysisResponse.from_error(error_msg, "google", "gemini-3.1-pro", 2)
            result.tier_3_response = ModelAnalysisResponse.from_error(error_msg, "xai", "grok-4.2", 3)
            result.failed_models = 3
            result.completed_at = datetime.now(timezone.utc)
            result.total_latency_ms = int((time.time() - start_time) * 1000)
            return result
        
        # Process results from each tier
        successful = 0
        failed = 0
        
        for tier_num, response_or_error in model_results.items():
            parsed_response = self._process_model_response(tier_num, response_or_error)
            
            if tier_num == 1:
                result.tier_1_response = parsed_response
            elif tier_num == 2:
                result.tier_2_response = parsed_response
            elif tier_num == 3:
                result.tier_3_response = parsed_response
            
            if parsed_response.is_success:
                successful += 1
            else:
                failed += 1
        
        # Finalize result
        result.successful_models = successful
        result.failed_models = failed
        result.completed_at = datetime.now(timezone.utc)
        result.total_latency_ms = int((time.time() - start_time) * 1000)
        
        logger.info(
            f"Document analysis complete: {successful}/3 models succeeded "
            f"in {result.total_latency_ms}ms"
        )
        
        return result
    
    def _process_model_response(
        self,
        tier_num: int,
        response_or_error: Any,
    ) -> ModelAnalysisResponse:
        """Process a single model's response or error.
        
        Args:
            tier_num: Tier number (1, 2, or 3)
            response_or_error: Either an AIResponse or an Exception
            
        Returns:
            ModelAnalysisResponse with parsed content and metadata
        """
        # Map tier to expected model info
        tier_info = {
            1: ("anthropic", "claude-opus-4-6"),
            2: ("google", "gemini-3.1-pro"),
            3: ("xai", "grok-4.2"),
        }
        provider, model = tier_info.get(tier_num, ("unknown", "unknown"))
        
        # Handle exception case
        if isinstance(response_or_error, Exception):
            return ModelAnalysisResponse.from_error(
                error=str(response_or_error),
                provider=provider,
                model=model,
                tier=tier_num,
            )
        
        # Handle successful response
        ai_response: AIResponse = response_or_error
        
        if not ai_response.success:
            return ModelAnalysisResponse.from_error(
                error=ai_response.error or "Unknown error",
                provider=ai_response.metadata.provider if ai_response.metadata else provider,
                model=ai_response.metadata.model if ai_response.metadata else model,
                tier=tier_num,
            )
        
        # Parse the response content
        parsed = self._parse_analysis_content(ai_response.content)
        
        return ModelAnalysisResponse(
            status=AnalysisStatus.SUCCESS,
            content=ai_response.content,
            metadata=AnalysisMetadata(
                model_id=ai_response.metadata.ai_call_id if ai_response.metadata else str(uuid.uuid4()),
                provider=ai_response.metadata.provider if ai_response.metadata else provider,
                model=ai_response.metadata.model if ai_response.metadata else model,
                tier=tier_num,
                latency_ms=ai_response.metadata.latency_ms if ai_response.metadata else 0,
                input_tokens=ai_response.metadata.input_tokens if ai_response.metadata else 0,
                output_tokens=ai_response.metadata.output_tokens if ai_response.metadata else 0,
            ),
            summary=parsed.get("summary"),
            key_findings=parsed.get("key_findings", []),
            recommendations=parsed.get("recommendations", []),
            confidence_score=parsed.get("confidence_score"),
        )
    
    def _parse_analysis_content(self, content: str) -> Dict[str, Any]:
        """Parse structured analysis from model response content.
        
        Attempts to extract JSON from the response, falling back to
        text parsing if JSON extraction fails.
        
        Args:
            content: Raw response content from the model
            
        Returns:
            Dictionary with parsed analysis fields
        """
        if not content:
            return {}
        
        # Try to extract JSON from markdown code block
        json_match = re.search(r'```(?:json)?\s*\n?({[\s\S]*?})\s*\n?```', content)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass
        
        # Try to parse as raw JSON
        try:
            # Find JSON object in content
            start = content.find('{')
            end = content.rfind('}') + 1
            if start >= 0 and end > start:
                return json.loads(content[start:end])
        except json.JSONDecodeError:
            pass
        
        # Fallback: extract text sections
        result: Dict[str, Any] = {}
        
        # Try to extract summary
        summary_match = re.search(
            r'(?:summary|executive summary)[:\s]*([^\n]+(?:\n(?![#*-])[^\n]+)*)',
            content,
            re.IGNORECASE
        )
        if summary_match:
            result["summary"] = summary_match.group(1).strip()
        
        # Try to extract findings as bullet points
        findings = re.findall(
            r'(?:^|\n)\s*[-*•]\s*(.+?)(?=\n\s*[-*•]|\n\n|\Z)',
            content,
            re.MULTILINE
        )
        if findings:
            result["key_findings"] = [f.strip() for f in findings[:5]]
        
        # If no structured parsing worked, use content as summary
        if not result:
            result["summary"] = content[:500] + ("..." if len(content) > 500 else "")
        
        return result
    
    def _extract_content(self, file_path: str) -> Optional[str]:
        """Extract text content from a document file.
        
        Args:
            file_path: Path to the document file
            
        Returns:
            Extracted text content or None if extraction fails
        """
        path = Path(file_path)
        if not path.exists():
            logger.error(f"Document file not found: {file_path}")
            return None
        
        suffix = path.suffix.lower()
        
        try:
            if suffix == ".pdf":
                return self._extract_pdf(file_path)
            elif suffix in (".txt", ".md", ".markdown"):
                return path.read_text(encoding="utf-8")
            elif suffix == ".json":
                return path.read_text(encoding="utf-8")
            elif suffix in (".docx", ".doc"):
                return self._extract_docx(file_path)
            elif suffix in (".xlsx", ".xls", ".csv"):
                return self._extract_spreadsheet(file_path)
            else:
                # Try reading as text
                try:
                    return path.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    logger.error(f"Cannot read binary file as text: {file_path}")
                    return None
        except Exception as e:
            logger.error(f"Content extraction failed for {file_path}: {e}")
            return None
    
    def _extract_pdf(self, file_path: str) -> Optional[str]:
        """Extract text from PDF using the document intelligence pipeline."""
        if self._pdf_extractor:
            try:
                pages = self._pdf_extractor.extract_pages(file_path)
                if pages:
                    return "\n\n".join(p.get("text", "") for p in pages)
            except Exception as e:
                logger.warning(f"PDF extractor failed: {e}")
        
        # Fallback to pypdf
        try:
            import pypdf
            reader = pypdf.PdfReader(file_path)
            text_parts = []
            for page in reader.pages:
                text = page.extract_text()
                if text:
                    text_parts.append(text)
            return "\n\n".join(text_parts)
        except Exception as e:
            logger.error(f"PDF extraction failed: {e}")
            return None
    
    def _extract_docx(self, file_path: str) -> Optional[str]:
        """Extract text from Word document."""
        try:
            import docx
            doc = docx.Document(file_path)
            paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
            return "\n\n".join(paragraphs)
        except ImportError:
            logger.warning("python-docx not installed, trying alternative")
        except Exception as e:
            logger.error(f"DOCX extraction failed: {e}")
        
        return None
    
    def _extract_spreadsheet(self, file_path: str) -> Optional[str]:
        """Extract data from spreadsheet as text."""
        try:
            import pandas as pd
            
            suffix = Path(file_path).suffix.lower()
            if suffix == ".csv":
                df = pd.read_csv(file_path)
            else:
                df = pd.read_excel(file_path)
            
            # Convert to markdown table
            return df.to_markdown(index=False)
        except ImportError:
            logger.warning("pandas not installed")
        except Exception as e:
            logger.error(f"Spreadsheet extraction failed: {e}")
        
        return None
    
    def _detect_document_type(self, file_path: Optional[str]) -> str:
        """Detect document type from file extension."""
        if not file_path:
            return "unknown"
        
        suffix = Path(file_path).suffix.lower()
        type_map = {
            ".pdf": "PDF",
            ".docx": "Word",
            ".doc": "Word",
            ".xlsx": "Excel",
            ".xls": "Excel",
            ".csv": "CSV",
            ".txt": "Text",
            ".md": "Markdown",
            ".json": "JSON",
        }
        return type_map.get(suffix, "unknown")
    
    def get_comparison_view(self, result: MultiModelAnalysisResult) -> ComparisonViewFormatter:
        """Get a comparison view formatter for the analysis result.
        
        Args:
            result: The multi-model analysis result
            
        Returns:
            ComparisonViewFormatter instance for generating various output formats
        """
        return ComparisonViewFormatter(result)
    
    async def analyze_document_async(
        self,
        file_path: Optional[str] = None,
        content: Optional[str] = None,
        **kwargs,
    ) -> MultiModelAnalysisResult:
        """Async wrapper for analyze_document.
        
        Runs the synchronous analysis in a thread pool executor.
        
        Args:
            file_path: Path to the document file
            content: Pre-extracted document content
            **kwargs: Additional arguments passed to analyze_document
            
        Returns:
            MultiModelAnalysisResult with responses from all three models
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: self.analyze_document(file_path=file_path, content=content, **kwargs)
        )


# Module-level convenience function
def analyze_document(
    file_path: Optional[str] = None,
    content: Optional[str] = None,
    **kwargs,
) -> MultiModelAnalysisResult:
    """Convenience function to analyze a document without instantiating the service.
    
    Args:
        file_path: Path to the document file
        content: Pre-extracted document content
        **kwargs: Additional arguments passed to DocumentAnalysisService.analyze_document
        
    Returns:
        MultiModelAnalysisResult with responses from all three models
    """
    service = DocumentAnalysisService()
    return service.analyze_document(file_path=file_path, content=content, **kwargs)
