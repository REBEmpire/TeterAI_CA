/**
 * Minimal type declaration for react-force-graph-2d.
 * The package ships its own types but they can conflict with strict TS setups —
 * this shim provides just enough to satisfy the KnowledgeGraphView usage.
 */
declare module 'react-force-graph-2d' {
  import React from 'react'

  export interface NodeObject {
    id: string | number
    x?: number
    y?: number
    [key: string]: unknown
  }

  export interface LinkObject {
    source: string | number | NodeObject
    target: string | number | NodeObject
    [key: string]: unknown
  }

  export interface GraphData {
    nodes: NodeObject[]
    links: LinkObject[]
  }

  export interface ForceGraphProps {
    graphData: GraphData
    width?: number
    height?: number
    backgroundColor?: string
    nodeLabel?: string | ((node: NodeObject) => string)
    nodeColor?: string | ((node: NodeObject) => string)
    nodeVal?: number | string | ((node: NodeObject) => number)
    nodeCanvasObject?: (node: NodeObject, ctx: CanvasRenderingContext2D, globalScale: number) => void
    nodeCanvasObjectMode?: string | ((node: NodeObject) => string)
    linkColor?: string | ((link: LinkObject) => string)
    linkWidth?: number | ((link: LinkObject) => number)
    linkDirectionalArrowLength?: number | ((link: LinkObject) => number)
    linkDirectionalArrowRelPos?: number
    linkLabel?: string | ((link: LinkObject) => string)
    onNodeClick?: (node: NodeObject, event: MouseEvent) => void
    onBackgroundClick?: (event: MouseEvent) => void
    cooldownTicks?: number
    d3AlphaDecay?: number
    d3VelocityDecay?: number
    enableNodeDrag?: boolean
  }

  const ForceGraph2D: React.FC<ForceGraphProps>
  export default ForceGraph2D
}
