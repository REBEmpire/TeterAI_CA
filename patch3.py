import re

with open('src/ui/web/src/views/KnowledgeGraphView.tsx', 'r') as f:
    content = f.read()

# Add onNavigate prop to GraphNodeDetailPanel
content = re.sub(
    r"          edges=\{rawData\.edges\}\n          onClose=\{\(\) => setSelectedNode\(null\)\}\n        />",
    "          edges={rawData.edges}\n          onClose={() => setSelectedNode(null)}\n          onNavigate={handleNavigateToNode}\n        />",
    content
)

# Add handleNavigateToNode function before return
content = re.sub(
    r"  const clearSearch = \(\) => \{\n    setSearchQuery\(''\)\n    setSearchResults\(\[\]\)\n    setSearchHighlightedNodeIds\(new Set\(\)\)\n  \}\n\n  return \(",
    """  const clearSearch = () => {
    setSearchQuery('')
    setSearchResults([])
    setSearchHighlightedNodeIds(new Set())
  }

  const handleNavigateToNode = useCallback((nodeId: string) => {
    if (!graphData) return
    const targetNode = graphData.nodes.find(n => n.id === nodeId) as MyNode | undefined
    if (targetNode) {
      handleNodeClick(targetNode)
    }
  }, [graphData, handleNodeClick])

  return (""",
    content
)

with open('src/ui/web/src/views/KnowledgeGraphView.tsx', 'w') as f:
    f.write(content)
