import re

with open('src/ui/web/src/views/KnowledgeGraphView.tsx', 'r') as f:
    content = f.read()

# 1. Add toggle state to component
toggle_state = """  // Selected node (side panel)
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null)

  // Node type visibility toggles
  const [hiddenTypes, setHiddenTypes] = useState<Set<string>>(new Set())

  // Graph container dimensions"""

content = content.replace("  // Selected node (side panel)\n  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null)\n\n  // Graph container dimensions", toggle_state)

# 2. Add handleToggleType function
handle_toggle = """  const clearSearch = () => {
    setSearchQuery('')
    setSearchResults([])
    setSearchHighlightedNodeIds(new Set())
  }

  const handleToggleType = useCallback((type: string) => {
    setHiddenTypes(prev => {
      const next = new Set(prev)
      if (next.has(type)) next.delete(type)
      else next.add(type)
      return next
    })
  }, [])"""

content = content.replace("  const clearSearch = () => {\n    setSearchQuery('')\n    setSearchResults([])\n    setSearchHighlightedNodeIds(new Set())\n  }", handle_toggle)

# 3. Filter graphData based on hiddenTypes
filtered_graph_data = """  // Filter graph data if needed
  const graphData = useMemo(() => {
    if (!rawData) return null

    // Client-side visibility filtering
    if (hiddenTypes.size > 0) {
      const filteredNodes = rawData.nodes.filter(n => !hiddenTypes.has(n.type))
      const visibleNodeIds = new Set(filteredNodes.map(n => n.id))
      const filteredEdges = rawData.edges.filter(e =>
        visibleNodeIds.has(e.source) && visibleNodeIds.has(e.target)
      )

      return {
        nodes: filteredNodes.map((n) => ({
          ...n,
          _type: n.type,
          _label: n.label,
          _connCount: 0,
          _highlighted: searchHighlightedNodeIds.has(n.id),
        })) as MyNode[],
        links: filteredEdges.map((e) => ({
          source: e.source,
          target: e.target,
          type: e.type,
        })),
      }
    }

    return {
      nodes: rawData.nodes.map((n) => ({
        ...n,
        _type: n.type,
        _label: n.label,
        _connCount: 0,
        _highlighted: searchHighlightedNodeIds.has(n.id),
      })) as MyNode[],
      links: rawData.edges.map((e) => ({
        source: e.source,
        target: e.target,
        type: e.type,
      })),
    }
  }, [rawData, searchHighlightedNodeIds, hiddenTypes])"""

content = re.sub(
    r"  // Map raw data into what ForceGraph needs.*?(?=\n  // Pre-calculate degrees)",
    filtered_graph_data.replace("  // Filter graph data if needed\n", "  // Filter graph data if needed\n"),
    content,
    flags=re.DOTALL
)

# 4. Update the sidebar UI to include toggles
sidebar_ui_old = r"""                  <li key=\{type\} className="flex items-center justify-between py-1 border-b border-gray-100 last:border-0">\n                    <div className="flex items-center gap-2">\n                      <span className=\{`w-2 h-2 rounded-full \$\{color\}`\} \/>\n                      <span className="text-sm text-teter-dark">\{label\}<\/span>\n                    <\/div>\n                    <span className="text-sm font-medium text-teter-dark">\n                      \{count\}\n                    <\/span>\n                  <\/li>"""

sidebar_ui_new = """                  <li key={type} className="flex items-center justify-between py-1 border-b border-gray-100 last:border-0">
                    <label className="flex items-center gap-2 cursor-pointer group">
                      <input
                        type="checkbox"
                        checked={!hiddenTypes.has(type)}
                        onChange={() => handleToggleType(type)}
                        className="rounded border-gray-300 text-blue-600 focus:ring-blue-500 w-3.5 h-3.5"
                      />
                      <span className={`w-2 h-2 rounded-full ${color} opacity-80 group-hover:opacity-100`} />
                      <span className={`text-sm text-teter-dark ${hiddenTypes.has(type) ? 'opacity-50 line-through' : ''}`}>{label}</span>
                    </label>
                    <span className={`text-sm font-medium text-teter-dark ${hiddenTypes.has(type) ? 'opacity-50' : ''}`}>
                      {count}
                    </span>
                  </li>"""

content = re.sub(sidebar_ui_old, sidebar_ui_new, content)

with open('src/ui/web/src/views/KnowledgeGraphView.tsx', 'w') as f:
    f.write(content)
