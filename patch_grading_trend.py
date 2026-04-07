import re

with open('src/ui/web/src/views/GradingView.tsx', 'r') as f:
    content = f.read()

# 1. Add trend state and fetch logic
trend_state = """import { listGradingSessions, getGradingSession, submitHumanGrade } from '../api/client'
import { API_BASE_URL } from '../api/client' // Need to fetch trend custom since it's not in client.tsx yet

// Simple fetch for trend
async function fetchDivergenceTrend() {
  const token = localStorage.getItem('teterai_token')
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (token) headers['Authorization'] = `Bearer ${token}`

  const res = await fetch(`${API_BASE_URL}/grading/divergence-trend`, { headers })
  if (!res.ok) throw new Error('Failed to fetch trend')
  return res.json()
}

export function GradingView() {
  const [sessions, setSessions] = useState<GradingSessionSummary[]>([])
  const [trendData, setTrendData] = useState<{date: string, avg_divergence: number, sessions: number}[]>([])"""

content = content.replace("import { listGradingSessions, getGradingSession, submitHumanGrade } from '../api/client'\n\nexport function GradingView() {\n  const [sessions, setSessions] = useState<GradingSessionSummary[]>([])", trend_state)

# Fetch trend
fetch_trend = """  const loadSessions = async () => {
    try {
      const data = await listGradingSessions()
      setSessions(data)
      const trend = await fetchDivergenceTrend()
      setTrendData(trend.trend || [])
    } catch (err) {
      console.error('Failed to load grading sessions:', err)
    } finally {
      setLoading(false)
    }
  }"""

content = content.replace("""  const loadSessions = async () => {
    try {
      const data = await listGradingSessions()
      setSessions(data)
    } catch (err) {
      console.error('Failed to load grading sessions:', err)
    } finally {
      setLoading(false)
    }
  }""", fetch_trend)

# 2. Add SVG chart component
trend_chart = """// Helpers for Trend Line SVG
function DivergenceTrendChart({ data }: { data: {date: string, avg_divergence: number, sessions: number}[] }) {
  if (!data || data.length < 2) return null

  const width = 400
  const height = 120
  const padding = { top: 20, right: 20, bottom: 20, left: 30 }

  const maxDiv = Math.max(1.5, ...data.map(d => d.avg_divergence))

  const getX = (index: number) => padding.left + (index / (data.length - 1)) * (width - padding.left - padding.right)
  const getY = (val: number) => height - padding.bottom - (val / maxDiv) * (height - padding.top - padding.bottom)

  const points = data.map((d, i) => `${getX(i)},${getY(d.avg_divergence)}`).join(' ')
  const refY = getY(1.0)

  return (
    <div className="mt-6 bg-white p-4 rounded border border-gray-200 shadow-sm flex flex-col items-center">
      <h3 className="text-sm font-semibold text-teter-dark mb-2">Divergence Trend (Avg over time)</h3>
      <svg width={width} height={height} className="overflow-visible font-sans text-[10px]">
        {/* Y Axis Labels */}
        <text x={padding.left - 5} y={getY(maxDiv)} textAnchor="end" dominantBaseline="middle" fill="#9CA3AF">{maxDiv.toFixed(1)}</text>
        <text x={padding.left - 5} y={getY(0)} textAnchor="end" dominantBaseline="middle" fill="#9CA3AF">0.0</text>

        {/* Threshold Line (1.0) */}
        <line x1={padding.left} y1={refY} x2={width - padding.right} y2={refY} stroke="#EF4444" strokeWidth="1" strokeDasharray="4 4" />
        <text x={width - padding.right + 5} y={refY} dominantBaseline="middle" fill="#EF4444" className="font-semibold">1.0</text>

        {/* X Axis Line */}
        <line x1={padding.left} y1={height - padding.bottom} x2={width - padding.right} y2={height - padding.bottom} stroke="#E5E7EB" strokeWidth="1" />

        {/* Trend Line */}
        <polyline points={points} fill="none" stroke="#3B82F6" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />

        {/* Data Points */}
        {data.map((d, i) => (
          <g key={i}>
            <circle cx={getX(i)} cy={getY(d.avg_divergence)} r="4" fill="#3B82F6" className="cursor-pointer transition-transform hover:scale-150" />
            <title>{`${d.date}: ${d.avg_divergence.toFixed(2)} (${d.sessions} sessions)`}</title>
          </g>
        ))}
      </svg>
    </div>
  )
}
"""

content = content.replace("export function GradingView() {", trend_chart + "\nexport function GradingView() {")

# Insert chart below stats
stats_placement = """        <div className="bg-white rounded border border-gray-200 shadow-sm p-4 text-center">
          <div className="text-3xl font-bold text-teter-dark mb-1">{highDivergenceCount}</div>
          <div className="text-sm text-teter-gray-text uppercase tracking-wider font-semibold">
            High Divergence (&gt;1.0)
          </div>
        </div>
      </div>

      {trendData && trendData.length > 1 && <DivergenceTrendChart data={trendData} />}

      <div className="bg-white border border-gray-200 rounded shadow-sm overflow-hidden mt-6">"""

content = content.replace("""        <div className="bg-white rounded border border-gray-200 shadow-sm p-4 text-center">
          <div className="text-3xl font-bold text-teter-dark mb-1">{highDivergenceCount}</div>
          <div className="text-sm text-teter-gray-text uppercase tracking-wider font-semibold">
            High Divergence (&gt;1.0)
          </div>
        </div>
      </div>

      <div className="bg-white border border-gray-200 rounded shadow-sm overflow-hidden mt-6">""", stats_placement)

with open('src/ui/web/src/views/GradingView.tsx', 'w') as f:
    f.write(content)
