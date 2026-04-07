import re

with open('src/ui/web/src/views/KnowledgeGraphView.tsx', 'r') as f:
    content = f.read()

# Add fgRef declaration
content = content.replace("  const containerRef = useRef<HTMLDivElement>(null)\n", "  const containerRef = useRef<HTMLDivElement>(null)\n  const fgRef = useRef<any>(null)\n")

# Add ref={fgRef} to ForceGraph2D
content = content.replace("<ForceGraph2D\n", "<ForceGraph2D\n              ref={fgRef}\n")

with open('src/ui/web/src/views/KnowledgeGraphView.tsx', 'w') as f:
    f.write(content)
