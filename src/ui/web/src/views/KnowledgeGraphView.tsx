/**
 * KnowledgeGraphView — interactive force-directed graph of RFIs clustered by
 * design flaw and spec section.
 *
 * Phase D feature — uses react-force-graph-2d for the canvas rendering.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import ForceGraph2D from 'react-force-graph-2d'
import type { NodeObject, LinkObject } from 'react-force-graph-2d'
import { GraphNodeDetailPanel } from '../components/graph/GraphNodeDetailPanel'
import type { GraphEdge, GraphNode } from '../components/graph/GraphNodeDetailPanel'
import { listProjects } from '../api/client'
import type { ProjectSummary } from '../types'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface RawGraphData {
  nodes: GraphNode[]
  edges: GraphEdge[]
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const NODE_COLORS: Record<string, string> = {
  SPEC_SECTION:      '#3b82f6', // blue
  RFI:               '#f97316', // orange (teter-orange)
  DESIGN_FLAW:       '#ef4444', // red
  CORRECTIVE_ACTION: '#22c55e', // green
}

const NODE_BASE_RADIUS = 6

const SPEC_DIVISIONS = [
  { code: '', label: 'All Divisions' },
  { code: '01', label: '01 General' },
  { code: '02', label: '02 Existing Conditions' },
  { code: '03', label: '03 Concrete' },
  { code: '04', label: '04 Masonry' },
  { code: '05', label: '05 Metals' },
  { code: '06', label: '06 Wood & Plastics' },
  { code: '07', label: '07 Thermal & Moisture' },
  { code: '08', label: '08 Openings' },
  { code: '09', label: '09 Finishes' },
  { code: '10', label: '10 Specialties' },
  { code: '14', label: '14 Conveying' },
  { code: '21', label: '21 Fire Suppression' },
  { code: '22', label: '22 Plumbing' },
  { code: '23', label: '23 HVAC' },
  { code: '26', label: '26 Electrical' },
]

const BASE_URL = '/api/v1'

function getToken(): string | null {
  return localStorage.getItem('teterai_token')
}

async function fetchGraphData(
  projectId: string,
  specDivision: string,
  dateFrom: string,
  dateTo: string,
): Promise<RawGraphData> {
  const params = new URLSearchParams({ project_id: projectId })
  if (specDivision) params.set('spec_division', specDivision)
  if (dateFrom) params.set('date_from', dateFrom)
  if (dateTo) params.set('date_to', dateTo)

  const token = getToken()
  const res = await fetch(`${BASE_URL}/knowledge-graph/rfi-patterns?${params.toString()}`, {
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
  })

  if (!res.ok) throw new Error(`API error ${res.status}`)
  return res.json()
}

// ---------------------------------------------------------------------------
// Helper: count connections per node
// ---------------------------------------------------------------------------

function connectionCounts(nodes: GraphNode[], edges: GraphEdge[]): Record<string, number> {
  const counts: Record<string, number> = {}
  for (const n of nodes) counts[n.id] = 0
  for (const e of edges) {
    if (counts[e.source] !== undefined) counts[e.source]++
    if (counts[e.target] !== undefined) counts[e.target]++
  }
  return counts
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function KnowledgeGraphView() {
  // Data state
  const [rawData, setRawData] = useState<RawGraphData | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Projects
  const [projects, setProjects] = useState<ProjectSummary[]>([])
  const [selectedProject, setSelectedProject] = useState('')

  // Filters
  const [specDivision, setSpecDivision] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')

  // Cluster mode
  const [clusterByFlaw, setClusterByFlaw] = useState(false)

  // Selected node (side panel)
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null)

  // Graph container dimensions
  const containerRef = useRef<HTMLDivElement>(null)
  const [dims, setDims] = useState({ width: 800, height: 600 })

  // Load projects for the project selector
  useEffect(() => {
    listProjects().then(setProjects).catch(() => {})
  }, [])

  // Auto-select first project
  useEffect(() => {
    if (projects.length > 0 && !selectedProject) {
      setSelectedProject(projects[0].project_id)
    }
  }, [projects, selectedProject])

  // Observe container size
  useEffect(() => {
    if (!containerRef.current) return
    const ro = new ResizeObserver((entries) => {
      const entry = entries[0]
      if (entry) {
        setDims({
          width: entry.contentRect.width,
          height: entry.contentRect.height,
        })
      }
    })
    ro.observe(containerRef.current)
    return () => ro.disconnect()
  }, [])

  // Fetch graph data whenever filters change
  useEffect(() => {
    if (!selectedProject) return

    setLoading(true)
    setError(null)
    setSelectedNode(null)

    fetchGraphData(selectedProject, specDivision, dateFrom, dateTo)
      .then(setRawData)
      .catch((err) => setError(err.message ?? 'Failed to load graph data.'))
      .finally(() => setLoading(false))
  }, [selectedProject, specDivision, dateFrom, dateTo])

  // Build force-graph data
  const connCounts = rawData
    ? connectionCounts(rawData.nodes, rawData.edges)
    : {}

  const graphData = rawData
    ? {
        nodes: rawData.nodes.map((n) => ({
          ...n,
          _type: n.type,
          _label: n.label,
          _connCount: connCounts[n.id] ?? 0,
        })),
        links: rawData.edges.map((e) => ({
          source: e.source,
          target: e.target,
          _type: e.type,
        })),
      }
    : { nodes: [], links: [] }

  // Custom node paint
  const paintNode = useCallback(
    (node: NodeObject, ctx: CanvasRenderingContext2D, globalScale: number) => {
      const type = (node as NodeObject & { _type: string })._type
      const label = (node as NodeObject & { _label: string })._label
      const connCount = (node as NodeObject & { _connCount: number })._connCount

      const color = NODE_COLORS[type] ?? '#94a3b8'
      const radius = NODE_BASE_RADIUS + Math.min(connCount * 1.5, 10)

      // Circle
      ctx.beginPath()
      ctx.arc(node.x ?? 0, node.y ?? 0, radius, 0, 2 * Math.PI)
      ctx.fillStyle = color
      ctx.fill()
      ctx.strokeStyle = 'rgba(255,255,255,0.4)'
      ctx.lineWidth = 1 / globalScale
      ctx.stroke()

      // Label (only at reasonable zoom)
      if (globalScale > 0.6) {
        const fontSize = Math.max(3, 10 / globalScale)
        ctx.font = `${fontSize}px Inter, sans-serif`
        ctx.fillStyle = '#ffffff'
        ctx.textAlign = 'center'
        ctx.textBaseline = 'middle'

        // Clip label to 20 chars
        const text = label.length > 20 ? label.slice(0, 18) + '…' : label
        ctx.fillText(text, node.x ?? 0, node.y ?? 0)
      }
    },
    [],
  )

  // Node click
  const handleNodeClick = useCallback(
    (node: NodeObject) => {
      if (!rawData) return
      const found = rawData.nodes.find((n) => n.id === node.id)
      setSelectedNode(found ?? null)
    },
    [rawData],
  )

  // Link color by relationship type
  const getLinkColor = useCallback((link: LinkObject) => {
    const type = (link as LinkObject & { _type: string })._type
    if (type === 'REVEALS') return '#ef4444'
    if (type === 'SUGGESTS') return '#22c55e'
    if (type === 'REFERENCES_SPEC') return '#3b82f6'
    return '#94a3b8'
  }, [])

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div className="flex flex-col h-screen overflow-hidden bg-gray-50">
      {/* Page header */}
      <div className="bg-white border-b border-gray-200 px-6 py-4 shrink-0">
        <div className="max-w-wide mx-auto">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h1 className="text-xl font-semibold text-teter-dark">Knowledge Graph</h1>
              <p className="text-sm text-teter-gray-text mt-0.5">
                RFI patterns clustered by design flaw and spec section
              </p>
            </div>
            <div className="hidden sm:block w-1 h-8 bg-teter-orange rounded-sm" />
          </div>

          {/* Filter bar */}
          <div className="flex flex-wrap gap-3 items-end">
            {/* Project selector */}
            <div className="flex flex-col gap-1">
              <label className="text-xs text-teter-gray-text font-medium">Project</label>
              <select
                className="select"
                value={selectedProject}
                onChange={(e) => setSelectedProject(e.target.value)}
                aria-label="Select project"
              >
                <option value="">Select project…</option>
                {projects.map((p) => (
                  <option key={p.project_id} value={p.project_id}>
                    {p.project_number} — {p.name}
                  </option>
                ))}
              </select>
            </div>

            {/* Spec division filter */}
            <div className="flex flex-col gap-1">
              <label className="text-xs text-teter-gray-text font-medium">Spec Division</label>
              <div className="flex flex-wrap gap-1">
                {SPEC_DIVISIONS.map((div) => (
                  <button
                    key={div.code}
                    onClick={() => setSpecDivision(div.code)}
                    className={`px-2.5 py-1 text-xs rounded-full font-medium transition-colors ${
                      specDivision === div.code
                        ? 'bg-teter-dark text-white'
                        : 'bg-gray-100 text-teter-dark hover:bg-gray-200'
                    }`}
                    aria-pressed={specDivision === div.code}
                  >
                    {div.label}
                  </button>
                ))}
              </div>
            </div>

            {/* Date range */}
            <div className="flex items-end gap-2">
              <div className="flex flex-col gap-1">
                <label className="text-xs text-teter-gray-text font-medium">From</label>
                <input
                  type="date"
                  className="select"
                  value={dateFrom}
                  onChange={(e) => setDateFrom(e.target.value)}
                  aria-label="Date from"
                />
              </div>
              <div className="flex flex-col gap-1">
                <label className="text-xs text-teter-gray-text font-medium">To</label>
                <input
                  type="date"
                  className="select"
                  value={dateTo}
                  onChange={(e) => setDateTo(e.target.value)}
                  aria-label="Date to"
                />
              </div>
            </div>

            {/* Cluster toggle */}
            <button
              onClick={() => setClusterByFlaw((v) => !v)}
              className={`px-4 py-2 text-sm font-semibold rounded border transition-colors ${
                clusterByFlaw
                  ? 'bg-red-50 border-red-300 text-red-700'
                  : 'bg-white border-gray-200 text-teter-dark hover:bg-gray-50'
              }`}
            >
              {clusterByFlaw ? '✓ ' : ''}Cluster by Design Flaw
            </button>
          </div>

          {/* Legend */}
          <div className="flex flex-wrap gap-4 mt-3">
            {Object.entries(NODE_COLORS).map(([type, color]) => (
              <div key={type} className="flex items-center gap-1.5">
                <span
                  className="w-3 h-3 rounded-full shrink-0"
                  style={{ backgroundColor: color }}
                />
                <span className="text-xs text-teter-gray-text">
                  {type.replace(/_/g, ' ')}
                </span>
              </div>
            ))}
            <div className="flex items-center gap-1.5">
              <span className="w-6 h-0.5 shrink-0 bg-blue-400 rounded" />
              <span className="text-xs text-teter-gray-text">REFERENCES_SPEC</span>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="w-6 h-0.5 shrink-0 bg-red-400 rounded" />
              <span className="text-xs text-teter-gray-text">REVEALS</span>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="w-6 h-0.5 shrink-0 bg-green-400 rounded" />
              <span className="text-xs text-teter-gray-text">SUGGESTS</span>
            </div>
          </div>
        </div>
      </div>

      {/* Graph canvas area */}
      <div className="flex-1 overflow-hidden relative" ref={containerRef}>
        {loading && (
          <div className="absolute inset-0 z-10 flex items-center justify-center bg-[#1a1a2e]/80">
            <div className="flex flex-col items-center gap-3">
              <div className="w-8 h-8 border-4 border-teter-orange border-t-transparent rounded-full animate-spin" />
              <span className="text-white/70 text-sm">Loading graph…</span>
            </div>
          </div>
        )}

        {error && (
          <div className="absolute inset-0 z-10 flex items-center justify-center bg-[#1a1a2e]">
            <div className="bg-red-900/30 border border-red-500/50 rounded-lg p-6 text-center max-w-sm">
              <p className="text-red-400 font-semibold mb-1">Failed to load graph</p>
              <p className="text-red-300/70 text-sm">{error}</p>
            </div>
          </div>
        )}

        {!loading && !error && rawData && rawData.nodes.length === 0 && (
          <div className="absolute inset-0 z-10 flex items-center justify-center bg-[#1a1a2e]">
            <div className="text-center">
              <div className="text-5xl mb-4 opacity-30">◎</div>
              <p className="text-white/60 font-semibold">No graph data</p>
              <p className="text-white/40 text-sm mt-1">
                Approve some RFI tasks to populate the knowledge graph.
              </p>
            </div>
          </div>
        )}

        {!loading && !error && graphData.nodes.length > 0 && (
          <ForceGraph2D
            graphData={graphData}
            width={dims.width}
            height={dims.height}
            backgroundColor="#1a1a2e"
            nodeCanvasObject={paintNode}
            nodeCanvasObjectMode={() => 'replace'}
            nodeVal={(node) => {
              const connCount = (node as NodeObject & { _connCount: number })._connCount
              return NODE_BASE_RADIUS + Math.min(connCount * 1.5, 10)
            }}
            linkColor={getLinkColor}
            linkWidth={1.5}
            linkDirectionalArrowLength={4}
            linkDirectionalArrowRelPos={1}
            onNodeClick={handleNodeClick}
            onBackgroundClick={() => setSelectedNode(null)}
            cooldownTicks={clusterByFlaw ? 300 : 100}
            d3AlphaDecay={clusterByFlaw ? 0.01 : 0.02}
            d3VelocityDecay={clusterByFlaw ? 0.2 : 0.4}
            enableNodeDrag
          />
        )}
      </div>

      {/* Node detail panel */}
      {selectedNode && rawData && (
        <GraphNodeDetailPanel
          node={selectedNode}
          allNodes={rawData.nodes}
          edges={rawData.edges}
          onClose={() => setSelectedNode(null)}
        />
      )}
    </div>
  )
}
