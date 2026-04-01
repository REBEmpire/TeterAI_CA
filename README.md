# TeterAI_CA

AI-powered multi-agent workflow automation system for the Teter Construction Administration (CA) department.

## Overview

TeterAI_CA is a multi-agent framework that automates the construction administration document workflow — from email ingest through classification, agent processing, human review, and final delivery. The system operates on a **human-in-the-loop** model: agents draft all outputs; humans approve before anything is sent externally.

## Features

### Core CA Workflow (Phases 0–3)
- **Dispatcher Agent** — classifies incoming documents from Gmail/Drive and routes to tool agents
- **RFI Agent** — drafts RFI responses using project knowledge and spec references
- **Submittal Review Agent** — multi-model parallel review of submittal packages with red-team critique
- **Change Order / Pay App agents** — cost document processing and analysis
- **Human review UI** — split-pane viewer for approving/rejecting/escalating AI drafts
- **Full audit trail** — every AI action logged to Firestore

### Knowledge Graph (Phase D)
- **Drive → Neo4j ingestion** — recursively ingests all CA documents from Google Drive into Neo4j Aura
- 584+ documents across 5 pilot projects with Vertex AI embeddings (`text-embedding-004`, 768-dim)
- `CADocument`, `Project`, `Party`, `RFI`, `SpecSection` node types with vector indexes

### Project Intelligence Dashboard (Phase E)
- **KPI cards** — total docs, response rates, party counts per project
- **Inline SVG charts** — document type breakdown, monthly activity timeline
- **Party network table** — who's submitting what, ranked by volume
- **AI health narrative** — Claude-generated project status summary from KG data
- **Cross-project comparison** — all 5 pilot projects side-by-side

### Pre-Bid Lessons Learned (Phase F)
- **Semantic search** — describe a design concern and find historically similar RFIs/Change Orders
- **Hotspot analysis** — see which doc types generated the most issues in source projects
- **AI pre-bid checklist** — Claude synthesises findings into actionable design review items
- Helps the design team eliminate known CA problem areas before bid documents go out

### Planned
- **Document Intelligence Service (Phase G)** — chunk spec books and drawing sets into
  searchable `SpecSection`/`DrawingSheet` nodes for precise agent content retrieval

## Setup Instructions

This project uses `uv` for fast dependency management.

1. Install `uv`: `curl -LsSf https://astral.sh/uv/install.sh | sh`
2. Run `uv sync` to install dependencies.
3. Obtain a GCP Service Account JSON key with `Cloud Datastore User`, `Secret Manager Secret Accessor`, and `roles/aiplatform.user` roles.
4. Save the key locally as `gcp-credentials.json` (this file is gitignored).
5. Set your environment variable: `export GOOGLE_APPLICATION_CREDENTIALS="gcp-credentials.json"`
6. Set Neo4j connection variables: `NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD`
7. Run tests: `uv run pytest tests/`

## Documentation

- **`CLAUDE.md`** — comprehensive architecture reference for AI assistants and developers
- **`docs/superpowers/specs/`** — feature design specs for each development phase
- **`specs/phase-0/`** — original phase-0 system specifications
