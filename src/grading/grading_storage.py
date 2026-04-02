"""Persistence layer for the auto-grading system.

Provides storage and retrieval of:
- Grading sessions
- AI and human grades
- Divergence analyses
- Historical grade data for reporting
"""
import json
import logging
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List, Dict, Any

from .grading_models import (
    GradingSession,
    ModelGrade,
    DivergenceAnalysis,
    DivergenceReport,
    DivergenceLevel,
    GradingCriterion,
    GradeSource,
    CriterionScore,
    GradingWeights,
)

logger = logging.getLogger(__name__)


class GradingStorage:
    """SQLite-based storage for grading data.
    
    Uses the same database patterns as the main TeterAI_CA application.
    """
    
    def __init__(self, db_path: Optional[str] = None):
        """Initialize grading storage.
        
        Args:
            db_path: Path to SQLite database. Defaults to project database.
        """
        if db_path is None:
            db_path = str(Path.home() / ".teterai_ca" / "teterai_ca.db")
        
        self._db_path = str(Path(db_path).expanduser())
        self._lock = threading.Lock()
        self._local = threading.local()
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()
    
    def _conn(self) -> sqlite3.Connection:
        """Get thread-local database connection."""
        if not hasattr(self._local, "conn") or self._local.conn is None:
            conn = sqlite3.connect(self._db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            self._local.conn = conn
        return self._local.conn
    
    def _init_schema(self) -> None:
        """Initialize grading tables if they don't exist."""
        conn = self._conn()
        conn.executescript("""
            -- Grading sessions
            CREATE TABLE IF NOT EXISTS grading_sessions (
                session_id TEXT PRIMARY KEY,
                analysis_id TEXT NOT NULL,
                document_id TEXT,
                document_name TEXT,
                status TEXT DEFAULT 'pending',
                weights TEXT DEFAULT '{}',
                created_at TEXT NOT NULL,
                completed_at TEXT
            );
            
            CREATE INDEX IF NOT EXISTS idx_grading_sessions_analysis 
                ON grading_sessions(analysis_id);
            CREATE INDEX IF NOT EXISTS idx_grading_sessions_status 
                ON grading_sessions(status);
            CREATE INDEX IF NOT EXISTS idx_grading_sessions_created 
                ON grading_sessions(created_at);
            
            -- Model grades (both AI and human)
            CREATE TABLE IF NOT EXISTS model_grades (
                grade_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                model_id TEXT NOT NULL,
                model_name TEXT NOT NULL,
                tier INTEGER NOT NULL,
                source TEXT NOT NULL,
                accuracy_score REAL,
                accuracy_reasoning TEXT,
                accuracy_evidence TEXT DEFAULT '[]',
                completeness_score REAL,
                completeness_reasoning TEXT,
                completeness_evidence TEXT DEFAULT '[]',
                relevance_score REAL,
                relevance_reasoning TEXT,
                relevance_evidence TEXT DEFAULT '[]',
                citation_quality_score REAL,
                citation_quality_reasoning TEXT,
                citation_quality_evidence TEXT DEFAULT '[]',
                overall_score REAL NOT NULL,
                grader_id TEXT,
                graded_at TEXT NOT NULL,
                notes TEXT DEFAULT '',
                FOREIGN KEY (session_id) REFERENCES grading_sessions(session_id)
            );
            
            CREATE INDEX IF NOT EXISTS idx_model_grades_session 
                ON model_grades(session_id);
            CREATE INDEX IF NOT EXISTS idx_model_grades_source 
                ON model_grades(source);
            CREATE INDEX IF NOT EXISTS idx_model_grades_model 
                ON model_grades(model_id);
            
            -- Divergence analyses
            CREATE TABLE IF NOT EXISTS divergence_analyses (
                analysis_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                model_id TEXT NOT NULL,
                model_name TEXT NOT NULL,
                ai_grade_id TEXT NOT NULL,
                human_grade_id TEXT NOT NULL,
                criterion_divergences TEXT DEFAULT '[]',
                overall_ai_score REAL NOT NULL,
                overall_human_score REAL NOT NULL,
                overall_difference REAL NOT NULL,
                overall_level TEXT NOT NULL,
                analyzed_at TEXT NOT NULL,
                calibration_notes TEXT DEFAULT '',
                action_items TEXT DEFAULT '[]',
                FOREIGN KEY (session_id) REFERENCES grading_sessions(session_id),
                FOREIGN KEY (ai_grade_id) REFERENCES model_grades(grade_id),
                FOREIGN KEY (human_grade_id) REFERENCES model_grades(grade_id)
            );
            
            CREATE INDEX IF NOT EXISTS idx_divergence_session 
                ON divergence_analyses(session_id);
            CREATE INDEX IF NOT EXISTS idx_divergence_level 
                ON divergence_analyses(overall_level);
            CREATE INDEX IF NOT EXISTS idx_divergence_analyzed 
                ON divergence_analyses(analyzed_at);
        """)
        conn.commit()
        logger.info("Grading storage schema initialized")
    
    # -------------------------------------------------------------------------
    # Session operations
    # -------------------------------------------------------------------------
    
    def create_session(self, session: GradingSession) -> str:
        """Create a new grading session."""
        conn = self._conn()
        conn.execute(
            """INSERT INTO grading_sessions 
               (session_id, analysis_id, document_id, document_name, 
                status, weights, created_at, completed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                session.session_id,
                session.analysis_id,
                session.document_id,
                session.document_name,
                session.status,
                json.dumps(session.weights.model_dump()),
                session.created_at.isoformat(),
                session.completed_at.isoformat() if session.completed_at else None,
            )
        )
        conn.commit()
        logger.info(f"Created grading session {session.session_id}")
        return session.session_id
    
    def get_session(self, session_id: str) -> Optional[GradingSession]:
        """Retrieve a grading session with all grades."""
        conn = self._conn()
        
        # Get session record
        row = conn.execute(
            "SELECT * FROM grading_sessions WHERE session_id = ?",
            (session_id,)
        ).fetchone()
        
        if not row:
            return None
        
        # Build session object
        session = GradingSession(
            session_id=row["session_id"],
            analysis_id=row["analysis_id"],
            document_id=row["document_id"],
            document_name=row["document_name"],
            status=row["status"],
            weights=GradingWeights(**json.loads(row["weights"] or "{}")),
            created_at=datetime.fromisoformat(row["created_at"]),
            completed_at=datetime.fromisoformat(row["completed_at"]) if row["completed_at"] else None,
        )
        
        # Load grades
        grades = conn.execute(
            "SELECT * FROM model_grades WHERE session_id = ?",
            (session_id,)
        ).fetchall()
        
        for g in grades:
            grade = self._row_to_grade(g)
            if grade.source == GradeSource.AI_JUDGE:
                session.ai_grades[grade.model_id] = grade
            else:
                session.human_grades[grade.model_id] = grade
        
        # Load divergence analyses
        analyses = conn.execute(
            "SELECT * FROM divergence_analyses WHERE session_id = ?",
            (session_id,)
        ).fetchall()
        
        for a in analyses:
            analysis = self._row_to_divergence(a)
            session.divergence_analyses[analysis.model_id] = analysis
        
        return session
    
    def update_session_status(self, session_id: str, status: str) -> None:
        """Update session status."""
        conn = self._conn()
        completed_at = None
        if status == "complete":
            completed_at = datetime.now(timezone.utc).isoformat()
        
        conn.execute(
            "UPDATE grading_sessions SET status = ?, completed_at = ? WHERE session_id = ?",
            (status, completed_at, session_id)
        )
        conn.commit()
    
    def list_sessions(
        self,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """List grading sessions with optional filtering."""
        conn = self._conn()
        
        sql = "SELECT * FROM grading_sessions"
        params = []
        
        if status:
            sql += " WHERE status = ?"
            params.append(status)
        
        sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
    
    # -------------------------------------------------------------------------
    # Grade operations
    # -------------------------------------------------------------------------
    
    def save_grade(self, session_id: str, grade: ModelGrade) -> str:
        """Save a model grade (AI or human)."""
        conn = self._conn()
        
        conn.execute(
            """INSERT OR REPLACE INTO model_grades
               (grade_id, session_id, model_id, model_name, tier, source,
                accuracy_score, accuracy_reasoning, accuracy_evidence,
                completeness_score, completeness_reasoning, completeness_evidence,
                relevance_score, relevance_reasoning, relevance_evidence,
                citation_quality_score, citation_quality_reasoning, citation_quality_evidence,
                overall_score, grader_id, graded_at, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                grade.grade_id,
                session_id,
                grade.model_id,
                grade.model_name,
                grade.tier,
                grade.source.value,
                grade.accuracy.score if grade.accuracy else None,
                grade.accuracy.reasoning if grade.accuracy else None,
                json.dumps(grade.accuracy.evidence if grade.accuracy else []),
                grade.completeness.score if grade.completeness else None,
                grade.completeness.reasoning if grade.completeness else None,
                json.dumps(grade.completeness.evidence if grade.completeness else []),
                grade.relevance.score if grade.relevance else None,
                grade.relevance.reasoning if grade.relevance else None,
                json.dumps(grade.relevance.evidence if grade.relevance else []),
                grade.citation_quality.score if grade.citation_quality else None,
                grade.citation_quality.reasoning if grade.citation_quality else None,
                json.dumps(grade.citation_quality.evidence if grade.citation_quality else []),
                grade.overall_score,
                grade.grader_id,
                grade.graded_at.isoformat(),
                grade.notes,
            )
        )
        conn.commit()
        logger.info(f"Saved {grade.source.value} grade {grade.grade_id} for model {grade.model_name}")
        return grade.grade_id
    
    def get_grade(self, grade_id: str) -> Optional[ModelGrade]:
        """Retrieve a specific grade."""
        conn = self._conn()
        row = conn.execute(
            "SELECT * FROM model_grades WHERE grade_id = ?",
            (grade_id,)
        ).fetchone()
        
        if not row:
            return None
        return self._row_to_grade(row)
    
    def get_grades_for_session(
        self,
        session_id: str,
        source: Optional[GradeSource] = None,
    ) -> List[ModelGrade]:
        """Get all grades for a session."""
        conn = self._conn()
        
        sql = "SELECT * FROM model_grades WHERE session_id = ?"
        params = [session_id]
        
        if source:
            sql += " AND source = ?"
            params.append(source.value)
        
        rows = conn.execute(sql, params).fetchall()
        return [self._row_to_grade(r) for r in rows]
    
    def _row_to_grade(self, row: sqlite3.Row) -> ModelGrade:
        """Convert database row to ModelGrade object."""
        grade = ModelGrade(
            grade_id=row["grade_id"],
            model_id=row["model_id"],
            model_name=row["model_name"],
            tier=row["tier"],
            source=GradeSource(row["source"]),
            overall_score=row["overall_score"],
            grader_id=row["grader_id"],
            graded_at=datetime.fromisoformat(row["graded_at"]),
            notes=row["notes"] or "",
        )
        
        # Build criterion scores
        if row["accuracy_score"] is not None:
            grade.accuracy = CriterionScore(
                criterion=GradingCriterion.ACCURACY,
                score=row["accuracy_score"],
                reasoning=row["accuracy_reasoning"] or "",
                evidence=json.loads(row["accuracy_evidence"] or "[]"),
            )
        
        if row["completeness_score"] is not None:
            grade.completeness = CriterionScore(
                criterion=GradingCriterion.COMPLETENESS,
                score=row["completeness_score"],
                reasoning=row["completeness_reasoning"] or "",
                evidence=json.loads(row["completeness_evidence"] or "[]"),
            )
        
        if row["relevance_score"] is not None:
            grade.relevance = CriterionScore(
                criterion=GradingCriterion.RELEVANCE,
                score=row["relevance_score"],
                reasoning=row["relevance_reasoning"] or "",
                evidence=json.loads(row["relevance_evidence"] or "[]"),
            )
        
        if row["citation_quality_score"] is not None:
            grade.citation_quality = CriterionScore(
                criterion=GradingCriterion.CITATION_QUALITY,
                score=row["citation_quality_score"],
                reasoning=row["citation_quality_reasoning"] or "",
                evidence=json.loads(row["citation_quality_evidence"] or "[]"),
            )
        
        return grade
    
    # -------------------------------------------------------------------------
    # Divergence operations
    # -------------------------------------------------------------------------
    
    def save_divergence(self, analysis: DivergenceAnalysis) -> str:
        """Save a divergence analysis."""
        conn = self._conn()
        
        conn.execute(
            """INSERT OR REPLACE INTO divergence_analyses
               (analysis_id, session_id, model_id, model_name,
                ai_grade_id, human_grade_id, criterion_divergences,
                overall_ai_score, overall_human_score, overall_difference,
                overall_level, analyzed_at, calibration_notes, action_items)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                analysis.analysis_id,
                analysis.session_id,
                analysis.model_id,
                analysis.model_name,
                analysis.ai_grade_id,
                analysis.human_grade_id,
                json.dumps([
                    {
                        "criterion": cd.criterion.value,
                        "ai_score": cd.ai_score,
                        "human_score": cd.human_score,
                        "difference": cd.difference,
                        "level": cd.level.value,
                        "notes": cd.notes,
                    }
                    for cd in analysis.criterion_divergences
                ]),
                analysis.overall_ai_score,
                analysis.overall_human_score,
                analysis.overall_difference,
                analysis.overall_level.value,
                analysis.analyzed_at.isoformat(),
                analysis.calibration_notes,
                json.dumps(analysis.action_items),
            )
        )
        conn.commit()
        logger.info(f"Saved divergence analysis {analysis.analysis_id}")
        return analysis.analysis_id
    
    def _row_to_divergence(self, row: sqlite3.Row) -> DivergenceAnalysis:
        """Convert database row to DivergenceAnalysis object."""
        from .grading_models import CriterionDivergence
        
        crit_data = json.loads(row["criterion_divergences"] or "[]")
        criterion_divergences = [
            CriterionDivergence(
                criterion=GradingCriterion(cd["criterion"]),
                ai_score=cd["ai_score"],
                human_score=cd["human_score"],
                difference=cd["difference"],
                level=DivergenceLevel(cd["level"]),
                notes=cd.get("notes", ""),
            )
            for cd in crit_data
        ]
        
        return DivergenceAnalysis(
            analysis_id=row["analysis_id"],
            session_id=row["session_id"],
            model_id=row["model_id"],
            model_name=row["model_name"],
            ai_grade_id=row["ai_grade_id"],
            human_grade_id=row["human_grade_id"],
            criterion_divergences=criterion_divergences,
            overall_ai_score=row["overall_ai_score"],
            overall_human_score=row["overall_human_score"],
            overall_difference=row["overall_difference"],
            overall_level=DivergenceLevel(row["overall_level"]),
            analyzed_at=datetime.fromisoformat(row["analyzed_at"]),
            calibration_notes=row["calibration_notes"] or "",
            action_items=json.loads(row["action_items"] or "[]"),
        )
    
    # -------------------------------------------------------------------------
    # Reporting
    # -------------------------------------------------------------------------
    
    def generate_divergence_report(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        model_filter: Optional[str] = None,
    ) -> DivergenceReport:
        """Generate an aggregated divergence report."""
        conn = self._conn()
        
        # Build query
        sql = "SELECT * FROM divergence_analyses"
        clauses = []
        params = []
        
        if start_date:
            clauses.append("analyzed_at >= ?")
            params.append(start_date.isoformat())
        if end_date:
            clauses.append("analyzed_at <= ?")
            params.append(end_date.isoformat())
        if model_filter:
            clauses.append("model_id = ?")
            params.append(model_filter)
        
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        
        sql += " ORDER BY analyzed_at"
        rows = conn.execute(sql, params).fetchall()
        
        if not rows:
            return DivergenceReport(
                start_date=start_date,
                end_date=end_date,
                model_filter=model_filter,
            )
        
        # Compute statistics
        overall_diffs = []
        criterion_diffs: Dict[str, List[float]] = {
            c.value: [] for c in GradingCriterion
        }
        level_counts = {"none": 0, "low": 0, "medium": 0, "high": 0}
        model_data: Dict[str, List[float]] = {}
        trend_data = []
        unique_sessions = set()
        
        for row in rows:
            analysis = self._row_to_divergence(row)
            unique_sessions.add(analysis.session_id)
            overall_diffs.append(abs(analysis.overall_difference))
            level_counts[analysis.overall_level.value] += 1
            
            # Per-model tracking
            if analysis.model_id not in model_data:
                model_data[analysis.model_id] = []
            model_data[analysis.model_id].append(abs(analysis.overall_difference))
            
            # Per-criterion tracking
            for cd in analysis.criterion_divergences:
                criterion_diffs[cd.criterion.value].append(abs(cd.difference))
            
            # Trend data point
            trend_data.append({
                "date": analysis.analyzed_at.isoformat(),
                "model_id": analysis.model_id,
                "difference": analysis.overall_difference,
                "level": analysis.overall_level.value,
            })
        
        # Compute criterion stats
        criterion_stats = {}
        for crit, diffs in criterion_diffs.items():
            if diffs:
                criterion_stats[crit] = {
                    "avg": round(sum(diffs) / len(diffs), 2),
                    "max": round(max(diffs), 2),
                    "min": round(min(diffs), 2),
                    "count": len(diffs),
                }
        
        # Compute model stats
        model_stats = {}
        for model_id, diffs in model_data.items():
            model_stats[model_id] = {
                "avg_divergence": round(sum(diffs) / len(diffs), 2),
                "max_divergence": round(max(diffs), 2),
                "min_divergence": round(min(diffs), 2),
                "count": len(diffs),
            }
        
        # Generate recommendations
        recommendations = []
        if overall_diffs:
            avg_div = sum(overall_diffs) / len(overall_diffs)
            if avg_div > 1.5:
                recommendations.append(
                    "High average divergence detected. Consider reviewing AI grading rubrics."
                )
            
            # Check for systematic bias per criterion
            for crit, stats in criterion_stats.items():
                if stats["avg"] > 1.5:
                    recommendations.append(
                        f"High divergence in {crit} criterion (avg: {stats['avg']}). "
                        f"Consider updating {crit} evaluation guidelines."
                    )
        
        return DivergenceReport(
            start_date=start_date,
            end_date=end_date,
            model_filter=model_filter,
            total_sessions=len(unique_sessions),
            total_grades_compared=len(rows),
            avg_overall_divergence=round(sum(overall_diffs) / len(overall_diffs), 2) if overall_diffs else 0,
            max_overall_divergence=round(max(overall_diffs), 2) if overall_diffs else 0,
            min_overall_divergence=round(min(overall_diffs), 2) if overall_diffs else 0,
            criterion_stats=criterion_stats,
            level_distribution=level_counts,
            model_stats=model_stats,
            trend_data=trend_data,
            recommendations=recommendations,
        )


# Module-level singleton
_storage_instance: Optional[GradingStorage] = None


def get_grading_storage() -> GradingStorage:
    """Get or create the grading storage singleton."""
    global _storage_instance
    if _storage_instance is None:
        _storage_instance = GradingStorage()
    return _storage_instance
