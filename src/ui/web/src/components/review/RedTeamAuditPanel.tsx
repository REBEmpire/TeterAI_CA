import { useEffect, useState } from 'react'
import { getRedTeamAudit } from '../../api/client'
import type { CritiqueItem, RedTeamAuditData } from '../../types'

// ---------------------------------------------------------------------------
// Severity helpers
// ---------------------------------------------------------------------------

type Severity = CritiqueItem['severity']

function severityClasses(severity: Severity): { row: string; badge: string } {
  switch (severity) {
    case 'AGREE':
      return { row: 'bg-green-50', badge: 'bg-green-50 text-green-700' }
    case 'MINOR_REVISION':
      return { row: 'bg-yellow-50', badge: 'bg-yellow-50 text-yellow-700' }
    case 'MAJOR_REVISION':
      return { row: 'bg-orange-50', badge: 'bg-orange-50 text-orange-700' }
    case 'REJECT':
      return { row: 'bg-red-50', badge: 'bg-red-50 text-red-700' }
    default:
      return { row: '', badge: 'bg-gray-100 text-gray-600' }
  }
}

function SeverityBadge({ severity }: { severity: Severity }) {
  const { badge } = severityClasses(severity)
  const label = severity.replace(/_/g, ' ')
  return (
    <span className={`inline-block px-1.5 py-0.5 rounded text-xs font-semibold uppercase ${badge}`}>
      {label}
    </span>
  )
}

// Chevron icons using inline SVG (consistent with project's no-icon-library pattern)
function ChevronDown() {
  return (
    <svg
      className="w-4 h-4"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      viewBox="0 0 24 24"
      aria-hidden="true"
    >
      <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
    </svg>
  )
}

function ChevronRight() {
  return (
    <svg
      className="w-4 h-4"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      viewBox="0 0 24 24"
      aria-hidden="true"
    >
      <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
    </svg>
  )
}

// ---------------------------------------------------------------------------
// Main panel component
// ---------------------------------------------------------------------------

interface Props {
  taskId: string
}

export function RedTeamAuditPanel({ taskId }: Props) {
  const [data, setData] = useState<RedTeamAuditData | null>(null)
  const [loading, setLoading] = useState(true)
  const [expanded, setExpanded] = useState(false)

  useEffect(() => {
    if (!taskId) return
    setLoading(true)
    getRedTeamAudit(taskId)
      .then(setData)
      .catch(() => {
        // Non-blocking: silently suppress errors so the review workflow isn't interrupted
        setData(null)
      })
      .finally(() => setLoading(false))
  }, [taskId])

  // Nothing to show while loading or if no audit data exists
  if (loading || !data) return null

  const { red_team_critique } = data
  const { critique_items, summary, overall_severity } = red_team_critique
  const { badge: headerBadgeClasses } = severityClasses(overall_severity)

  return (
    <div className="card border border-teter-gray-mid rounded">
      {/* Collapsible header */}
      <button
        type="button"
        className="w-full flex items-center justify-between px-4 py-3 text-left hover:bg-teter-gray/40 transition-colors rounded"
        onClick={() => setExpanded((v) => !v)}
        aria-expanded={expanded}
      >
        <div className="flex items-center gap-2">
          <span className="w-0.5 h-5 bg-teter-orange rounded-sm flex-shrink-0" />
          <span className="text-sm font-semibold text-teter-dark">Red Team Audit Trail</span>
          <SeverityBadge severity={overall_severity} />
        </div>
        <span className="text-teter-gray-text">
          {expanded ? <ChevronDown /> : <ChevronRight />}
        </span>
      </button>

      {/* Expanded body */}
      {expanded && (
        <div className="px-4 pb-4 flex flex-col gap-3">
          {/* Summary */}
          {summary && (
            <p className="text-sm italic text-teter-gray-text leading-relaxed">
              &ldquo;{summary}&rdquo;
            </p>
          )}

          {/* Critique table */}
          {critique_items.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="w-full text-xs border-collapse">
                <thead>
                  <tr className="bg-teter-gray border-b border-teter-gray-mid">
                    <th className="px-2 py-2 text-left font-semibold text-teter-dark w-1/6">
                      Field
                    </th>
                    <th className="px-2 py-2 text-left font-semibold text-teter-dark w-1/4">
                      Original (Pass 1)
                    </th>
                    <th className="px-2 py-2 text-left font-semibold text-teter-dark w-1/4">
                      Critique
                    </th>
                    <th className="px-2 py-2 text-left font-semibold text-teter-dark w-1/8">
                      Severity
                    </th>
                    <th className="px-2 py-2 text-left font-semibold text-teter-dark w-1/4">
                      Revised
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {critique_items.map((item, idx) => {
                    const { row } = severityClasses(item.severity)
                    return (
                      <tr
                        key={idx}
                        className={`border-b border-teter-gray-mid last:border-b-0 ${row}`}
                      >
                        <td className="px-2 py-2 font-medium text-teter-dark align-top">
                          {item.field}
                        </td>
                        <td className="px-2 py-2 text-teter-gray-text align-top whitespace-pre-wrap">
                          {item.original}
                        </td>
                        <td className="px-2 py-2 text-teter-dark align-top whitespace-pre-wrap">
                          {item.critique}
                        </td>
                        <td className="px-2 py-2 align-top">
                          <SeverityBadge severity={item.severity} />
                        </td>
                        <td className="px-2 py-2 text-teter-dark align-top whitespace-pre-wrap">
                          {item.revised_value ?? (
                            <span className="text-teter-gray-text italic">—</span>
                          )}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="text-xs text-teter-gray-text italic">No critique items recorded.</p>
          )}
        </div>
      )}
    </div>
  )
}
