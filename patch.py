import re

with open('src/ui/web/src/components/graph/GraphNodeDetailPanel.tsx', 'r') as f:
    content = f.read()

# Replace GraphNode interface type
content = re.sub(
    r"type: 'SPEC_SECTION' \| 'RFI' \| 'DESIGN_FLAW' \| 'CORRECTIVE_ACTION' \| string",
    "type: 'SPEC_SECTION' | 'RFI' | 'DESIGN_FLAW' | 'CORRECTIVE_ACTION' | 'SUBMITTAL' | 'SCHEDULEREVIEW' | 'PAYAPP' | 'COSTANALYSIS' | 'PARTY' | string",
    content
)

# Add onNavigate to Props
content = re.sub(
    r"  onClose: \(\) => void\n}",
    "  onClose: () => void\n  onNavigate?: (nodeId: string) => void\n}",
    content
)

# Update TYPE_COLORS
content = re.sub(
    r"  CORRECTIVE_ACTION:  'bg-green-100 text-green-800',\n}",
    "  CORRECTIVE_ACTION:  'bg-green-100 text-green-800',\n  SUBMITTAL:          'bg-purple-100 text-purple-800',\n  SCHEDULEREVIEW:     'bg-teal-100 text-teal-800',\n  PAYAPP:             'bg-yellow-100 text-yellow-800',\n  COSTANALYSIS:       'bg-indigo-100 text-indigo-800',\n  PARTY:              'bg-pink-100 text-pink-800',\n}",
    content
)

# Update TYPE_LABELS
content = re.sub(
    r"  CORRECTIVE_ACTION: 'Corrective Action',\n}",
    "  CORRECTIVE_ACTION: 'Corrective Action',\n  SUBMITTAL:         'Submittal',\n  SCHEDULEREVIEW:    'Schedule Review',\n  PAYAPP:            'Pay App',\n  COSTANALYSIS:      'Cost Analysis',\n  PARTY:             'Party',\n}",
    content
)

# Update function signature
content = re.sub(
    r"export function GraphNodeDetailPanel\(\{ node, allNodes, edges, onClose \}: Props\) \{",
    "export function GraphNodeDetailPanel({ node, allNodes, edges, onClose, onNavigate }: Props) {",
    content
)

# Replace the properties and UI rendering section
content = re.sub(
    r"  // Property entries to display \(skip empty values\)\n  const propEntries = Object.entries\(node.properties\).filter\(\n    \(\[k, v\]\) => v && k !== 'flaw_id' && k !== 'action_id' && k !== 'rfi_id'\n  \)\n\n  return \(\n    <>\n      \{\/\* Backdrop \*\/\}\n      <div\n        className=\"fixed inset-0 z-40 bg-black\/20\"\n        onClick=\{onClose\}\n        aria-hidden=\"true\"\n      \/>\n\n      \{\/\* Panel \*\/\}\n      <aside\n        className=\"fixed right-0 top-0 h-full w-80 z-50 bg-white shadow-2xl flex flex-col\"\n        role=\"complementary\"\n        aria-label=\"Node detail panel\"\n      >\n        \{\/\* Header \*\/\}\n        <div className=\"bg-teter-dark text-white px-4 py-3 flex items-start justify-between gap-2\">\n          <div className=\"flex flex-col gap-1 min-w-0\">\n            <TypeBadge type=\{node.type\} \/>\n            <span className=\"font-semibold text-sm mt-1 break-words leading-snug\">\n              \{node.label\}\n            <\/span>\n          <\/div>\n          <button\n            onClick=\{onClose\}\n            className=\"text-white\/60 hover:text-white text-lg leading-none shrink-0 mt-0.5\"\n            aria-label=\"Close panel\"\n          >\n            ✕\n          <\/button>\n        <\/div>\n\n        \{\/\* Scrollable body \*\/\}\n        <div className=\"flex-1 overflow-y-auto p-4 space-y-5\">\n          \{\/\* Properties \*\/\}\n          \{propEntries.length > 0 && \(\n            <section>\n              <h3 className=\"text-xs font-semibold text-teter-gray-text uppercase tracking-wider mb-2\">\n                Properties\n              <\/h3>\n              <dl className=\"space-y-2\">\n                \{propEntries.map\(\(\[key, value\]\) => \(\n                  <div key=\{key\}>\n                    <dt className=\"text-xs text-teter-gray-text capitalize\">\n                      \{key.replace\(\/_/g, ' '\)\}\n                    <\/dt>\n                    <dd className=\"text-sm text-teter-dark break-words leading-snug\">\n                      \{value\}\n                    <\/dd>\n                  <\/div>\n                \)\)\}\n              <\/dl>\n            <\/section>\n          \)\}\n\n          \{\/\* Connected nodes \*\/\}\n          \{connectedNodes.length > 0 && \(\n            <section>\n              <h3 className=\"text-xs font-semibold text-teter-gray-text uppercase tracking-wider mb-2\">\n                Connected Nodes \(\{connectedNodes.length\}\)\n              <\/h3>\n              <ul className=\"space-y-2\">\n                \{connectedNodes.map\(\(cn\) => \(\n                  <li key=\{cn.id\} className=\"border border-gray-100 rounded p-2\">\n                    <div className=\"flex items-center gap-2 mb-1\">\n                      <TypeBadge type=\{cn.type\} \/>\n                      <span className=\"text-xs text-teter-gray-text\">\n                        via \{connectionTypes\[cn.id\] \?\? '—'\}\n                      <\/span>\n                    <\/div>\n                    <p className=\"text-sm text-teter-dark break-words leading-snug\">\n                      \{cn.label\}\n                    <\/p>\n                  <\/li>\n                \)\)\}\n              <\/ul>\n            <\/section>\n          \)\}\n\n          \{connectedNodes.length === 0 && propEntries.length === 0 && \(\n            <p className=\"text-sm text-teter-gray-text\">No additional details available.<\/p>\n          \)\}",
    """  // Format readable dates
  const formatDate = (dateStr: string) => {
    try {
      const date = new Date(dateStr)
      return isNaN(date.getTime()) ? dateStr : date.toLocaleDateString()
    } catch {
      return dateStr
    }
  }

  // Extract source document info
  const driveFileId = node.properties?.drive_file_id
  const filename = node.properties?.filename

  // Extract full summary
  const summaryFull = node.properties?.summary_full || node.properties?.summary

  // Property entries to display (skip empty values, summary, and internal fields)
  const propEntries = Object.entries(node.properties).filter(
    ([k, v]) => v &&
      k !== 'flaw_id' &&
      k !== 'action_id' &&
      k !== 'rfi_id' &&
      k !== 'summary' &&
      k !== 'summary_full' &&
      k !== 'drive_file_id' &&
      k !== 'filename'
  )

  const isDesktopMode = import.meta.env.VITE_DESKTOP_MODE === 'true'
  const sourceDocHref = driveFileId && !isDesktopMode
    ? `https://drive.google.com/file/d/${driveFileId}/view`
    : (filename ? `file://${filename}` : undefined)

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 z-40 bg-black/20"
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Panel */}
      <aside
        className="fixed right-0 top-0 h-full w-80 z-50 bg-white shadow-2xl flex flex-col"
        role="complementary"
        aria-label="Node detail panel"
      >
        {/* Header */}
        <div className="bg-teter-dark text-white px-4 py-3 flex items-start justify-between gap-2">
          <div className="flex flex-col gap-1 min-w-0">
            <TypeBadge type={node.type} />
            <span className="font-semibold text-sm mt-1 break-words leading-snug">
              {node.label}
            </span>
          </div>
          <button
            onClick={onClose}
            className="text-white/60 hover:text-white text-lg leading-none shrink-0 mt-0.5"
            aria-label="Close panel"
          >
            ✕
          </button>
        </div>

        {/* Scrollable body */}
        <div className="flex-1 overflow-y-auto p-4 space-y-5">
          {/* Source Document Link */}
          {(sourceDocHref) && (
            <section>
              <a
                href={sourceDocHref}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-blue-50 text-blue-700 hover:bg-blue-100 rounded text-sm font-medium transition-colors"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
                </svg>
                View Source Document
              </a>
              {filename && <p className="text-xs text-teter-gray-text mt-1 ml-1">{filename}</p>}
            </section>
          )}

          {/* Full Summary */}
          {summaryFull && (
            <section>
              <h3 className="text-xs font-semibold text-teter-gray-text uppercase tracking-wider mb-2">
                Summary
              </h3>
              <p className="text-sm text-teter-dark break-words leading-relaxed bg-gray-50 p-3 rounded border border-gray-100">
                {summaryFull}
              </p>
            </section>
          )}

          {/* Properties */}
          {propEntries.length > 0 && (
            <section>
              <h3 className="text-xs font-semibold text-teter-gray-text uppercase tracking-wider mb-2">
                Properties
              </h3>
              <dl className="space-y-2">
                {propEntries.map(([key, value]) => {
                  const isDate = key.includes('date')
                  const displayValue = isDate ? formatDate(value as string) : value
                  return (
                    <div key={key}>
                      <dt className="text-xs text-teter-gray-text capitalize">
                        {key.replace(/_/g, ' ')}
                      </dt>
                      <dd className="text-sm text-teter-dark break-words leading-snug">
                        {displayValue as string}
                      </dd>
                    </div>
                  )
                })}
              </dl>
            </section>
          )}

          {/* Connected nodes */}
          {connectedNodes.length > 0 && (
            <section>
              <h3 className="text-xs font-semibold text-teter-gray-text uppercase tracking-wider mb-2">
                Connected Nodes ({connectedNodes.length})
              </h3>
              <ul className="space-y-2">
                {connectedNodes.map((cn) => (
                  <li
                    key={cn.id}
                    className={`border border-gray-100 rounded p-2 transition-colors ${onNavigate ? 'cursor-pointer hover:bg-gray-50' : ''}`}
                    onClick={() => onNavigate && onNavigate(cn.id)}
                  >
                    <div className="flex items-center justify-between mb-1">
                      <div className="flex items-center gap-2">
                        <TypeBadge type={cn.type} />
                        <span className="text-xs text-teter-gray-text">
                          via {connectionTypes[cn.id] ?? '—'}
                        </span>
                      </div>
                      {onNavigate && (
                        <svg className="w-3 h-3 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                        </svg>
                      )}
                    </div>
                    <p className="text-sm text-teter-dark break-words leading-snug">
                      {cn.label}
                    </p>
                  </li>
                ))}
              </ul>
            </section>
          )}

          {connectedNodes.length === 0 && propEntries.length === 0 && !summaryFull && !sourceDocHref && (
            <p className="text-sm text-teter-gray-text">No additional details available.</p>
          )}""",
    content,
    flags=re.DOTALL
)

with open('src/ui/web/src/components/graph/GraphNodeDetailPanel.tsx', 'w') as f:
    f.write(content)
