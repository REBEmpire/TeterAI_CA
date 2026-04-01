/**
 * ProjectIntelligenceView — dashboard surfacing Neo4j KG data as KPIs,
 * charts, a party table, and an AI-generated project health narrative.
 *
 * Phase E feature — uses inline SVG for charts (no extra npm packages).
 */
import { useEffect, useState } from 'react'
import {
  listProjects,
  getProjectIntelligence,
  getPartyNetwork,
  getDocumentTimeline,
  compareProjects,
  generateAISummary,
} from '../api/client'
import type {
  ProjectIntelligence,
  PartyEntry,
  TimelineMonth,
  CrossProjectEntry,
  AINarrative,
} from '../api/client'
import type { ProjectSummary } from '../types'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function rateColor(rate: number): string {
  if (rate >= 0.7) return '#16a34a'   // green
  if (rate >= 0.5) return '#d97706'   // amber
  return '#dc2626'                    // red
}

function pct(v: number): string {
  return `${Math.round(v * 100)}%`
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function KpiCard({
  label,
  value,
  color,
  sub,
}: {
  label: string
  value: string | number
  color?: string
  sub?: string
}) {
  return (
    <div className="card flex flex-col gap-1 min-w-[140px]">
      <span className="text-xs text-teter-gray-text font-medium uppercase tracking-wide">
        {label}
      </span>
      <span
        className="text-3xl font-bold"
        style={{ color: color ?? '#d06f1a' }}
      >
        {value}
      </span>
      {sub && <span className="text-xs text-teter-gray-text">{sub}</span>}
    </div>
  )
}

function DocTypeBarChart({ counts }: { counts: Record<string, number> }) {
  const entries = Object.entries(counts).sort((a, b) => b[1] - a[1])
  if (entries.length === 0) return <p className="text-sm text-teter-gray-text">No data.</p>

  const max = Math.max(...entries.map(([, v]) => v), 1)
  const barH = 24
  const gap = 6
  const labelW = 148
  const chartW = 280
  const totalH = entries.length * (barH + gap)

  return (
    <svg
      width={labelW + chartW + 56}
      height={totalH}
      className="overflow-visible"
      aria-label="Documents by type bar chart"
    >
      {entries.map(([type, count], i) => {
        const y = i * (barH + gap)
        const barW = Math.max((count / max) * chartW, 2)
        return (
          <g key={type} transform={`translate(0,${y})`}>
            <text
              x={labelW - 8}
              y={barH / 2 + 5}
              textAnchor="end"
              style={{ fill: '#6b6b6b', fontSize: 12, fontFamily: 'Inter, sans-serif' }}
            >
              {type}
            </text>
            <rect x={labelW} y={0} width={barW} height={barH} rx={3} fill="#d06f1a" />
            <text
              x={labelW + barW + 6}
              y={barH / 2 + 5}
              style={{ fill: '#1a1a2e', fontSize: 12, fontWeight: 'bold', fontFamily: 'Inter, sans-serif' }}
            >
              {count}
            </text>
          </g>
        )
      })}
    </svg>
  )
}

function TimelineChart({ months }: { months: TimelineMonth[] }) {
  if (months.length === 0) return <p className="text-sm text-teter-gray-text">No timeline data.</p>

  const totals = months.map((m) => Object.values(m.counts).reduce((s, v) => s + v, 0))
  const maxVal = Math.max(...totals, 1)

  const W = 560
  const H = 140
  const padL = 40
  const padR = 16
  const padT = 12
  const padB = 32
  const innerW = W - padL - padR
  const innerH = H - padT - padB

  const pts = months.map((_, i) => {
    const x = padL + (i / Math.max(months.length - 1, 1)) * innerW
    const y = padT + innerH - (totals[i] / maxVal) * innerH
    return { x, y }
  })

  const polyline = pts.map((p) => `${p.x},${p.y}`).join(' ')
  const area = [
    `${pts[0].x},${padT + innerH}`,
    ...pts.map((p) => `${p.x},${p.y}`),
    `${pts[pts.length - 1].x},${padT + innerH}`,
  ].join(' ')

  // Y-axis tick at max and mid
  const yTicks = [
    { val: maxVal, y: padT },
    { val: Math.round(maxVal / 2), y: padT + innerH / 2 },
    { val: 0, y: padT + innerH },
  ]

  // X-axis labels — show every Nth label to avoid crowding
  const every = Math.ceil(months.length / 8)

  return (
    <svg width={W} height={H} aria-label="Document submission timeline chart">
      {/* Y grid lines */}
      {yTicks.map((t) => (
        <line
          key={t.val}
          x1={padL}
          y1={t.y}
          x2={padL + innerW}
          y2={t.y}
          stroke="#e5e7eb"
          strokeWidth={1}
        />
      ))}
      {/* Y labels */}
      {yTicks.map((t) => (
        <text
          key={t.val}
          x={padL - 6}
          y={t.y + 4}
          textAnchor="end"
          style={{ fill: '#9ca3af', fontSize: 10, fontFamily: 'Inter, sans-serif' }}
        >
          {t.val}
        </text>
      ))}
      {/* Area fill */}
      <polygon points={area} fill="#d06f1a" opacity={0.12} />
      {/* Line */}
      <polyline
        points={polyline}
        fill="none"
        stroke="#d06f1a"
        strokeWidth={2}
        strokeLinejoin="round"
      />
      {/* Dots */}
      {pts.map((p, i) => (
        <circle key={i} cx={p.x} cy={p.y} r={3} fill="#d06f1a">
          <title>{`${months[i].month}: ${totals[i]} docs`}</title>
        </circle>
      ))}
      {/* X labels */}
      {months.map((m, i) =>
        i % every === 0 ? (
          <text
            key={m.month}
            x={pts[i].x}
            y={H - 6}
            textAnchor="middle"
            style={{ fill: '#9ca3af', fontSize: 9, fontFamily: 'Inter, sans-serif' }}
          >
            {m.month}
          </text>
        ) : null,
      )}
    </svg>
  )
}

function PartyTable({ parties }: { parties: PartyEntry[] }) {
  if (parties.length === 0) {
    return <p className="text-sm text-teter-gray-text">No party data available.</p>
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-gray-200">
            <th className="text-left py-2 pr-4 text-xs font-semibold text-teter-gray-text uppercase tracking-wide">
              Party
            </th>
            <th className="text-left py-2 pr-4 text-xs font-semibold text-teter-gray-text uppercase tracking-wide">
              Type
            </th>
            <th className="text-right py-2 pr-4 text-xs font-semibold text-teter-gray-text uppercase tracking-wide">
              Total Docs
            </th>
            <th className="text-left py-2 text-xs font-semibold text-teter-gray-text uppercase tracking-wide">
              Primary Doc Type
            </th>
          </tr>
        </thead>
        <tbody>
          {parties.map((p) => {
            const topSub = [...p.submissions].sort((a, b) => b.count - a.count)[0]
            return (
              <tr key={p.party_id} className="border-b border-gray-100 hover:bg-gray-50">
                <td className="py-2 pr-4 font-medium text-teter-dark">{p.name}</td>
                <td className="py-2 pr-4 text-teter-gray-text capitalize">{p.type}</td>
                <td className="py-2 pr-4 text-right font-semibold text-teter-orange">
                  {p.total_submissions}
                </td>
                <td className="py-2 text-teter-gray-text">{topSub?.doc_type ?? '—'}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function NarrativeSection({ label, text }: { label: string; text: string }) {
  if (!text) return null
  return (
    <div className="mb-4">
      <h4 className="text-xs font-semibold uppercase tracking-wider text-teter-gray-text mb-1">
        {label}
      </h4>
      <p className="text-sm text-teter-dark leading-relaxed">{text}</p>
    </div>
  )
}

const NARRATIVE_LABELS: Record<keyof AINarrative, string> = {
  overview:        'Project Overview',
  document_status: 'Document Status',
  key_parties:     'Key Parties',
  risk_flags:      'Risk Flags',
  recommendations: 'Recommendations',
}

function CompareGrid({ projects }: { projects: CrossProjectEntry[] }) {
  if (projects.length === 0) {
    return <p className="text-sm text-teter-gray-text">No project data available.</p>
  }
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
      {projects.map((p) => (
        <div key={p.project_id} className="card flex flex-col gap-2">
          <div className="flex items-start justify-between gap-2">
            <div>
              <span className="text-xs font-bold text-teter-gray-text">
                {p.project_number || p.project_id}
              </span>
              <p className="text-sm font-semibold text-teter-dark leading-tight mt-0.5">
                {p.name || p.project_id}
              </p>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-2 mt-1">
            <div>
              <span className="text-xs text-teter-gray-text">Total Docs</span>
              <p className="text-xl font-bold text-teter-orange">{p.total_docs}</p>
            </div>
            <div>
              <span className="text-xs text-teter-gray-text">Response Rate</span>
              <p
                className="text-xl font-bold"
                style={{ color: rateColor(p.response_rate) }}
              >
                {pct(p.response_rate)}
              </p>
            </div>
            <div>
              <span className="text-xs text-teter-gray-text">Parties</span>
              <p className="text-lg font-semibold text-teter-dark">{p.party_count}</p>
            </div>
            <div>
              <span className="text-xs text-teter-gray-text">Metadata Only</span>
              <p className="text-lg font-semibold text-teter-dark">
                {p.metadata_only_count}
              </p>
            </div>
          </div>
        </div>
      ))}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main view
// ---------------------------------------------------------------------------

export function ProjectIntelligenceView() {
  const [projects, setProjects] = useState<ProjectSummary[]>([])
  const [selectedProject, setSelectedProject] = useState('')

  const [intel, setIntel] = useState<ProjectIntelligence | null>(null)
  const [parties, setParties] = useState<PartyEntry[]>([])
  const [timeline, setTimeline] = useState<TimelineMonth[]>([])

  const [compareMode, setCompareMode] = useState(false)
  const [comparison, setComparison] = useState<CrossProjectEntry[]>([])

  const [narrative, setNarrative] = useState<AINarrative | null>(null)
  const [generating, setGenerating] = useState(false)
  const [narrativeError, setNarrativeError] = useState<string | null>(null)

  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Load project list
  useEffect(() => {
    listProjects().then(setProjects).catch(() => {})
  }, [])

  // Auto-select first project
  useEffect(() => {
    if (projects.length > 0 && !selectedProject) {
      setSelectedProject(projects[0].project_id)
    }
  }, [projects, selectedProject])

  // Load single-project data
  useEffect(() => {
    if (!selectedProject || compareMode) return
    setLoading(true)
    setError(null)
    setNarrative(null)
    setNarrativeError(null)

    Promise.all([
      getProjectIntelligence(selectedProject),
      getPartyNetwork(selectedProject),
      getDocumentTimeline(selectedProject),
    ])
      .then(([i, p, t]) => {
        setIntel(i)
        setParties(p.parties)
        setTimeline(t.months)
      })
      .catch((err) => setError(err.message ?? 'Failed to load project data.'))
      .finally(() => setLoading(false))
  }, [selectedProject, compareMode])

  // Load cross-project comparison
  useEffect(() => {
    if (!compareMode) return
    compareProjects()
      .then((data) => setComparison(data.projects))
      .catch((err) => setError(err.message ?? 'Failed to load comparison data.'))
  }, [compareMode])

  async function handleGenerateSummary() {
    if (!selectedProject) return
    setGenerating(true)
    setNarrativeError(null)
    try {
      const result = await generateAISummary(selectedProject)
      setNarrative(result.narrative)
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to generate summary.'
      setNarrativeError(msg)
    } finally {
      setGenerating(false)
    }
  }

  const rfiCount = intel?.doc_counts_by_type?.['RFI'] ?? 0

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div className="flex flex-col min-h-screen bg-gray-50">
      {/* Page header */}
      <div className="bg-white border-b border-gray-200 px-6 py-4 shrink-0">
        <div className="max-w-wide mx-auto">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h1 className="text-xl font-semibold text-teter-dark">Project Intelligence</h1>
              <p className="text-sm text-teter-gray-text mt-0.5">
                KG-powered insights from ingested CA documents
              </p>
            </div>
            <div className="hidden sm:block w-1 h-8 bg-teter-orange rounded-sm" />
          </div>

          {/* Control bar */}
          <div className="flex flex-wrap items-end gap-3">
            {/* Project selector */}
            <div className="flex flex-col gap-1">
              <label className="text-xs text-teter-gray-text font-medium">Project</label>
              <select
                className="select"
                value={selectedProject}
                onChange={(e) => {
                  setSelectedProject(e.target.value)
                  setCompareMode(false)
                }}
                aria-label="Select project"
                disabled={compareMode}
              >
                <option value="">Select project…</option>
                {projects.map((p) => (
                  <option key={p.project_id} value={p.project_id}>
                    {p.project_number} — {p.name}
                  </option>
                ))}
              </select>
            </div>

            {/* Compare toggle */}
            <button
              onClick={() => setCompareMode((v) => !v)}
              className={`px-4 py-2 text-sm font-semibold rounded border transition-colors ${
                compareMode
                  ? 'bg-teter-dark text-white border-teter-dark'
                  : 'bg-white border-gray-200 text-teter-dark hover:bg-gray-50'
              }`}
            >
              {compareMode ? '✓ ' : ''}Compare All Projects
            </button>
          </div>
        </div>
      </div>

      {/* Body */}
      <div className="flex-1 px-6 py-6">
        <div className="max-w-wide mx-auto space-y-6">
          {/* Loading */}
          {loading && (
            <div className="flex items-center gap-3 text-teter-gray-text">
              <div className="w-5 h-5 border-2 border-teter-orange border-t-transparent rounded-full animate-spin" />
              <span className="text-sm">Loading project data…</span>
            </div>
          )}

          {/* Error */}
          {error && (
            <div className="bg-red-50 border border-red-200 rounded-lg px-4 py-3 text-sm text-red-700">
              {error}
            </div>
          )}

          {/* ---- Compare mode ---- */}
          {compareMode && (
            <section>
              <h2 className="text-base font-semibold text-teter-dark mb-3">
                All Projects — Side-by-Side
              </h2>
              <CompareGrid projects={comparison} />
            </section>
          )}

          {/* ---- Single project mode ---- */}
          {!compareMode && intel && (
            <>
              {/* KPI cards */}
              <section>
                <h2 className="text-base font-semibold text-teter-dark mb-3">
                  Project KPIs
                </h2>
                <div className="flex flex-wrap gap-4">
                  <KpiCard
                    label="Total Documents"
                    value={intel.total_docs}
                    sub={`${intel.earliest_date ?? '?'} – ${intel.latest_date ?? '?'}`}
                  />
                  <KpiCard
                    label="RFIs"
                    value={rfiCount}
                    sub={`${intel.doc_counts_by_type?.['SUBMITTAL'] ?? 0} submittals`}
                  />
                  <KpiCard
                    label="Response Rate"
                    value={pct(intel.response_rate)}
                    color={rateColor(intel.response_rate)}
                    sub={`${intel.responded_docs} of ${intel.total_docs} responded`}
                  />
                  <KpiCard
                    label="Parties Involved"
                    value={intel.party_count}
                    sub={`${intel.metadata_only_count} docs metadata-only`}
                  />
                </div>
              </section>

              {/* Bar chart + Timeline side by side */}
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                <section className="card">
                  <h2 className="text-base font-semibold text-teter-dark mb-4">
                    Documents by Type
                  </h2>
                  <DocTypeBarChart counts={intel.doc_counts_by_type} />
                </section>

                <section className="card">
                  <h2 className="text-base font-semibold text-teter-dark mb-4">
                    Submission Timeline
                  </h2>
                  <TimelineChart months={timeline} />
                </section>
              </div>

              {/* Party table */}
              <section className="card">
                <h2 className="text-base font-semibold text-teter-dark mb-4">
                  Submitting Parties
                </h2>
                <PartyTable parties={parties} />
              </section>

              {/* AI Narrative */}
              <section className="card">
                <div className="flex items-center justify-between mb-4">
                  <h2 className="text-base font-semibold text-teter-dark">
                    AI Project Health Narrative
                  </h2>
                  <button
                    className="btn-primary text-sm"
                    onClick={handleGenerateSummary}
                    disabled={generating || !selectedProject}
                  >
                    {generating ? (
                      <span className="flex items-center gap-2">
                        <span className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                        Generating…
                      </span>
                    ) : (
                      'Generate Project Summary'
                    )}
                  </button>
                </div>

                {narrativeError && (
                  <p className="text-sm text-red-600 mb-3">{narrativeError}</p>
                )}

                {!narrative && !generating && (
                  <p className="text-sm text-teter-gray-text">
                    Click "Generate Project Summary" to have AI analyze the KG data and
                    produce a structured project health narrative.
                  </p>
                )}

                {narrative && (
                  <div>
                    {(Object.keys(NARRATIVE_LABELS) as Array<keyof AINarrative>).map((key) => (
                      <NarrativeSection
                        key={key}
                        label={NARRATIVE_LABELS[key]}
                        text={narrative[key]}
                      />
                    ))}
                  </div>
                )}
              </section>
            </>
          )}

          {/* Empty state */}
          {!compareMode && !loading && !error && !intel && (
            <div className="text-center py-16 text-teter-gray-text">
              <svg
                className="mx-auto mb-3 opacity-30"
                width="48"
                height="48"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
                strokeWidth={1.5}
              >
                <rect x="3" y="12" width="4" height="9" rx="1" />
                <rect x="10" y="7" width="4" height="14" rx="1" />
                <rect x="17" y="3" width="4" height="18" rx="1" />
              </svg>
              <p className="font-semibold">Select a project to view intelligence data</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
