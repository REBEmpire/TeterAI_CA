import { useState, useCallback } from 'react'
import { useDropzone } from 'react-dropzone'
import { analyzeDocument, gradeAnalysis, type AnalyzeDocumentResponse } from '../api/client'
import { ConfidenceMeter } from '../components/common/ConfidenceMeter'
import type { ComparisonColumn, MultiModelAnalysisResult, GradingSession } from '../types'

type Tab = 'comparison' | 'raw' | 'grading'

/**
 * Document Analysis View — Multi-model document analysis with side-by-side comparison.
 * 
 * Features:
 * - Drag-and-drop document upload
 * - Parallel analysis with Claude Opus, Gemini Pro, and Grok
 * - Side-by-side comparison view
 * - AI grading integration
 */

// Helpers for the Radar Chart
function RadarChart({ models, width = 300, height = 300 }: { models: any[], width?: number, height?: number }) {
  if (!models || models.length === 0) return null

  const cx = width / 2
  const cy = height / 2
  const radius = Math.min(cx, cy) - 40 // Padding

  // The 4 axes
  const axes = ['accuracy', 'completeness', 'relevance', 'citation_quality']
  const axisLabels = ['Accuracy', 'Completeness', 'Relevance', 'Citation']
  const angleSlice = (Math.PI * 2) / axes.length

  // Parse scores from model.columns
  const modelData = models.map((m, i) => {
    // Find numeric score in text like "Score: 8/10" or just use default
    const getScore = (key: string) => {
      const col = m.columns.find((c: any) => c.title.toLowerCase().includes(key))
      if (!col) return 5
      const match = col.content.match(/(?:Score|Rating):?\s*(\d+(?:\.\d+)?)/i)
      if (match) return parseFloat(match[1])
      // Try to parse confidence score if it exists and we're looking at accuracy
      if (key === 'accuracy' && m.confidence_score) return m.confidence_score * 10
      return 5 // default fallback
    }

    return {
      name: m.model_name || `Model ${i+1}`,
      color: i === 0 ? '#3B82F6' : i === 1 ? '#10B981' : '#F59E0B',
      scores: [
        getScore('accuracy'),
        getScore('completeness'),
        getScore('relevance'),
        getScore('citation')
      ]
    }
  })

  // Calculate points for a given score (0-10) on a given axis index
  const getPoint = (score: number, i: number) => {
    // Math.PI / 2 offset to start at the top
    const angle = angleSlice * i - Math.PI / 2
    // Scale score 0-10 to radius length
    const r = (Math.max(0, Math.min(10, score)) / 10) * radius
    return {
      x: cx + r * Math.cos(angle),
      y: cy + r * Math.sin(angle)
    }
  }

  return (
    <div className="flex flex-col items-center justify-center my-6 bg-white p-4 rounded border border-gray-200 shadow-sm max-w-lg mx-auto">
      <h3 className="text-sm font-semibold text-teter-dark mb-4 uppercase tracking-wide">Multi-Model Comparison</h3>
      <svg width={width} height={height} className="overflow-visible font-sans">
        {/* Background grid circles */}
        {[0.2, 0.4, 0.6, 0.8, 1.0].map((scale, i) => (
          <circle key={i} cx={cx} cy={cy} r={radius * scale} fill="none" stroke="#e5e7eb" strokeWidth="1" strokeDasharray={i === 4 ? "" : "4 4"} />
        ))}

        {/* Axis lines */}
        {axes.map((_, i) => {
          const p = getPoint(10, i)
          return <line key={i} x1={cx} y1={cy} x2={p.x} y2={p.y} stroke="#e5e7eb" strokeWidth="1" />
        })}

        {/* Axis labels */}
        {axes.map((_, i) => {
          const p = getPoint(12, i) // Push labels out a bit
          return (
            <text key={i} x={p.x} y={p.y} fontSize="11" fill="#6b7280" textAnchor="middle" dominantBaseline="middle" className="font-medium">
              {axisLabels[i]}
            </text>
          )
        })}

        {/* Polygons per model */}
        {modelData.map((m, mIndex) => {
          const points = m.scores.map((s, i) => getPoint(s, i))
          const pointsStr = points.map(p => `${p.x},${p.y}`).join(' ')
          return (
            <g key={mIndex}>
              <polygon points={pointsStr} fill={m.color} fillOpacity="0.15" stroke={m.color} strokeWidth="2" />
              {points.map((p, i) => (
                <circle key={i} cx={p.x} cy={p.y} r="4" fill={m.color} />
              ))}
            </g>
          )
        })}
      </svg>

      {/* Legend */}
      <div className="flex gap-4 mt-4">
        {modelData.map((m, i) => (
          <div key={i} className="flex items-center gap-1.5">
            <span className="w-3 h-3 rounded-full" style={{ backgroundColor: m.color }}></span>
            <span className="text-xs font-medium text-teter-dark">{m.name}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

export function DocumentAnalysisView() {
  const [file, setFile] = useState<File | null>(null)
  const [purpose, setPurpose] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<AnalyzeDocumentResponse | null>(null)
  const [activeTab, setActiveTab] = useState<Tab>('comparison')
  const [gradingSession, setGradingSession] = useState<GradingSession | null>(null)
  const [gradingLoading, setGradingLoading] = useState(false)

  const onDrop = useCallback((acceptedFiles: File[]) => {
    if (acceptedFiles.length > 0) {
      setFile(acceptedFiles[0])
      setError(null)
      setResult(null)
      setGradingSession(null)
    }
  }, [])

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: {
      'application/pdf': ['.pdf'],
      'application/vnd.openxmlformats-officedocument.wordprocessingml.document': ['.docx'],
      'text/plain': ['.txt'],
      'text/markdown': ['.md'],
    },
    maxFiles: 1,
  })

  const handleAnalyze = async () => {
    if (!file) return
    setLoading(true)
    setError(null)
    try {
      const response = await analyzeDocument(file, purpose || undefined)
      setResult(response)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Analysis failed')
    } finally {
      setLoading(false)
    }
  }

  const handleGrade = async () => {
    if (!result) return
    setGradingLoading(true)
    setError(null)
    try {
      const session = await gradeAnalysis(
        result.analysis.analysis_id,
        '', // Document content extracted by backend
        purpose || 'Construction document analysis',
      )
      setGradingSession(session)
      setActiveTab('grading')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Grading failed')
    } finally {
      setGradingLoading(false)
    }
  }

  return (
    <div className="max-w-wide mx-auto px-4 py-8">
      {/* Header */}
      <div className="mb-8">
        <h1 className="text-2xl font-semibold text-white mb-2">Document Analysis</h1>
        <p className="text-teter-gray-text">
          Analyze construction documents using multiple AI models with side-by-side comparison.
        </p>
      </div>

      {/* Upload Section */}
      <div className="bg-teter-card border border-white/8 rounded-xl p-6 mb-6">
        <div
          {...getRootProps()}
          className={`border-2 border-dashed rounded-lg p-8 text-center cursor-pointer transition-colors ${
            isDragActive
              ? 'border-teter-orange bg-teter-orange/5'
              : 'border-white/20 hover:border-white/40'
          }`}
        >
          <input {...getInputProps()} />
          <svg
            className="w-12 h-12 mx-auto mb-4 text-teter-gray-text"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={1.5}
              d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"
            />
          </svg>
          {file ? (
            <p className="text-white font-medium">{file.name}</p>
          ) : (
            <>
              <p className="text-white font-medium mb-1">
                {isDragActive ? 'Drop the document here' : 'Drag & drop a document'}
              </p>
              <p className="text-teter-gray-text text-sm">PDF, DOCX, TXT, or MD files supported</p>
            </>
          )}
        </div>

        {/* Purpose Input */}
        <div className="mt-4">
          <label className="block text-sm font-medium text-teter-gray-text mb-2">
            Analysis Purpose (optional)
          </label>
          <input
            type="text"
            value={purpose}
            onChange={(e) => setPurpose(e.target.value)}
            placeholder="e.g., Review RFI response for compliance"
            className="w-full bg-teter-dark border border-white/15 rounded-lg px-4 py-2 text-white placeholder-white/40 focus:border-teter-orange focus:outline-none"
          />
        </div>

        {/* Analyze Button */}
        <div className="mt-4 flex gap-3">
          <button
            onClick={handleAnalyze}
            disabled={!file || loading}
            className="px-6 py-2 bg-teter-orange text-white font-medium rounded-lg hover:bg-teter-orange-light disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {loading ? 'Analyzing...' : 'Analyze Document'}
          </button>
          {result && (
            <button
              onClick={handleGrade}
              disabled={gradingLoading}
              className="px-6 py-2 bg-green-600 text-white font-medium rounded-lg hover:bg-green-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {gradingLoading ? 'Grading...' : 'Run AI Grading'}
            </button>
          )}
        </div>
      </div>

      {/* Error Display */}
      {error && (
        <div className="bg-red-500/10 border border-red-500/30 text-red-400 rounded-lg px-4 py-3 mb-6">
          {error}
        </div>
      )}

      {/* Results Section */}
      {result && (
        <div className="bg-teter-card border border-white/8 rounded-xl overflow-hidden">
          {/* Tabs */}
          <div className="border-b border-white/8 flex">
            <TabButton
              active={activeTab === 'comparison'}
              onClick={() => setActiveTab('comparison')}
            >
              Side-by-Side Comparison
            </TabButton>
            <TabButton active={activeTab === 'raw'} onClick={() => setActiveTab('raw')}>
              Raw Analysis
            </TabButton>
            {gradingSession && (
              <TabButton active={activeTab === 'grading'} onClick={() => setActiveTab('grading')}>
                AI Grades
              </TabButton>
            )}
          </div>

          {/* Tab Content */}
          <div className="p-6">
            {activeTab === 'comparison' && (
              <ComparisonView columns={result.comparison_view.columns} />
            )}
            {activeTab === 'raw' && <RawAnalysisView analysis={result.analysis} />}
            {activeTab === 'grading' && gradingSession && (
              <GradingView session={gradingSession} />
            )}
          </div>
        </div>
      )}
    </div>
  )
}

function TabButton({
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
      className={`px-6 py-3 text-sm font-medium transition-colors ${
        active
          ? 'text-teter-orange border-b-2 border-teter-orange bg-white/5'
          : 'text-teter-gray-text hover:text-white'
      }`}
    >
      {children}
    </button>
  )
}

function ComparisonView({ columns }: { columns: ComparisonColumn[] }) {
  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
      {columns.map((col, idx) => (
        <div
          key={idx}
          className={`bg-teter-dark border rounded-lg p-4 ${
            col.status === 'SUCCESS' ? 'border-white/10' : 'border-red-500/30'
          }`}
        >
          {/* Header */}
          <div className="flex items-center justify-between mb-4">
            <div>
              <span className="text-xs text-teter-gray-text uppercase tracking-wide">
                Tier {col.tier}
              </span>
              <h3 className="text-white font-medium">{col.model_name}</h3>
              <span className="text-xs text-teter-gray-text">{col.provider}</span>
            </div>
            <StatusBadge status={col.status} />
          </div>

          {col.status === 'SUCCESS' ? (
            <>
              {/* Confidence */}
              {col.confidence !== undefined && (
                <div className="mb-4">
                  <span className="text-xs text-teter-gray-text">Confidence</span>
                  <ConfidenceMeter score={col.confidence} />
                </div>
              )}

              {/* Latency */}
              {col.latency_ms && (
                <div className="text-xs text-teter-gray-text mb-4">
                  Latency: {(col.latency_ms / 1000).toFixed(2)}s
                </div>
              )}

              {/* Summary */}
              {col.summary && (
                <div className="mb-4">
                  <h4 className="text-sm font-medium text-white mb-1">Summary</h4>
                  <p className="text-sm text-teter-gray-text">{col.summary}</p>
                </div>
              )}

              {/* Key Findings */}
              {col.key_findings && col.key_findings.length > 0 && (
                <div className="mb-4">
                  <h4 className="text-sm font-medium text-white mb-2">Key Findings</h4>
                  <ul className="space-y-1">
                    {col.key_findings.map((finding, i) => (
                      <li key={i} className="text-sm text-teter-gray-text flex items-start gap-2">
                        <span className="text-teter-orange mt-1">•</span>
                        {finding}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {/* Recommendations */}
              {col.recommendations && col.recommendations.length > 0 && (
                <div>
                  <h4 className="text-sm font-medium text-white mb-2">Recommendations</h4>
                  <ul className="space-y-1">
                    {col.recommendations.map((rec, i) => (
                      <li key={i} className="text-sm text-teter-gray-text flex items-start gap-2">
                        <span className="text-green-500 mt-1">→</span>
                        {rec}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </>
          ) : (
            <div className="text-red-400 text-sm">{col.error || 'Analysis failed'}</div>
          )}
        </div>
      ))}
    </div>
  )
}

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    SUCCESS: 'bg-green-500/20 text-green-400',
    FAILED: 'bg-red-500/20 text-red-400',
    TIMEOUT: 'bg-yellow-500/20 text-yellow-400',
    RATE_LIMITED: 'bg-orange-500/20 text-orange-400',
  }

  return (
    <span className={`px-2 py-1 rounded text-xs font-medium ${colors[status] || colors.FAILED}`}>
      {status}
    </span>
  )
}

function RawAnalysisView({ analysis }: { analysis: MultiModelAnalysisResult }) {
  return (
    <div className="space-y-4">
      <div className="text-sm text-teter-gray-text">
        <p>
          <strong>Analysis ID:</strong> {analysis.analysis_id}
        </p>
        <p>
          <strong>Document:</strong> {analysis.document_name || 'N/A'}
        </p>
        <p>
          <strong>Total Latency:</strong> {((analysis.total_latency_ms || 0) / 1000).toFixed(2)}s
        </p>
        <p>
          <strong>Successful Models:</strong> {analysis.successful_models || 0}/3
        </p>
      </div>

      <pre className="bg-teter-dark rounded-lg p-4 overflow-x-auto text-xs text-teter-gray-text">
        {JSON.stringify(analysis, null, 2)}
      </pre>
    </div>
  )
}

function GradingView({ session }: { session: GradingSession }) {
  const grades = Object.values(session.ai_grades)

  return (
    <div className="space-y-6">
      <div className="text-sm text-teter-gray-text mb-4">
        <p>
          <strong>Session ID:</strong> {session.session_id}
        </p>
        <p>
          <strong>Status:</strong>{' '}
          <span className="text-teter-orange capitalize">{session.status}</span>
        </p>
      </div>

      {grades.map((grade) => (
        <div key={grade.grade_id} className="bg-teter-dark border border-white/10 rounded-lg p-4">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h3 className="text-white font-medium">{grade.model_name}</h3>
              <span className="text-xs text-teter-gray-text">Tier {grade.tier}</span>
            </div>
            <div className="text-2xl font-bold text-teter-orange">
              {grade.overall_score.toFixed(1)}/10
            </div>
          </div>

          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <ScoreCard label="Accuracy" score={grade.accuracy} />
            <ScoreCard label="Completeness" score={grade.completeness} />
            <ScoreCard label="Relevance" score={grade.relevance} />
            <ScoreCard label="Citation Quality" score={grade.citation_quality} />
          </div>
        </div>
      ))}

      {grades.length === 0 && (
        <p className="text-teter-gray-text text-center py-8">No grades available yet.</p>
      )}
    </div>
  )
}

function ScoreCard({
  label,
  score,
}: {
  label: string
  score: { score: number; reasoning: string }
}) {
  const colorClass =
    score.score >= 8
      ? 'text-green-400'
      : score.score >= 6
        ? 'text-yellow-400'
        : score.score >= 4
          ? 'text-orange-400'
          : 'text-red-400'

  return (
    <div className="bg-white/5 rounded-lg p-3">
      <div className="text-xs text-teter-gray-text mb-1">{label}</div>
      <div className={`text-xl font-bold ${colorClass}`}>{score.score.toFixed(1)}</div>
      <p className="text-xs text-teter-gray-text mt-1 line-clamp-2" title={score.reasoning}>
        {score.reasoning}
      </p>
    </div>
  )
}
