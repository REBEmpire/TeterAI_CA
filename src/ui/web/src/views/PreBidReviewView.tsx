/**
 * PreBidReviewView — mine completed-project RFI / Change Order history from
 * the Neo4j Knowledge Graph to identify design issues before a project goes
 * to bid.  Uses the POST /api/v1/prebid-lessons endpoint.
 */
import { useEffect, useState } from 'react'
import { listProjects, getPreBidLessons } from '../api/client'
import type { PreBidSimilarDoc, PreBidChecklist, PreBidLessonsResponse } from '../api/client'
import type { ProjectSummary } from '../types'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function scoreColor(score: number): string {
  if (score >= 0.85) return '#dc2626'   // red  — very high relevance / risk
  if (score >= 0.75) return '#d97706'   // amber
  return '#16a34a'                      // green — lower similarity
}

function scoreLabel(score: number): string {
  if (score >= 0.85) return 'High Match'
  if (score >= 0.75) return 'Medium Match'
  return 'Low Match'
}

/** Split a newline-delimited string into list items, stripping bullet chars. */
function toLines(text: string): string[] {
  return text
    .split('\n')
    .map(l => l.replace(/^[\s\-•*]+/, '').trim())
    .filter(Boolean)
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function SectionCard({ title, content, accent }: { title: string; content: string; accent?: boolean }) {
  const lines = toLines(content)
  return (
    <div className={`card ${accent ? 'border-l-4 border-teter-orange' : ''}`}>
      <h3 className="text-sm font-semibold text-teter-orange uppercase tracking-wide mb-2">
        {title}
      </h3>
      {lines.length > 1 ? (
        <ul className="space-y-1 list-disc list-inside text-sm text-teter-gray-text">
          {lines.map((l, i) => <li key={i}>{l}</li>)}
        </ul>
      ) : (
        <p className="text-sm text-teter-gray-text">{content}</p>
      )}
    </div>
  )
}

function DocTypeBar({ counts }: { counts: Record<string, number> }) {
  const entries = Object.entries(counts).sort((a, b) => b[1] - a[1])
  if (!entries.length) return null
  const max = entries[0][1]
  return (
    <div className="card">
      <h3 className="text-sm font-semibold text-teter-gray-text uppercase tracking-wide mb-3">
        Issue Volume by Type
      </h3>
      <svg width="100%" height={entries.length * 28 + 8} role="img" aria-label="Issue volume by type">
        {entries.map(([type, count], i) => {
          const barWidth = max > 0 ? (count / max) * 65 : 0   // 65% of total width for bar
          const y = i * 28 + 4
          return (
            <g key={type}>
              <text
                x={0} y={y + 14}
                style={{ fill: '#6b6b6b', fontSize: 12, fontFamily: 'inherit' }}
              >
                {type}
              </text>
              <rect
                x="22%" y={y + 3}
                width={`${barWidth}%`} height={16}
                rx={3}
                fill="#d06f1a"
                opacity={0.85}
              />
              <text
                x="89%" y={y + 14}
                style={{ fill: '#6b6b6b', fontSize: 12, fontFamily: 'inherit' }}
                textAnchor="end"
              >
                {count}
              </text>
            </g>
          )
        })}
      </svg>
    </div>
  )
}

function SimilarDocRow({ doc }: { doc: PreBidSimilarDoc }) {
  const [expanded, setExpanded] = useState(false)
  const summary = doc.summary?.trim() || 'No summary available.'
  const short = summary.length > 180 ? summary.slice(0, 180) + '…' : summary
  const color = scoreColor(doc.score)
  const label = scoreLabel(doc.score)

  return (
    <div className="card mb-2 text-sm">
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap mb-1">
            <span className="text-xs font-semibold px-2 py-0.5 rounded bg-teter-orange/15 text-teter-orange uppercase">
              {doc.doc_type}
            </span>
            {doc.doc_number && (
              <span className="text-xs text-teter-gray-text font-medium"># {doc.doc_number}</span>
            )}
            <span className="text-xs text-teter-gray-text">
              {doc.project_name || doc.project_id}
              {doc.project_number ? ` (${doc.project_number})` : ''}
            </span>
            {doc.date_submitted && (
              <span className="text-xs text-teter-gray-text opacity-70">{doc.date_submitted.slice(0, 10)}</span>
            )}
          </div>
          <p className="text-teter-gray-text leading-snug">
            {expanded ? summary : short}
            {!expanded && summary.length > 180 && (
              <button
                onClick={() => setExpanded(true)}
                className="ml-1 text-teter-orange underline text-xs"
              >
                more
              </button>
            )}
          </p>
        </div>
        <div className="flex flex-col items-end shrink-0 gap-1 min-w-[80px]">
          <span className="text-xs font-semibold" style={{ color }}>
            {label}
          </span>
          <span className="text-xs text-teter-gray-text opacity-60">
            {Math.round(doc.score * 100)}%
          </span>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main view
// ---------------------------------------------------------------------------

export function PreBidReviewView() {
  const [projects, setProjects] = useState<ProjectSummary[]>([])
  const [selectedSources, setSelectedSources] = useState<string[]>([])
  const [queryText, setQueryText] = useState('')
  const [result, setResult] = useState<PreBidLessonsResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [projectsLoading, setProjectsLoading] = useState(true)

  // Load project list
  useEffect(() => {
    listProjects()
      .then(setProjects)
      .catch(() => setProjects([]))
      .finally(() => setProjectsLoading(false))
  }, [])

  function toggleSource(projectId: string) {
    setSelectedSources(prev =>
      prev.includes(projectId) ? prev.filter(id => id !== projectId) : [...prev, projectId]
    )
  }

  async function handleRun() {
    if (!queryText.trim()) {
      setError('Please enter a design concern or topic to search.')
      return
    }
    if (selectedSources.length === 0) {
      setError('Select at least one historical project to mine for lessons.')
      return
    }
    setError(null)
    setLoading(true)
    setResult(null)
    try {
      const res = await getPreBidLessons(queryText, selectedSources)
      setResult(res)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Request failed.')
    } finally {
      setLoading(false)
    }
  }

  const hasSimilarDocs = (result?.similar_docs ?? []).length > 0
  const hasDocTypeCounts = Object.keys(result?.doc_type_counts ?? {}).length > 0

  return (
    <div className="max-w-wide mx-auto px-4 py-6 space-y-6">

      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-white">Pre-Bid Lessons Learned</h1>
        <p className="text-sm text-teter-gray-text mt-1">
          Mine historical RFI and Change Order patterns from completed projects to identify
          design issues you can eliminate before going to bid.
        </p>
      </div>

      {/* Input panel */}
      <div className="card space-y-4">

        {/* Design concern */}
        <div>
          <label className="block text-sm font-semibold text-white mb-1">
            Describe the design concern or topic
          </label>
          <textarea
            rows={3}
            value={queryText}
            onChange={e => setQueryText(e.target.value)}
            placeholder="e.g. exterior waterproofing and flashing details at windows, or structural steel connections at cantilever, or mechanical room coordination with structure…"
            className="w-full rounded border border-white/10 bg-white/5 text-white placeholder-white/30
                       text-sm px-3 py-2 focus:outline-none focus:ring-2 focus:ring-teter-orange/60 resize-none"
          />
        </div>

        {/* Source project selector */}
        <div>
          <label className="block text-sm font-semibold text-white mb-1">
            Select historical projects to mine{' '}
            <span className="text-white/40 font-normal">(completed CA projects)</span>
          </label>
          {projectsLoading ? (
            <p className="text-xs text-white/40">Loading projects…</p>
          ) : projects.length === 0 ? (
            <p className="text-xs text-white/40">No projects found.</p>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-2 mt-1">
              {projects.map(p => {
                const selected = selectedSources.includes(p.project_id)
                return (
                  <button
                    key={p.id}
                    type="button"
                    onClick={() => toggleSource(p.project_id)}
                    className={`flex items-center gap-2 px-3 py-2 rounded border text-sm text-left transition-colors
                      ${selected
                        ? 'border-teter-orange bg-teter-orange/10 text-white'
                        : 'border-white/10 bg-white/5 text-white/60 hover:border-white/30 hover:text-white/80'
                      }`}
                  >
                    {/* Checkbox indicator */}
                    <span className={`w-4 h-4 shrink-0 rounded border flex items-center justify-center
                      ${selected ? 'border-teter-orange bg-teter-orange' : 'border-white/30'}`}>
                      {selected && (
                        <svg className="w-2.5 h-2.5" fill="none" viewBox="0 0 10 10" stroke="white" strokeWidth={2}>
                          <path strokeLinecap="round" strokeLinejoin="round" d="M1.5 5l2.5 2.5 4.5-4.5" />
                        </svg>
                      )}
                    </span>
                    <span className="truncate">
                      {p.name}
                      <span className="block text-xs opacity-50">{p.project_number || p.project_id}</span>
                    </span>
                  </button>
                )
              })}
            </div>
          )}
        </div>

        {/* Run button */}
        <div className="flex items-center gap-4">
          <button
            onClick={handleRun}
            disabled={loading}
            className="btn-primary flex items-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {loading ? (
              <>
                <svg className="animate-spin h-4 w-4 shrink-0" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor"
                    d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
                Analysing…
              </>
            ) : (
              <>
                {/* Magnifying glass + document icon */}
                <svg className="h-4 w-4 shrink-0" fill="none" viewBox="0 0 24 24"
                  stroke="currentColor" strokeWidth={2} aria-hidden="true">
                  <path strokeLinecap="round" strokeLinejoin="round"
                    d="M21 21l-4.35-4.35M17 11A6 6 0 1 1 5 11a6 6 0 0 1 12 0z" />
                </svg>
                Run Pre-Bid Review
              </>
            )}
          </button>
          {selectedSources.length > 0 && (
            <span className="text-xs text-white/50">
              {selectedSources.length} project{selectedSources.length !== 1 ? 's' : ''} selected
            </span>
          )}
        </div>

        {error && (
          <p className="text-sm text-red-400">{error}</p>
        )}
      </div>

      {/* Results */}
      {result && (
        <>
          {/* Meta bar */}
          <div className="flex items-center gap-4 text-xs text-white/40 flex-wrap">
            <span>
              {result.similar_docs.length} historically similar doc{result.similar_docs.length !== 1 ? 's' : ''} found
            </span>
            <span>·</span>
            <span>Analysis by {result.model_used} (tier {result.tier_used})</span>
            <span>·</span>
            <span>{new Date(result.generated_at).toLocaleString()}</span>
          </div>

          {/* AI Checklist sections */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <SectionCard
              title="Historical Pattern Summary"
              content={result.checklist.summary}
              accent
            />
            <SectionCard
              title="Design Risks to Address"
              content={result.checklist.design_risks}
              accent
            />
            <SectionCard
              title="Spec Sections / Details to Clarify"
              content={result.checklist.spec_sections_to_clarify}
            />
            <SectionCard
              title="Pre-Bid Action Checklist"
              content={result.checklist.bid_checklist}
              accent
            />
          </div>

          {/* Volume chart + similar docs side-by-side on wider screens */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            {hasDocTypeCounts && (
              <div className="lg:col-span-1">
                <DocTypeBar counts={result.doc_type_counts} />
              </div>
            )}

            {/* Similar docs list */}
            {hasSimilarDocs && (
              <div className={hasDocTypeCounts ? 'lg:col-span-2' : 'lg:col-span-3'}>
                <div className="card">
                  <h3 className="text-sm font-semibold text-teter-gray-text uppercase tracking-wide mb-3">
                    Semantically Similar Historical Issues ({result.similar_docs.length})
                  </h3>
                  <p className="text-xs text-white/40 mb-3">
                    Ranked by semantic similarity to your design concern. High-match items represent
                    issues that occurred in similar situations on past projects.
                  </p>
                  <div className="max-h-[480px] overflow-y-auto pr-1 space-y-0">
                    {result.similar_docs.map(doc => (
                      <SimilarDocRow key={doc.doc_id} doc={doc} />
                    ))}
                  </div>
                </div>
              </div>
            )}

            {!hasSimilarDocs && (
              <div className="lg:col-span-2">
                <div className="card text-center py-8">
                  <p className="text-sm text-white/40">
                    No semantically similar documents found in the selected projects for this topic.
                    Try broadening your query or selecting more source projects.
                  </p>
                </div>
              </div>
            )}
          </div>
        </>
      )}

      {/* Empty state before first run */}
      {!result && !loading && (
        <div className="card text-center py-12">
          <svg
            className="mx-auto h-12 w-12 text-white/10 mb-4"
            fill="none" viewBox="0 0 48 48"
            stroke="currentColor" strokeWidth={1.5}
            aria-hidden="true"
          >
            {/* Clipboard with magnifier */}
            <rect x="10" y="4" width="28" height="36" rx="3" />
            <path strokeLinecap="round" d="M17 14h14M17 20h10" />
            <circle cx="33" cy="36" r="7" />
            <path strokeLinecap="round" d="M38.5 41.5l3 3" />
          </svg>
          <p className="text-sm text-white/40 max-w-sm mx-auto">
            Select completed projects above, describe your design concern, and run the review
            to surface historical RFI and Change Order patterns that could affect your new design.
          </p>
        </div>
      )}
    </div>
  )
}
