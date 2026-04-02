/**
 * KnowledgeGraphView — interactive force-directed graph of construction
 * documents clustered by relationships across all CA document types.
 *
 * Modes:
 *   "rfi_patterns"  — RFI × DesignFlaw × SpecSection (original Phase D view)
 *   "full_project"  — All types: RFI, Submittal, ScheduleReview, PayApp,
 *                     CostAnalysis, Party, SpecSection, DesignFlaw
 *
 * New features:
 *   - Doc-type filter pills (Full Project mode only)
 *   - Semantic search bar with node highlighting
 *   - Stats sidebar (collapsible)
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

interface SearchResult {
  node_id: string
  node_type: string
  label: string
  score: number
  properties: Record<string, string>
}

interface ProjectStats {
  rfi_count: number
  submittal_count: number
  schedule_review_count: number
  payapp_count: number
  cost_analysis_count: number
  unique_parties: number
  unique_spec_sections: number
  top_design_flaws: Array<{ category: string; count: number }>
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const NODE_COLORS: Record<string, string> = {
  SPEC_SECTION:      '#3b82f6', // blue
  RFI:               '#f97316', // orange (teter-orange)
  DESIGN_FLAW:       '#ef4444', // red
  CORRECTIVE_ACTION: '#22c55e', // green
  SUBMITTAL:         '#8b5cf6', // purple
  SCHEDULEREVIEW:    '#06b6d4', // teal
  PAYAPP:            '#84cc16', // lime
  COSTANALYSIS:      '#eab308', // yellow
  PARTY:             '#22d3ee', // cyan
}

const NODE_LABELS: Record<string, string> = {
  SPEC_SECTION:      'Spec Section',
  RFI:               'RFI',
  DESIGN_FLAW:       'Design Flaw',
  CORRECTIVE_ACTION: 'Corrective Action',
  SUBMITTAL:         'Submittal',
  SCHEDULEREVIEW:    'Schedule Review',
  PAYAPP:            'Pay App',
  COSTANALYSIS:      'Cost Analysis',
  PARTY:             'Party',
}

const EDGE_COLORS: Record<string, string> = {
  REFERENCES_SPEC: '#3b82f6',
  REVEALS:         '#ef4444',
  SUGGESTS:        '#22c55e',
  SUBMITTED_BY:    '#22d3ee',
  FULFILLS:        '#8b5cf6',
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

const DOC_TYPE_FILTERS = [
  { value: '',                label: 'All Types' },
  { value: 'rfi',             label: 'RFI' },
  { value: 'submittal',       label: 'Submittal' },
  { value: 'schedule_review', label: 'Schedule' },
  { value: 'pay_app',         label: 'Pay App' },
  { value: 'cost_analysis',   label: 'Cost Analysis' },
]

const BASE_URL = '/api/v1'

function getToken(): string | null {
  return localStorage.getItem('teterai_token')
}

function authHeaders() {
  const token = getToken()
  return {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  }
}

// ---------------------------------------------------------------------------
// API helpers
// ---------------------------------------------------------------------------

async function fetchRfiPatternGraph(
  projectId: string,
  specDivision: string,
  dateFrom: string,
  dateTo: string,
): Promise<RawGraphData> {
  const params = new URLSearchParams({ project_id: projectId })
  if (specDivision) params.set('spec_division', specDivision)
  if (dateFrom) params.set('date_from', dateFrom)
  if (dateTo) params.set('date_to', dateTo)
  const res = await fetch(`${BASE_URL}/knowledge-graph/rfi-patterns?${params}`, { headers: authHeaders() })
  if (!res.ok) throw new Error(`API error ${res.status}`)
  return res.json()
}

async function fetchFullGraph(
  projectId: string,
  docType: string,
): Promise<RawGraphData> {
  const params = new URLSearchParams({ project_id: projectId })
  if (docType) params.set('doc_type', docType)
  const res = await fetch(`${BASE_URL}/knowledge-graph/full-graph?${params}`, { headers: authHeaders() })
  if (!res.ok) throw new Error(`API error ${res.status}`)
  return res.json()
}

async function fetchSearch(
  query: string,
  projectId: string,
): Promise<SearchResult[]> {
  const params = new URLSearchParams({ q: query })
  if (projectId) params.set('project_id', projectId)
  const res = await fetch(`${BASE_URL}/knowledge-graph/search?${params}`, { headers: authHeaders() })
  if (!res.ok) throw new Error(`API error ${res.status}`)
  return res.json()
}

async function fetchStats(projectId: string): Promise<ProjectStats> {
  const res = await fetch(
    `${BASE_URL}/knowledge-graph/stats?project_id=${encodeURIComponent(projectId)}`,
    { headers: authHeaders() },
  )
  if (!res.ok) throw new Error(`API error ${res.status}`)
  return res.json()
}

// ---------------------------------------------------------------------------
// Helper: connection counts
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

  // Graph mode
  const [graphMode, setGraphMode] = useState<'rfi_patterns' | 'full_project'>('rfi_patterns')

  // RFI-patterns filters (only used in rfi_patterns mode)
  const [specDivision, setSpecDivision] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [clusterByFlaw, setClusterByFlaw] = useState(false)

  // Full-project filters (only used in full_project mode)
  const [docTypeFilter, setDocTypeFilter] = useState('')

  // Semantic search
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState<SearchResult[]>([])
  const [searchLoading, setSearchLoading] = useState(false)
  const [highlightedIds, setHighlightedIds] = useState<Set<string>>(new Set())

  // Stats sidebar
  const [showStats, setShowStats] = useState(false)
  const [stats, setStats] = useState<ProjectStats | null>(null)
  const [statsLoading, setStatsLoading] = useState(false)

  // Selected node (side panel)
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null)

  // Graph container dimensions
  const containerRef = useRef<HTMLDivElement>(null)
  const [dims, setDims] = useState({ width: 800, height: 600 })

  // Load projects
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
      if (entry) setDims({ width: entry.contentRect.width, height: entry.contentRect.height })
    })
    ro.observe(containerRef.current)
    return () => ro.disconnect()
  }, [])

  // Fetch graph data on filter/mode changes
  useEffect(() => {
    if (!selectedProject) return
    setLoading(true)
    setError(null)
    setSelectedNode(null)
    setHighlightedIds(new Set())
    setSearchResults([])

    const fetch =
      graphMode === 'full_project'
        ? fetchFullGraph(selectedProject, docTypeFilter)
        : fetchRfiPatternGraph(selectedProject, specDivision, dateFrom, dateTo)

    fetch
      .then(setRawData)
      .catch((err) => setError(err.message ?? 'Failed to load graph data.'))
      .finally(() => setLoading(false))
  }, [selectedProject, graphMode, docTypeFilter, specDivision, dateFrom, dateTo])

  // Fetch stats when project changes or stats panel opens
  useEffect(() => {
    if (!selectedProject || !showStats) return
    setStatsLoading(true)
    fetchStats(selectedProject)
      .then(setStats)
      .catch(() => setStats(null))
      .finally(() => setStatsLoading(false))
  }, [selectedProject, showStats])

  // Semantic search handler
  const handleSearch = useCallback(() => {
    if (!searchQuery.trim() || !selectedProject) return
    setSearchLoading(true)
    fetchSearch(searchQuery, selectedProject)
      .then((results) => {
        setSearchResults(results)
        // Build set of IDs that match so we can highlight them
        const ids = new Set(results.map((r) => `rfi_${r.node_id}`))
        setHighlightedIds(ids)
      })
      .catch(() => setSearchResults([]))
      .finally(() => setSearchLoading(false))
  }, [searchQuery, selectedProject])

  const handleSearchClear = useCallback(() => {
    setSearchQuery('')
    setSearchResults([])
    setHighlightedIds(new Set())
  }, [])

  // Build force-graph data
  const connCounts = rawData ? connectionCounts(rawData.nodes, rawData.edges) : {}

  const graphData = rawData
    ? {
        nodes: rawData.nodes.map((n) => ({
          ...n,
          _type: n.type,
          _label: n.label,
          _connCount: connCounts[n.id] ?? 0,
          _highlighted: highlightedIds.has(n.id),
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
      const n = node as NodeObject & { _type: string; _label: string; _connCount: number; _highlighted: boolean }
      const color = NODE_COLORS[n._type] ?? '#94a3b8'
      const radius = NODE_BASE_RADIUS + Math.min(n._connCount * 1.5, 10)

      // Highlight ring
      if (n._highlighted) {
        ctx.beginPath()
        ctx.arc(n.x ?? 0, n.y ?? 0, radius + 4, 0, 2 * Math.PI)
        ctx.fillStyle = 'rgba(255, 255, 255, 0.25)'
        ctx.fill()
        ctx.strokeStyle = '#ffffff'
        ctx.lineWidth = 2 / globalScale
        ctx.stroke()
      }

      // Node circle
      ctx.beginPath()
      ctx.arc(n.x ?? 0, n.y ?? 0, radius, 0, 2 * Math.PI)
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
        const text = n._label.length > 20 ? n._label.slice(0, 18) + '…' : n._label
        ctx.fillText(text, n.x ?? 0, n.y ?? 0)
      }
    },
    [highlightedIds],
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

  // Link color
  const getLinkColor = useCallback((link: LinkObject) => {
    const type = (link as LinkObject & { _type: string })._type
    return EDGE_COLORS[type] ?? '#94a3b8'
  }, [])

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div className="flex flex-col h-screen overflow-hidden bg-gray-50">
      {/* Page header */}
      <div className="bg-white border-b border-gray-200 px-6 py-4 shrink-0">
        <div className="max-w-wide mx-auto">

          {/* Title row */}
          <div className="flex items-center justify-between mb-3">
            <div>
              <h1 className="text-xl font-semibold text-teter-dark">Knowledge Graph</h1>
              <p className="text-sm text-teter-gray-text mt-0.5">
                {graphMode === 'rfi_patterns'
                  ? 'RFI patterns clustered by design flaw and spec section'
                  : 'Full project view across all document types'}
              </p>
            </div>
            <div className="flex items-center gap-3">
              {/* Stats toggle */}
              <button
                onClick={() => setShowStats((v) => !v)}
                className={`px-3 py-1.5 text-xs font-semibold rounded border transition-colors ${
                  showStats
                    ? 'bg-teter-dark text-white border-teter-dark'
                    : 'bg-white text-teter-dark border-gray-200 hover:bg-gray-50'
                }`}
              >
                {showStats ? '▶ Stats' : '▷ Stats'}
              </button>
              <div className="hidden sm:block w-1 h-8 bg-teter-orange rounded-sm" />
            </div>
          </div>

          {/* Graph mode toggle + project selector */}
          <div className="flex flex-wrap gap-3 items-end mb-3">
            {/* Mode pills */}
            <div className="flex gap-1">
              {(['rfi_patterns', 'full_project'] as const).map((mode) => (
                <button
                  key={mode}
                  onClick={() => setGraphMode(mode)}
                  className={`px-3 py-1.5 text-xs rounded-full font-semibold transition-colors ${
                    graphMode === mode
                      ? 'bg-teter-orange text-white'
                      : 'bg-gray-100 text-teter-dark hover:bg-gray-200'
                  }`}
                >
                  {mode === 'rfi_patterns' ? 'RFI Patterns' : 'Full Project'}
                </button>
              ))}
            </div>

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
          </div>

          {/* Filters — conditional by mode */}
          <div className="flex flex-wrap gap-3 items-end mb-3">
            {graphMode === 'rfi_patterns' && (
              <>
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
                    <input type="date" className="select" value={dateFrom}
                      onChange={(e) => setDateFrom(e.target.value)} aria-label="Date from" />
                  </div>
                  <div className="flex flex-col gap-1">
                    <label className="text-xs text-teter-gray-text font-medium">To</label>
                    <input type="date" className="select" value={dateTo}
                      onChange={(e) => setDateTo(e.target.value)} aria-label="Date to" />
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
              </>
            )}

            {graphMode === 'full_project' && (
              <div className="flex flex-col gap-1">
                <label className="text-xs text-teter-gray-text font-medium">Document Type</label>
                <div className="flex flex-wrap gap-1">
                  {DOC_TYPE_FILTERS.map((f) => (
                    <button
                      key={f.value}
                      onClick={() => setDocTypeFilter(f.value)}
                      className={`px-2.5 py-1 text-xs rounded-full font-medium transition-colors ${
                        docTypeFilter === f.value
                          ? 'bg-teter-dark text-white'
                          : 'bg-gray-100 text-teter-dark hover:bg-gray-200'
                      }`}
                      aria-pressed={docTypeFilter === f.value}
                    >
                      {f.label}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {/* Semantic search bar */}
            <div className="flex flex-col gap-1 ml-auto">
              <label className="text-xs text-teter-gray-text font-medium">Semantic Search</label>
              <div className="flex gap-1.5">
                <input
                  type="text"
                  placeholder="e.g. glazing curtain wall…"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
                  className="select w-52"
                  aria-label="Semantic search"
                />
                <button
                  onClick={handleSearch}
                  disabled={searchLoading || !searchQuery.trim()}
                  className="px-3 py-1.5 text-xs bg-teter-orange text-white font-semibold rounded hover:bg-orange-600 disabled:opacity-50 transition-colors"
                >
                  {searchLoading ? '…' : 'Search'}
                </button>
                {highlightedIds.size > 0 && (
                  <button
                    onClick={handleSearchClear}
                    className="px-2 py-1.5 text-xs bg-gray-100 text-teter-dark rounded hover:bg-gray-200 transition-colors"
                    aria-label="Clear search"
                  >
                    ✕
                  </button>
                )}
              </div>
              {highlightedIds.size > 0 && (
                <p className="text-xs text-teter-gray-text">
                  {highlightedIds.size} node{highlightedIds.size !== 1 ? 's' : ''} highlighted
                </p>
              )}
            </div>
          </div>

          {/* Legend */}
          <div className="flex flex-wrap gap-4">
            {Object.entries(NODE_COLORS).map(([type, color]) => (
              <div key={type} className="flex items-center gap-1.5">
                <span className="w-3 h-3 rounded-full shrink-0" style={{ backgroundColor: color }} />
                <span className="text-xs text-teter-gray-text">{NODE_LABELS[type] ?? type}</span>
              </div>
            ))}
            {Object.entries(EDGE_COLORS).map(([type, color]) => (
              <div key={type} className="flex items-center gap-1.5">
                <span className="w-6 h-0.5 shrink-0 rounded" style={{ backgroundColor: color }} />
                <span className="text-xs text-teter-gray-text">{type.replace(/_/g, ' ')}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Main content: graph + optional stats sidebar */}
      <div className="flex flex-1 overflow-hidden">
        {/* Graph canvas */}
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
                  {graphMode === 'rfi_patterns'
                    ? 'Approve some RFI tasks to populate the knowledge graph.'
                    : 'Approve documents across any CA type to build the full project graph.'}
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

          {/* Semantic search results overlay */}
          {searchResults.length > 0 && (
            <div className="absolute top-4 left-4 z-20 bg-[#1a1a2e]/95 border border-white/10 rounded-lg p-3 max-w-xs max-h-64 overflow-y-auto">
              <p className="text-white/60 text-xs font-semibold mb-2 uppercase tracking-wide">
                Search Results ({searchResults.length})
              </p>
              {searchResults.map((r) => (
                <div key={r.node_id} className="mb-2 pb-2 border-b border-white/5 last:border-0">
                  <div className="flex items-center gap-1.5 mb-0.5">
                    <span
                      className="w-2 h-2 rounded-full shrink-0"
                      style={{ backgroundColor: NODE_COLORS[r.node_type] ?? '#94a3b8' }}
                    />
                    <span className="text-white/80 text-xs font-medium">{r.label}</span>
                    <span className="text-white/30 text-xs ml-auto">{(r.score * 100).toFixed(0)}%</span>
                  </div>
                  {r.properties.question && (
                    <p className="text-white/40 text-xs pl-3.5 line-clamp-2">{r.properties.question}</p>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Stats sidebar */}
        {showStats && (
          <div className="w-64 shrink-0 bg-white border-l border-gray-200 overflow-y-auto p-4">
            <h2 className="text-sm font-semibold text-teter-dark mb-4">Project Stats</h2>

            {statsLoading && (
              <div className="flex justify-center py-8">
                <div className="w-5 h-5 border-2 border-teter-orange border-t-transparent rounded-full animate-spin" />
              </div>
            )}

            {!statsLoading && stats && (
              <>
                <div className="space-y-2 mb-4">
                  {[
                    { label: 'RFIs',             value: stats.rfi_count,            color: NODE_COLORS.RFI },
                    { label: 'Submittals',        value: stats.submittal_count,      color: NODE_COLORS.SUBMITTAL },
                    { label: 'Schedule Reviews',  value: stats.schedule_review_count,color: NODE_COLORS.SCHEDULEREVIEW },
                    { label: 'Pay Apps',          value: stats.payapp_count,         color: NODE_COLORS.PAYAPP },
                    { label: 'Cost Analyses',     value: stats.cost_analysis_count,  color: NODE_COLORS.COSTANALYSIS },
                    { label: 'Unique Parties',    value: stats.unique_parties,       color: NODE_COLORS.PARTY },
                    { label: 'Spec Sections',     value: stats.unique_spec_sections, color: NODE_COLORS.SPEC_SECTION },
                  ].map(({ label, value, color }) => (
                    <div key={label} className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ backgroundColor: color }} />
                        <span className="text-xs text-teter-gray-text">{label}</span>
                      </div>
                      <span className="text-xs font-semibold text-teter-dark">{value}</span>
                    </div>
                  ))}
                </div>

                {stats.top_design_flaws.length > 0 && (
                  <>
                    <div className="border-t border-gray-100 pt-3 mb-2">
                      <p className="text-xs font-semibold text-teter-dark mb-2">Top Design Flaws</p>
                    </div>
                    <div className="space-y-1.5">
                      {stats.top_design_flaws.map(({ category, count }) => (
                        <div key={category} className="flex items-center justify-between">
                          <span className="text-xs text-teter-gray-text truncate flex-1 pr-2">{category}</span>
                          <span
                            className="text-xs font-semibold px-1.5 py-0.5 rounded"
                            style={{ backgroundColor: `${NODE_COLORS.DESIGN_FLAW}20`, color: NODE_COLORS.DESIGN_FLAW }}
                          >
                            {count}
                          </span>
                        </div>
                      ))}
                    </div>
                  </>
                )}
              </>
            )}

            {!statsLoading && !stats && (
              <p className="text-xs text-teter-gray-text">No stats available.</p>
            )}
          </div>
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
