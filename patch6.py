import re

with open('src/ui/web/src/views/KnowledgeGraphView.tsx', 'r') as f:
    content = f.read()

replacement = """  const handleNavigateToNode = useCallback((nodeId: string) => {
    if (!graphData || !fgRef.current) return
    const targetNode = graphData.nodes.find(n => n.id === nodeId)
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
  }, [graphData, rawData, fgRef])

  return ("""

content = re.sub(
    r"  return \(",
    replacement,
    content,
    count=1
)

with open('src/ui/web/src/views/KnowledgeGraphView.tsx', 'w') as f:
    f.write(content)
