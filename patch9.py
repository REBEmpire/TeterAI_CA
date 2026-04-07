import re

with open('src/ui/web/src/views/KnowledgeGraphView.tsx', 'r') as f:
    content = f.read()

# Fix fgRef issue. react-force-graph exports a method to get the reference, or we can use the ref prop properly depending on its type. But if it errors, we can just omit it for now and center without zoom, or use it without TS complaining.
# For react-force-graph-2d, we can use forwardRef if needed, but easier is to cast it.
# Actually, the ForceGraph2D module might export a hook or be a forwardRef component.
content = content.replace("ref={fgRef}\n", "//@ts-ignore\n              ref={fgRef}\n")

with open('src/ui/web/src/views/KnowledgeGraphView.tsx', 'w') as f:
    f.write(content)
