import re

with open('src/ui/web/src/views/DocumentAnalysisView.tsx', 'r') as f:
    content = f.read()

# Add RadarChart component
radar_chart = """
// Helpers for the Radar Chart
function RadarChart({ models, width = 300, height = 300 }: { models: any[], width?: number, height?: number }) {
  if (!models || models.length === 0) return null

  const cx = width / 2
  const cy = height / 2
  const radius = Math.min(cx, cy) - 40 // Padding

  // The 4 axes
  const axes = ['accuracy', 'completeness', 'relevance', 'citation_quality']
  const axisLabels = ['Accuracy', 'Completeness', 'Relevance', 'Citation']
  const angleSlice = (Math.PI * 2) / axes.length

  // Parse scores from model.columns
  const modelData = models.map((m, i) => {
    // Find numeric score in text like "Score: 8/10" or just use default
    const getScore = (key: string) => {
      const col = m.columns.find((c: any) => c.title.toLowerCase().includes(key))
      if (!col) return 5
      const match = col.content.match(/(?:Score|Rating):?\\s*(\\d+(?:\\.\\d+)?)/i)
      if (match) return parseFloat(match[1])
      // Try to parse confidence score if it exists and we're looking at accuracy
      if (key === 'accuracy' && m.confidence_score) return m.confidence_score * 10
      return 5 // default fallback
    }

    return {
      name: m.model_name || `Model ${i+1}`,
      color: i === 0 ? '#3B82F6' : i === 1 ? '#10B981' : '#F59E0B',
      scores: [
        getScore('accuracy'),
        getScore('completeness'),
        getScore('relevance'),
        getScore('citation')
      ]
    }
  })

  // Calculate points for a given score (0-10) on a given axis index
  const getPoint = (score: number, i: number) => {
    // Math.PI / 2 offset to start at the top
    const angle = angleSlice * i - Math.PI / 2
    // Scale score 0-10 to radius length
    const r = (Math.max(0, Math.min(10, score)) / 10) * radius
    return {
      x: cx + r * Math.cos(angle),
      y: cy + r * Math.sin(angle)
    }
  }

  return (
    <div className="flex flex-col items-center justify-center my-6 bg-white p-4 rounded border border-gray-200 shadow-sm max-w-lg mx-auto">
      <h3 className="text-sm font-semibold text-teter-dark mb-4 uppercase tracking-wide">Multi-Model Comparison</h3>
      <svg width={width} height={height} className="overflow-visible font-sans">
        {/* Background grid circles */}
        {[0.2, 0.4, 0.6, 0.8, 1.0].map((scale, i) => (
          <circle key={i} cx={cx} cy={cy} r={radius * scale} fill="none" stroke="#e5e7eb" strokeWidth="1" strokeDasharray={i === 4 ? "" : "4 4"} />
        ))}

        {/* Axis lines */}
        {axes.map((_, i) => {
          const p = getPoint(10, i)
          return <line key={i} x1={cx} y1={cy} x2={p.x} y2={p.y} stroke="#e5e7eb" strokeWidth="1" />
        })}

        {/* Axis labels */}
        {axes.map((_, i) => {
          const p = getPoint(12, i) // Push labels out a bit
          return (
            <text key={i} x={p.x} y={p.y} fontSize="11" fill="#6b7280" textAnchor="middle" dominantBaseline="middle" className="font-medium">
              {axisLabels[i]}
            </text>
          )
        })}

        {/* Polygons per model */}
        {modelData.map((m, mIndex) => {
          const points = m.scores.map((s, i) => getPoint(s, i))
          const pointsStr = points.map(p => `${p.x},${p.y}`).join(' ')
          return (
            <g key={mIndex}>
              <polygon points={pointsStr} fill={m.color} fillOpacity="0.15" stroke={m.color} strokeWidth="2" />
              {points.map((p, i) => (
                <circle key={i} cx={p.x} cy={p.y} r="4" fill={m.color} />
              ))}
            </g>
          )
        })}
      </svg>

      {/* Legend */}
      <div className="flex gap-4 mt-4">
        {modelData.map((m, i) => (
          <div key={i} className="flex items-center gap-1.5">
            <span className="w-3 h-3 rounded-full" style={{ backgroundColor: m.color }}></span>
            <span className="text-xs font-medium text-teter-dark">{m.name}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
"""

if "function RadarChart" not in content:
    # Insert it before DocumentAnalysisView
    content = content.replace("export function DocumentAnalysisView() {", radar_chart + "\nexport function DocumentAnalysisView() {")

# Insert RadarChart into the view above columns
radar_usage = """        {analysisResult.length > 1 && (
          <RadarChart models={analysisResult} />
        )}

        <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">"""

if "grid grid-cols-1 xl:grid-cols-3 gap-6" in content:
    content = content.replace('<div className="grid grid-cols-1 xl:grid-cols-3 gap-6">', radar_usage)

with open('src/ui/web/src/views/DocumentAnalysisView.tsx', 'w') as f:
    f.write(content)
