/**
 * GraphNodeDetailPanel — side panel shown when a knowledge-graph node is clicked.
 *
 * Shows the node's type badge, label, description/properties, and a list of
 * directly connected nodes. Closes via the "Close" button or by clicking the
 * overlay.
 */

export interface GraphNode {
  id: string
  type: 'SPEC_SECTION' | 'RFI' | 'DESIGN_FLAW' | 'CORRECTIVE_ACTION' | string
  label: string
  properties: Record<string, string>
}

export interface GraphEdge {
  source: string
  target: string
  type: string
}

interface Props {
  node: GraphNode
  allNodes: GraphNode[]
  edges: GraphEdge[]
  onClose: () => void
}

const TYPE_COLORS: Record<string, string> = {
  SPEC_SECTION:       'bg-blue-100 text-blue-800',
  RFI:                'bg-orange-100 text-orange-800',
  DESIGN_FLAW:        'bg-red-100 text-red-800',
  CORRECTIVE_ACTION:  'bg-green-100 text-green-800',
}

const TYPE_LABELS: Record<string, string> = {
  SPEC_SECTION:      'Spec Section',
  RFI:               'RFI',
  DESIGN_FLAW:       'Design Flaw',
  CORRECTIVE_ACTION: 'Corrective Action',
}

function TypeBadge({ type }: { type: string }) {
  const color = TYPE_COLORS[type] ?? 'bg-gray-100 text-gray-700'
  const label = TYPE_LABELS[type] ?? type
  return (
    <span className={`inline-block px-2 py-0.5 rounded text-xs font-semibold uppercase tracking-wide ${color}`}>
      {label}
    </span>
  )
}

export function GraphNodeDetailPanel({ node, allNodes, edges, onClose }: Props) {
  // Find all nodes connected to this one (either direction)
  const connectedNodeIds = new Set<string>()
  const connectionTypes: Record<string, string> = {}

  for (const edge of edges) {
    if (edge.source === node.id) {
      connectedNodeIds.add(edge.target)
      connectionTypes[edge.target] = edge.type
    } else if (edge.target === node.id) {
      connectedNodeIds.add(edge.source)
      connectionTypes[edge.source] = edge.type
    }
  }

  const connectedNodes = allNodes.filter((n) => connectedNodeIds.has(n.id))

  // Property entries to display (skip empty values)
  const propEntries = Object.entries(node.properties).filter(
    ([k, v]) => v && k !== 'flaw_id' && k !== 'action_id' && k !== 'rfi_id'
  )

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
          {/* Properties */}
          {propEntries.length > 0 && (
            <section>
              <h3 className="text-xs font-semibold text-teter-gray-text uppercase tracking-wider mb-2">
                Properties
              </h3>
              <dl className="space-y-2">
                {propEntries.map(([key, value]) => (
                  <div key={key}>
                    <dt className="text-xs text-teter-gray-text capitalize">
                      {key.replace(/_/g, ' ')}
                    </dt>
                    <dd className="text-sm text-teter-dark break-words leading-snug">
                      {value}
                    </dd>
                  </div>
                ))}
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
                  <li key={cn.id} className="border border-gray-100 rounded p-2">
                    <div className="flex items-center gap-2 mb-1">
                      <TypeBadge type={cn.type} />
                      <span className="text-xs text-teter-gray-text">
                        via {connectionTypes[cn.id] ?? '—'}
                      </span>
                    </div>
                    <p className="text-sm text-teter-dark break-words leading-snug">
                      {cn.label}
                    </p>
                  </li>
                ))}
              </ul>
            </section>
          )}

          {connectedNodes.length === 0 && propEntries.length === 0 && (
            <p className="text-sm text-teter-gray-text">No additional details available.</p>
          )}
        </div>

        {/* Footer */}
        <div className="border-t border-gray-100 p-3">
          <button
            onClick={onClose}
            className="w-full text-sm font-semibold text-center py-2 rounded border border-gray-200 text-teter-dark hover:bg-gray-50 transition-colors"
          >
            Close
          </button>
        </div>
      </aside>
    </>
  )
}
