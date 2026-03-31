/**
 * Collapsible JSON tree viewer for AI thought chains.
 */
interface Props {
  data: unknown
  onClose: () => void
}

function JsonNode({ value, depth = 0 }: { value: unknown; depth?: number }) {
  if (value === null) return <span className="text-teter-gray-text">null</span>
  if (typeof value === 'boolean')
    return <span className="text-purple-600">{String(value)}</span>
  if (typeof value === 'number')
    return <span className="text-blue-600">{value}</span>
  if (typeof value === 'string')
    return (
      <span className="text-green-700">
        &quot;{value.length > 200 ? value.slice(0, 200) + '…' : value}&quot;
      </span>
    )

  if (Array.isArray(value)) {
    return (
      <span>
        [
        <div className="pl-4">
          {value.map((v, i) => (
            <div key={i}>
              <JsonNode value={v} depth={depth + 1} />
              {i < value.length - 1 && ','}
            </div>
          ))}
        </div>
        ]
      </span>
    )
  }

  if (typeof value === 'object' && value !== null) {
    const entries = Object.entries(value as Record<string, unknown>)
    return (
      <span>
        {'{'}
        <div className="pl-4">
          {entries.map(([k, v], i) => (
            <div key={k}>
              <span className="text-teter-orange font-semibold">&quot;{k}&quot;</span>
              {': '}
              <JsonNode value={v} depth={depth + 1} />
              {i < entries.length - 1 && ','}
            </div>
          ))}
        </div>
        {'}'}
      </span>
    )
  }

  return <span>{String(value)}</span>
}

export function ThoughtChainModal({ data, onClose }: Props) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 px-4">
      <div className="bg-white rounded-lg shadow-xl w-full max-w-3xl max-h-[85vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-teter-gray-mid">
          <div className="flex items-center gap-3">
            <span className="w-1 h-6 bg-teter-orange rounded-sm" />
            <h2 className="font-semibold text-teter-dark">Agent Thought Chain</h2>
          </div>
          <button
            className="text-teter-gray-text hover:text-teter-dark text-xl leading-none"
            onClick={onClose}
            aria-label="Close"
          >
            ×
          </button>
        </div>

        {/* Scrollable JSON body */}
        <div className="overflow-auto flex-1 p-5">
          <pre className="font-mono text-xs leading-relaxed text-teter-dark whitespace-pre-wrap">
            <JsonNode value={data} />
          </pre>
        </div>

        <div className="px-5 py-3 border-t border-teter-gray-mid flex justify-end">
          <button className="btn-outline text-sm" onClick={onClose}>
            Close
          </button>
        </div>
      </div>
    </div>
  )
}
