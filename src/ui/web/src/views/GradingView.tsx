import { useState, useEffect } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import {
  listGradingSessions,
  getPendingGradingSessions,
  getGradingSession,
  getSessionForGrading,
  getAIGradeForModel,
  submitHumanGrade,
  getDivergenceReport,
  addDivergenceNotes,
} from '../api/client'
import { useAuth } from '../hooks/useAuth'
import type {
  GradingSession,
  GradingSessionSummary,
  ModelGrade,
  DivergenceReport,
  DivergenceAnalysis,
  GradingCriterion,
} from '../types'

type ViewMode = 'list' | 'grade' | 'review' | 'report'

/**
 * Grading View — AI vs Human grading comparison interface.
 * 
 * Features:
 * - List of grading sessions pending human review
 * - Human grading interface with AI grade comparison
 * - Divergence analysis and calibration notes
 * - Aggregated divergence reports
 */
// Helpers for Trend Line SVG
function DivergenceTrendChart({ data }: { data: {date: string, avg_divergence: number, sessions: number}[] }) {
  if (!data || data.length < 2) return null

  const width = 400
  const height = 120
  const padding = { top: 20, right: 20, bottom: 20, left: 30 }

  const maxDiv = Math.max(1.5, ...data.map(d => d.avg_divergence))

  const getX = (index: number) => padding.left + (index / (data.length - 1)) * (width - padding.left - padding.right)
  const getY = (val: number) => height - padding.bottom - (val / maxDiv) * (height - padding.top - padding.bottom)

  const points = data.map((d, i) => `${getX(i)},${getY(d.avg_divergence)}`).join(' ')
  const refY = getY(1.0)

  return (
    <div className="mt-6 bg-white p-4 rounded border border-gray-200 shadow-sm flex flex-col items-center">
      <h3 className="text-sm font-semibold text-teter-dark mb-2">Divergence Trend (Avg over time)</h3>
      <svg width={width} height={height} className="overflow-visible font-sans text-[10px]">
        {/* Y Axis Labels */}
        <text x={padding.left - 5} y={getY(maxDiv)} textAnchor="end" dominantBaseline="middle" fill="#9CA3AF">{maxDiv.toFixed(1)}</text>
        <text x={padding.left - 5} y={getY(0)} textAnchor="end" dominantBaseline="middle" fill="#9CA3AF">0.0</text>

        {/* Threshold Line (1.0) */}
        <line x1={padding.left} y1={refY} x2={width - padding.right} y2={refY} stroke="#EF4444" strokeWidth="1" strokeDasharray="4 4" />
        <text x={width - padding.right + 5} y={refY} dominantBaseline="middle" fill="#EF4444" className="font-semibold">1.0</text>

        {/* X Axis Line */}
        <line x1={padding.left} y1={height - padding.bottom} x2={width - padding.right} y2={height - padding.bottom} stroke="#E5E7EB" strokeWidth="1" />

        {/* Trend Line */}
        <polyline points={points} fill="none" stroke="#3B82F6" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />

        {/* Data Points */}
        {data.map((d, i) => (
          <g key={i}>
            <circle cx={getX(i)} cy={getY(d.avg_divergence)} r="4" fill="#3B82F6" className="cursor-pointer transition-transform hover:scale-150" />
            <title>{`${d.date}: ${d.avg_divergence.toFixed(2)} (${d.sessions} sessions)`}</title>
          </g>
        ))}
      </svg>
    </div>
  )
}

export function GradingView() {
  const { sessionId } = useParams<{ sessionId?: string }>()
  const navigate = useNavigate()
  const [mode, setMode] = useState<ViewMode>(sessionId ? 'grade' : 'list')
  const [sessions, setSessions] = useState<GradingSessionSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (sessionId) {
      setMode('grade')
    } else {
      loadSessions()
    }
  }, [sessionId])

  const loadSessions = async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await getPendingGradingSessions()
      setSessions(data)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load sessions')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="max-w-wide mx-auto px-4 py-8">
      {/* Header */}
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-2xl font-semibold text-white mb-2">Grading & Calibration</h1>
          <p className="text-teter-gray-text">
            Review AI grades and submit human assessments for model calibration.
          </p>
        </div>
        <div className="flex gap-2">
          <ModeButton active={mode === 'list'} onClick={() => { setMode('list'); navigate('/grading'); }}>
            Pending Reviews
          </ModeButton>
          <ModeButton active={mode === 'report'} onClick={() => setMode('report')}>
            Divergence Report
          </ModeButton>
        </div>
      </div>

      {error && (
        <div className="bg-red-500/10 border border-red-500/30 text-red-400 rounded-lg px-4 py-3 mb-6">
          {error}
        </div>
      )}

      {mode === 'list' && (
        <SessionList sessions={sessions} loading={loading} onSelect={(id) => navigate(`/grading/${id}`)} />
      )}
      {mode === 'grade' && sessionId && <GradingInterface sessionId={sessionId} />}
      {mode === 'report' && <DivergenceReportView />}
    </div>
  )
}

function ModeButton({
  active,
  onClick,
  children,
}: {
  active: boolean
  onClick: () => void
  children: React.ReactNode
}) {
  return (
    <button
      onClick={onClick}
      className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
        active
          ? 'bg-teter-orange text-white'
          : 'bg-white/5 text-teter-gray-text hover:bg-white/10 hover:text-white'
      }`}
    >
      {children}
    </button>
  )
}

function SessionList({
  sessions,
  loading,
  onSelect,
}: {
  sessions: GradingSessionSummary[]
  loading: boolean
  onSelect: (id: string) => void
}) {
  if (loading) {
    return (
      <div className="text-center py-12 text-teter-gray-text">
        Loading sessions...
      </div>
    )
  }

  if (sessions.length === 0) {
    return (
      <div className="bg-teter-card border border-white/8 rounded-xl p-12 text-center">
        <svg className="w-16 h-16 mx-auto mb-4 text-teter-gray-text" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
        <h3 className="text-white font-medium mb-2">No Pending Reviews</h3>
        <p className="text-teter-gray-text text-sm">
          All grading sessions have been reviewed. Run a document analysis to create new sessions.
        </p>
        <Link
          to="/document-analysis"
          className="inline-block mt-4 px-4 py-2 bg-teter-orange text-white rounded-lg hover:bg-teter-orange-light transition-colors"
        >
          Go to Document Analysis
        </Link>
      </div>
    )
  }

  return (
    <div className="space-y-3">
      {sessions.map((session) => (
        <div
          key={session.session_id}
          onClick={() => onSelect(session.session_id)}
          className="bg-teter-card border border-white/8 rounded-xl p-4 cursor-pointer hover:border-teter-orange/50 transition-colors"
        >
          <div className="flex items-center justify-between">
            <div>
              <h3 className="text-white font-medium">{session.document_name || 'Unnamed Document'}</h3>
              <p className="text-sm text-teter-gray-text">Session: {session.session_id.slice(0, 8)}...</p>
            </div>
            <div className="flex items-center gap-4">
              <div className="text-right">
                <div className="text-sm text-teter-gray-text">AI Graded</div>
                <div className="text-white font-medium">
                  {session.ai_graded_count}/{session.model_count}
                </div>
              </div>
              <div className="text-right">
                <div className="text-sm text-teter-gray-text">Human Graded</div>
                <div className="text-white font-medium">
                  {session.human_graded_count}/{session.model_count}
                </div>
              </div>
              {session.avg_ai_score && (
                <div className="text-right">
                  <div className="text-sm text-teter-gray-text">Avg AI Score</div>
                  <div className="text-teter-orange font-medium">
                    {session.avg_ai_score.toFixed(1)}/10
                  </div>
                </div>
              )}
              <StatusBadge status={session.status} />
            </div>
          </div>
        </div>
      ))}
    </div>
  )
}

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    pending: 'bg-gray-500/20 text-gray-400',
    ai_graded: 'bg-yellow-500/20 text-yellow-400',
    human_graded: 'bg-blue-500/20 text-blue-400',
    complete: 'bg-green-500/20 text-green-400',
  }

  return (
    <span className={`px-3 py-1 rounded-full text-xs font-medium ${colors[status] || colors.pending}`}>
      {status.replace('_', ' ')}
    </span>
  )
}

function GradingInterface({ sessionId }: { sessionId: string }) {
  const { user } = useAuth()
  const navigate = useNavigate()
  const [session, setSession] = useState<GradingSession | null>(null)
  const [modelsAwaiting, setModelsAwaiting] = useState<string[]>([])
  const [selectedModel, setSelectedModel] = useState<string | null>(null)
  const [aiGrade, setAiGrade] = useState<ModelGrade | null>(null)
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Human grade form state
  const [scores, setScores] = useState({
    accuracy: { score: 7, reasoning: '' },
    completeness: { score: 7, reasoning: '' },
    relevance: { score: 7, reasoning: '' },
    citation_quality: { score: 7, reasoning: '' },
  })
  const [notes, setNotes] = useState('')

  useEffect(() => {
    loadSession()
  }, [sessionId])

  useEffect(() => {
    if (selectedModel) {
      loadAIGrade(selectedModel)
    }
  }, [selectedModel])

  const loadSession = async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await getSessionForGrading(sessionId)
      setSession(data.session)
      setModelsAwaiting(data.models_awaiting_human_grade)
      if (data.models_awaiting_human_grade.length > 0) {
        setSelectedModel(data.models_awaiting_human_grade[0])
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load session')
    } finally {
      setLoading(false)
    }
  }

  const loadAIGrade = async (modelId: string) => {
    try {
      const data = await getAIGradeForModel(sessionId, modelId)
      setAiGrade(data.grade)
      // Pre-fill human scores with AI scores as starting point
      setScores({
        accuracy: { score: data.grade.accuracy.score, reasoning: '' },
        completeness: { score: data.grade.completeness.score, reasoning: '' },
        relevance: { score: data.grade.relevance.score, reasoning: '' },
        citation_quality: { score: data.grade.citation_quality.score, reasoning: '' },
      })
    } catch (e) {
      console.error('Failed to load AI grade:', e)
    }
  }

  const handleSubmit = async () => {
    if (!selectedModel || !user) return
    setSubmitting(true)
    setError(null)
    try {
      await submitHumanGrade({
        session_id: sessionId,
        model_id: selectedModel,
        grader_id: user.uid,
        scores: scores as any,
        notes: notes || undefined,
      })
      // Reload session
      await loadSession()
      setNotes('')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to submit grade')
    } finally {
      setSubmitting(false)
    }
  }

  if (loading) {
    return <div className="text-center py-12 text-teter-gray-text">Loading session...</div>
  }

  if (!session) {
    return <div className="text-center py-12 text-red-400">{error || 'Session not found'}</div>
  }

  // If all models graded, show review view
  if (modelsAwaiting.length === 0) {
    return <SessionReview session={session} />
  }

  return (
    <div className="space-y-6">
      {/* Model Selection */}
      <div className="bg-teter-card border border-white/8 rounded-xl p-4">
        <h3 className="text-white font-medium mb-3">Models Awaiting Human Review</h3>
        <div className="flex gap-2 flex-wrap">
          {modelsAwaiting.map((modelId) => {
            const grade = session.ai_grades[modelId]
            return (
              <button
                key={modelId}
                onClick={() => setSelectedModel(modelId)}
                className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
                  selectedModel === modelId
                    ? 'bg-teter-orange text-white'
                    : 'bg-white/5 text-teter-gray-text hover:bg-white/10'
                }`}
              >
                {grade?.model_name || modelId}
              </button>
            )
          })}
        </div>
      </div>

      {error && (
        <div className="bg-red-500/10 border border-red-500/30 text-red-400 rounded-lg px-4 py-3">
          {error}
        </div>
      )}

      {/* Grading Form */}
      {aiGrade && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* AI Grade Display */}
          <div className="bg-teter-card border border-white/8 rounded-xl p-6">
            <h3 className="text-white font-medium mb-4 flex items-center gap-2">
              <span className="w-2 h-2 bg-blue-500 rounded-full"></span>
              AI Grade — {aiGrade.model_name}
            </h3>
            <div className="text-3xl font-bold text-blue-400 mb-4">
              {aiGrade.overall_score.toFixed(1)}/10
            </div>
            <div className="space-y-4">
              <GradeDisplay label="Accuracy" score={aiGrade.accuracy} />
              <GradeDisplay label="Completeness" score={aiGrade.completeness} />
              <GradeDisplay label="Relevance" score={aiGrade.relevance} />
              <GradeDisplay label="Citation Quality" score={aiGrade.citation_quality} />
            </div>
          </div>

          {/* Human Grade Form */}
          <div className="bg-teter-card border border-white/8 rounded-xl p-6">
            <h3 className="text-white font-medium mb-4 flex items-center gap-2">
              <span className="w-2 h-2 bg-green-500 rounded-full"></span>
              Your Assessment
            </h3>
            <div className="space-y-4">
              <ScoreInput
                label="Accuracy"
                value={scores.accuracy}
                onChange={(v) => setScores({ ...scores, accuracy: v })}
              />
              <ScoreInput
                label="Completeness"
                value={scores.completeness}
                onChange={(v) => setScores({ ...scores, completeness: v })}
              />
              <ScoreInput
                label="Relevance"
                value={scores.relevance}
                onChange={(v) => setScores({ ...scores, relevance: v })}
              />
              <ScoreInput
                label="Citation Quality"
                value={scores.citation_quality}
                onChange={(v) => setScores({ ...scores, citation_quality: v })}
              />

              <div>
                <label className="block text-sm text-teter-gray-text mb-2">Notes (optional)</label>
                <textarea
                  value={notes}
                  onChange={(e) => setNotes(e.target.value)}
                  rows={3}
                  placeholder="Any additional observations..."
                  className="w-full bg-teter-dark border border-white/15 rounded-lg px-4 py-2 text-white placeholder-white/40 focus:border-teter-orange focus:outline-none"
                />
              </div>

              <button
                onClick={handleSubmit}
                disabled={submitting}
                className="w-full px-6 py-3 bg-green-600 text-white font-medium rounded-lg hover:bg-green-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                {submitting ? 'Submitting...' : 'Submit Human Grade'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function GradeDisplay({
  label,
  score,
}: {
  label: string
  score: { score: number; reasoning: string }
}) {
  return (
    <div className="bg-teter-dark rounded-lg p-3">
      <div className="flex items-center justify-between mb-1">
        <span className="text-sm text-teter-gray-text">{label}</span>
        <span className="text-lg font-bold text-white">{score.score.toFixed(1)}</span>
      </div>
      <p className="text-xs text-teter-gray-text">{score.reasoning}</p>
    </div>
  )
}

function ScoreInput({
  label,
  value,
  onChange,
}: {
  label: string
  value: { score: number; reasoning: string }
  onChange: (v: { score: number; reasoning: string }) => void
}) {
  return (
    <div className="bg-teter-dark rounded-lg p-3">
      <div className="flex items-center justify-between mb-2">
        <span className="text-sm text-teter-gray-text">{label}</span>
        <div className="flex items-center gap-2">
          <input
            type="range"
            min="0"
            max="10"
            step="0.5"
            value={value.score}
            onChange={(e) => onChange({ ...value, score: parseFloat(e.target.value) })}
            className="w-24 accent-teter-orange"
          />
          <span className="text-lg font-bold text-white w-8">{value.score.toFixed(1)}</span>
        </div>
      </div>
      <input
        type="text"
        value={value.reasoning}
        onChange={(e) => onChange({ ...value, reasoning: e.target.value })}
        placeholder="Your reasoning..."
        className="w-full bg-white/5 border border-white/10 rounded px-3 py-1.5 text-sm text-white placeholder-white/30 focus:border-teter-orange focus:outline-none"
      />
    </div>
  )
}

function SessionReview({ session }: { session: GradingSession }) {
  const divergences = Object.values(session.divergence_analyses)

  return (
    <div className="space-y-6">
      <div className="bg-green-500/10 border border-green-500/30 text-green-400 rounded-lg px-4 py-3">
        ✓ All models have been graded. Review the divergence analysis below.
      </div>

      {divergences.map((div) => (
        <DivergenceCard key={div.analysis_id} divergence={div} sessionId={session.session_id} />
      ))}
    </div>
  )
}

function DivergenceCard({
  divergence,
  sessionId,
}: {
  divergence: DivergenceAnalysis
  sessionId: string
}) {
  const [notes, setNotes] = useState(divergence.calibration_notes || '')
  const [saving, setSaving] = useState(false)

  const levelColors: Record<string, string> = {
    NONE: 'bg-green-500/20 text-green-400 border-green-500/30',
    LOW: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
    MEDIUM: 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30',
    HIGH: 'bg-red-500/20 text-red-400 border-red-500/30',
  }

  const handleSaveNotes = async () => {
    setSaving(true)
    try {
      await addDivergenceNotes(sessionId, divergence.model_id, notes)
    } catch (e) {
      console.error('Failed to save notes:', e)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="bg-teter-card border border-white/8 rounded-xl p-6">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-white font-medium">{divergence.model_name}</h3>
        <span className={`px-3 py-1 rounded-full text-xs font-medium border ${levelColors[divergence.overall_level]}`}>
          {divergence.overall_level} Divergence
        </span>
      </div>

      <div className="grid grid-cols-3 gap-4 mb-4">
        <div className="text-center">
          <div className="text-sm text-teter-gray-text">AI Score</div>
          <div className="text-2xl font-bold text-blue-400">{divergence.overall_ai_score.toFixed(1)}</div>
        </div>
        <div className="text-center">
          <div className="text-sm text-teter-gray-text">Human Score</div>
          <div className="text-2xl font-bold text-green-400">{divergence.overall_human_score.toFixed(1)}</div>
        </div>
        <div className="text-center">
          <div className="text-sm text-teter-gray-text">Difference</div>
          <div className={`text-2xl font-bold ${Math.abs(divergence.overall_difference) > 1 ? 'text-red-400' : 'text-white'}`}>
            {divergence.overall_difference > 0 ? '+' : ''}{divergence.overall_difference.toFixed(1)}
          </div>
        </div>
      </div>

      {/* Criterion Breakdown */}
      <div className="grid grid-cols-4 gap-2 mb-4">
        {divergence.criterion_divergences.map((cd) => (
          <div key={cd.criterion} className="bg-teter-dark rounded p-2 text-center">
            <div className="text-xs text-teter-gray-text">{cd.criterion.replace('_', ' ')}</div>
            <div className={`text-sm font-medium ${levelColors[cd.level]?.split(' ')[1] || 'text-white'}`}>
              {cd.difference > 0 ? '+' : ''}{cd.difference.toFixed(1)}
            </div>
          </div>
        ))}
      </div>

      {/* Calibration Notes */}
      <div>
        <label className="block text-sm text-teter-gray-text mb-2">Calibration Notes</label>
        <div className="flex gap-2">
          <input
            type="text"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            placeholder="Notes for AI calibration..."
            className="flex-1 bg-teter-dark border border-white/15 rounded-lg px-4 py-2 text-white placeholder-white/40 focus:border-teter-orange focus:outline-none"
          />
          <button
            onClick={handleSaveNotes}
            disabled={saving}
            className="px-4 py-2 bg-teter-orange text-white rounded-lg hover:bg-teter-orange-light disabled:opacity-50 transition-colors"
          >
            {saving ? 'Saving...' : 'Save'}
          </button>
        </div>
      </div>
    </div>
  )
}

function DivergenceReportView() {
  const [report, setReport] = useState<DivergenceReport | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    loadReport()
  }, [])

  const loadReport = async () => {
    setLoading(true)
    try {
      const data = await getDivergenceReport()
      setReport(data)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load report')
    } finally {
      setLoading(false)
    }
  }

  if (loading) {
    return <div className="text-center py-12 text-teter-gray-text">Loading report...</div>
  }

  if (error) {
    return <div className="text-center py-12 text-red-400">{error}</div>
  }

  if (!report) {
    return <div className="text-center py-12 text-teter-gray-text">No report available</div>
  }

  return (
    <div className="space-y-6">
      {/* Summary Stats */}
      <div className="grid grid-cols-4 gap-4">
        <StatCard label="Total Sessions" value={report.total_sessions} />
        <StatCard label="Total Analyses" value={report.total_analyses} />
        <StatCard label="Avg Divergence" value={report.avg_divergence.toFixed(2)} highlight />
        <StatCard label="High Divergence" value={report.high_divergence_count} alert={report.high_divergence_count > 0} />
      </div>

      {/* Divergence by Criterion */}
      <div className="bg-teter-card border border-white/8 rounded-xl p-6">
        <h3 className="text-white font-medium mb-4">Divergence by Criterion</h3>
        <div className="grid grid-cols-4 gap-4">
          {Object.entries(report.divergence_by_criterion).map(([criterion, value]) => (
            <div key={criterion} className="bg-teter-dark rounded-lg p-4 text-center">
              <div className="text-sm text-teter-gray-text mb-1">{criterion.replace('_', ' ')}</div>
              <div className={`text-2xl font-bold ${value > 1 ? 'text-red-400' : value > 0.5 ? 'text-yellow-400' : 'text-green-400'}`}>
                {value.toFixed(2)}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Recommendations */}
      {report.recommendations.length > 0 && (
        <div className="bg-teter-card border border-white/8 rounded-xl p-6">
          <h3 className="text-white font-medium mb-4">Recommendations</h3>
          <ul className="space-y-2">
            {report.recommendations.map((rec, i) => (
              <li key={i} className="flex items-start gap-2 text-teter-gray-text">
                <span className="text-teter-orange">→</span>
                {rec}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

function StatCard({
  label,
  value,
  highlight,
  alert,
}: {
  label: string
  value: string | number
  highlight?: boolean
  alert?: boolean
}) {
  return (
    <div className="bg-teter-card border border-white/8 rounded-xl p-4">
      <div className="text-sm text-teter-gray-text mb-1">{label}</div>
      <div className={`text-2xl font-bold ${alert ? 'text-red-400' : highlight ? 'text-teter-orange' : 'text-white'}`}>
        {value}
      </div>
    </div>
  )
}
