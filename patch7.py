import re

with open('src/ui/web/src/views/KnowledgeGraphView.tsx', 'r') as f:
    content = f.read()

# Make sure handleNavigateToNode is defined
replacement = """  const handleNavigateToNode = useCallback((nodeId: string) => {
    if (!graphData || !fgRef.current) return
    const targetNode = graphData.nodes.find(n => n.id === nodeId) as any
    if (targetNode && typeof targetNode.x === 'number' && typeof targetNode.y === 'number') {
      // Find the raw node data for the detail panel
      if (rawData) {
        const found = rawData.nodes.find(n => n.id === nodeId)
        if (found) setSelectedNode(found)
      }

      // Center the graph on the node
      // @ts-ignore
      fgRef.current.centerAt(targetNode.x, targetNode.y, 1000)
      // @ts-ignore
      fgRef.current.zoom(2.5, 1000)
    }
  }, [graphData, rawData])

  // Link color
"""

content = content.replace("  // Link color\n", replacement)

# Add onNavigate prop to GraphNodeDetailPanel
content = re.sub(
    r"          edges=\{rawData\.edges\}\n          onClose=\{\(\) => setSelectedNode\(null\)\}\n        />",
    "          edges={rawData.edges}\n          onClose={() => setSelectedNode(null)}\n          onNavigate={handleNavigateToNode}\n        />",
    content
)

with open('src/ui/web/src/views/KnowledgeGraphView.tsx', 'w') as f:
    f.write(content)
