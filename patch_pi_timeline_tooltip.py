import re

with open('src/ui/web/src/views/ProjectIntelligenceView.tsx', 'r') as f:
    content = f.read()

# Add hover tooltip state to TimelineChart
timeline_old = r"""function TimelineChart\(\{ timeline \}: \{ timeline: TimelineEntry\[\] \}\) \{\n  if \(!timeline \|\| timeline\.length === 0\) return null\n\n  const maxTotal = Math\.max\(\.\.\.timeline\.map\(\(t\) => t\.total\)\)\n  const chartHeight = 200\n  const chartWidth = 600\n  const padding = 20"""

timeline_new = """function TimelineChart({ timeline }: { timeline: TimelineEntry[] }) {
  const [hoveredPoint, setHoveredPoint] = useState<{
    x: number,
    y: number,
    data: TimelineEntry
  } | null>(null)

  if (!timeline || timeline.length === 0) return null

  const maxTotal = Math.max(...timeline.map((t) => t.total))
  const chartHeight = 200
  const chartWidth = 600
  const padding = 20"""

content = content.replace("function TimelineChart({ timeline }: { timeline: TimelineEntry[] }) {\n  if (!timeline || timeline.length === 0) return null\n\n  const maxTotal = Math.max(...timeline.map((t) => t.total))\n  const chartHeight = 200\n  const chartWidth = 600\n  const padding = 20", timeline_new)

# Update circles and add tooltip UI
circles_old = r"""          <circle\n            key=\{t\.month\}\n            cx=\{x\}\n            cy=\{y\}\n            r=\{4\}\n            className="fill-blue-500"\n          >\n            <title>\{`\$\{t\.month\}: \$\{t\.total\} docs`\}<\/title>\n          <\/circle>"""

circles_new = """          <circle
            key={t.month}
            cx={x}
            cy={y}
            r={hoveredPoint?.data.month === t.month ? 6 : 4}
            className={`fill-blue-500 transition-all ${hoveredPoint?.data.month === t.month ? 'cursor-pointer stroke-white stroke-2' : ''}`}
            onMouseEnter={() => setHoveredPoint({ x, y, data: t })}
            onMouseLeave={() => setHoveredPoint(null)}
          />"""

content = re.sub(circles_old, circles_new, content)

# Add tooltip div inside the wrapper
wrapper_old = r"""  return \(\n    <div className="w-full overflow-x-auto">\n      <svg viewBox=\{`0 0 \$\{chartWidth\} \$\{chartHeight\}`\} className="w-full min-w-\[500px\] h-auto font-sans">"""

wrapper_new = """  return (
    <div className="w-full overflow-x-auto relative">
      {hoveredPoint && (
        <div
          className="absolute z-30 bg-teter-dark text-white rounded px-3 py-2 text-xs shadow-xl pointer-events-none transform -translate-x-1/2 -translate-y-full"
          style={{
            left: `${(hoveredPoint.x / chartWidth) * 100}%`,
            top: `${(hoveredPoint.y / chartHeight) * 100}%`,
            marginTop: '-10px'
          }}
        >
          <div className="font-bold mb-1 border-b border-gray-600 pb-1">{hoveredPoint.data.month}</div>
          <div className="mb-1">Total: {hoveredPoint.data.total} docs</div>
          {Object.entries(hoveredPoint.data.by_type || {}).map(([type, count]) => (
            <div key={type} className="flex justify-between gap-3 text-gray-300">
              <span>{type.replace('_', ' ')}:</span>
              <span className="font-semibold text-white">{count}</span>
            </div>
          ))}
          <div className="absolute bottom-[-6px] left-1/2 transform -translate-x-1/2 w-0 h-0 border-l-[6px] border-l-transparent border-r-[6px] border-r-transparent border-t-[6px] border-t-teter-dark"></div>
        </div>
      )}
      <svg viewBox={`0 0 ${chartWidth} ${chartHeight}`} className="w-full min-w-[500px] h-auto font-sans">"""

content = content.replace("  return (\n    <div className=\"w-full overflow-x-auto\">\n      <svg viewBox={`0 0 ${chartWidth} ${chartHeight}`} className=\"w-full min-w-[500px] h-auto font-sans\">", wrapper_new)

with open('src/ui/web/src/views/ProjectIntelligenceView.tsx', 'w') as f:
    f.write(content)
