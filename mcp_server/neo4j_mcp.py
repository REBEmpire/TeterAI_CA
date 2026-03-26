"""
TeterAI CA — Neo4j MCP Server

Exposes the project knowledge graph to Claude Code (and other MCP clients)
via the Model Context Protocol using STDIO transport.

Tools provided:
  query-rfi-patterns    — RFI × DesignFlaw × SpecSection graph for a project
  query-full-graph      — All doc types for a project (optional type filter)
  semantic-search       — Vector-similarity search across graph nodes
  project-stats         — Document counts and top patterns for a project

Usage (development):
    PYTHONPATH=src python -m mcp_server.neo4j_mcp

Usage (via .mcp.json in Claude Code):
    Configured automatically — see .mcp.json at the project root.
"""
import json
import sys
import os
import logging

logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Path setup: ensure src/ is on sys.path so knowledge_graph imports work
# ---------------------------------------------------------------------------

_here = os.path.dirname(os.path.abspath(__file__))
_src = os.path.join(os.path.dirname(_here), "src")
if _src not in sys.path:
    sys.path.insert(0, _src)

# ---------------------------------------------------------------------------
# Lazy KG client import (only after path is set)
# ---------------------------------------------------------------------------

def _get_kg():
    from knowledge_graph.client import kg_client
    return kg_client


# ---------------------------------------------------------------------------
# MCP server setup
# ---------------------------------------------------------------------------

try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp import types as mcp_types
except ImportError:
    print(
        json.dumps({"error": "mcp package not installed. Run: pip install mcp"}),
        file=sys.stderr,
    )
    sys.exit(1)


server = Server("teterai-neo4j")


# ---------------------------------------------------------------------------
# Tool: query-rfi-patterns
# ---------------------------------------------------------------------------

@server.list_tools()
async def list_tools() -> list[mcp_types.Tool]:
    return [
        mcp_types.Tool(
            name="query-rfi-patterns",
            description=(
                "Fetch the RFI pattern graph for a project: RFI nodes connected to "
                "DesignFlaw and SpecSection nodes. Use this to identify recurring "
                "design issues and which spec sections generate the most questions."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "string",
                        "description": "The project ID to query.",
                    },
                    "spec_division": {
                        "type": "string",
                        "description": "Optional CSI division prefix filter, e.g. '08'.",
                    },
                    "date_from": {
                        "type": "string",
                        "description": "Optional ISO date string (YYYY-MM-DD) for start of range.",
                    },
                    "date_to": {
                        "type": "string",
                        "description": "Optional ISO date string (YYYY-MM-DD) for end of range.",
                    },
                },
                "required": ["project_id"],
            },
        ),
        mcp_types.Tool(
            name="query-full-graph",
            description=(
                "Fetch the full project graph across all CA document types: "
                "RFI, Submittal, ScheduleReview, PayApp, CostAnalysis, Party, and SpecSection. "
                "Optionally filter to a single document type."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "string",
                        "description": "The project ID to query.",
                    },
                    "doc_type": {
                        "type": "string",
                        "description": (
                            "Optional filter: 'rfi', 'submittal', 'schedule_review', "
                            "'pay_app', or 'cost_analysis'."
                        ),
                    },
                },
                "required": ["project_id"],
            },
        ),
        mcp_types.Tool(
            name="semantic-search",
            description=(
                "Search the knowledge graph using natural language. Returns the most "
                "semantically similar RFI nodes to your query, ranked by relevance. "
                "Useful for finding precedents, similar issues, or related spec citations."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Natural language search query, e.g. 'glazing waterproofing issue'.",
                    },
                    "project_id": {
                        "type": "string",
                        "description": "Optional project ID to restrict the search.",
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "Number of results to return (default 10, max 50).",
                        "default": 10,
                    },
                },
                "required": ["query"],
            },
        ),
        mcp_types.Tool(
            name="project-stats",
            description=(
                "Return a summary of the knowledge graph for a project: document counts "
                "by type, unique parties, unique spec sections, and the top recurring "
                "design flaw categories."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "string",
                        "description": "The project ID to summarise.",
                    },
                },
                "required": ["project_id"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[mcp_types.TextContent]:
    kg = _get_kg()
    result: object

    try:
        if name == "query-rfi-patterns":
            result = kg.get_rfi_pattern_graph(
                project_id=arguments["project_id"],
                spec_division=arguments.get("spec_division"),
                date_from=arguments.get("date_from"),
                date_to=arguments.get("date_to"),
            )

        elif name == "query-full-graph":
            result = kg.get_full_project_graph(
                project_id=arguments["project_id"],
                doc_type_filter=arguments.get("doc_type"),
            )

        elif name == "semantic-search":
            result = kg.semantic_search_graph(
                query=arguments["query"],
                project_id=arguments.get("project_id"),
                top_k=int(arguments.get("top_k", 10)),
            )

        elif name == "project-stats":
            result = kg.get_project_graph_stats(project_id=arguments["project_id"])

        else:
            result = {"error": f"Unknown tool: {name}"}

    except Exception as e:
        result = {"error": str(e)}

    return [mcp_types.TextContent(type="text", text=json.dumps(result, default=str, indent=2))]


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def _main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    import asyncio
    asyncio.run(_main())
