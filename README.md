# TeterAI_CA

AI-powered multi-agent workflow automation system for the Teter Construction Administration (CA) department.

## Overview

TeterAI_CA is a multi-agent framework that automates the construction administration document workflow — from email ingest through classification, agent processing, human review, and final delivery. The system operates on a **human-in-the-loop** model: agents draft all outputs; humans approve before anything is sent externally.

**Design Principles:**
- Intuitive Interface — primary touchpoint is a unified web + mobile app
- Specification-Driven — agent behavior governed by a versioned knowledge graph
- Human-in-the-Loop — every output staged for human approval before external delivery
- Provider Agnostic — abstracted AI engine supports Claude, Google AI, and xAI
- Transparent Reasoning — all agent thought chains captured and auditable
- Continuous Learning — human corrections feed back into the knowledge graph

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                  Human Interface Layer                  │
│         Unified Web & Mobile App  |  Teams Bot          │
├─────────────────────────────────────────────────────────┤
│                    Workflow Layer                        │
│            Task Queue  |  Human Review Staging          │
├─────────────────────────────────────────────────────────┤
│                    Agent Framework                       │
│   Dispatcher  |  RFI  |  Submittal  |  CO Pipeline...   │
├─────────────────────────────────────────────────────────┤
│                    Knowledge Layer                       │
│     Neo4j 4-Tier Graph  +  Vector Embedding Overlay     │
├─────────────────────────────────────────────────────────┤
│                   Integration Layer                      │
│              Gmail API  |  Google Drive API              │
├─────────────────────────────────────────────────────────┤
│                     AI Engine                            │
│   Model Registry  |  Capability Classes  |  Fallback    │
├─────────────────────────────────────────────────────────┤
│                   Infrastructure (GCP)                   │
│     Cloud Run  |  Firestore  |  Cloud Scheduler         │
└─────────────────────────────────────────────────────────┘
```

**Stack:** Python · Google ADK · LiteLLM · React (web) · Flutter (mobile) · Neo4j Aura · GCP

---

## Repository Structure

```
TeterAI_CA/
├── specs/
│   ├── master/             # Master Project Specification (.docx)
│   ├── phase-0/            # Foundation component specs (10 specs)
│   ├── phase-1/            # Bid Phase + Core Construction specs
│   └── phase-2/            # Full Construction + Closeout specs
├── src/
│   ├── ai_engine/          # Model Registry, Capability Classes, Fallback Chain
│   ├── agents/
│   │   ├── dispatcher/     # Dispatcher Agent
│   │   └── rfi/            # RFI Agent (Construction Phase)
│   ├── knowledge_graph/    # Neo4j schema, seed data, query layer
│   ├── integrations/
│   │   ├── gmail/          # Gmail API polling + parsing
│   │   └── drive/          # Google Drive folder management
│   ├── workflow/           # Task queue, state machine, scheduler
│   └── ui/                 # Web (React) and mobile (Flutter) app
├── infrastructure/
│   └── gcp/                # Cloud Run, Firestore, Scheduler configs
└── tests/
```

---

## Development Phases

| Phase | Name | Key Deliverables | Status |
|-------|------|-----------------|--------|
| 0 | Foundation | AI Engine, Dispatcher, RFI Agent, Gmail/Drive integrations, Web App MVP, Knowledge Graph foundation | In Planning |
| 1 | Bid Phase + Core Construction | Pre-Bid RFI Agent, Bid Doc Processor, Submittal Reviewer, Change Order Pipeline | Not Started |
| 2 | Full Construction + Closeout | Remaining construction agents, Closeout Doc Reviewer | Not Started |
| 3 | Scale & Optimize | Performance tuning, additional agent specializations, Teams Bot enhancement | Not Started |

---

## Phase 0 Component Specifications

| Spec ID | Component | File |
|---------|-----------|------|
| TETER-CA-AI-AEC-001 | AI Engine Configuration | [AEC-001](specs/phase-0/TETER-CA-AI-AEC-001_AI-Engine-Configuration.md) |
| TETER-CA-AI-KG-001 | Knowledge Graph Architecture | [KG-001](specs/phase-0/TETER-CA-AI-KG-001_Knowledge-Graph-Architecture.md) |
| TETER-CA-AI-SEC-001 | Security & Access Control | [SEC-001](specs/phase-0/TETER-CA-AI-SEC-001_Security-Access-Control.md) |
| TETER-CA-AI-AUDIT-001 | Audit Trail & Logging | [AUDIT-001](specs/phase-0/TETER-CA-AI-AUDIT-001_Audit-Trail-Logging.md) |
| TETER-CA-AI-INT-GMAIL-001 | Gmail Integration | [INT-GMAIL-001](specs/phase-0/TETER-CA-AI-INT-GMAIL-001_Gmail-Integration.md) |
| TETER-CA-AI-INT-DRIVE-001 | Google Drive Structure | [INT-DRIVE-001](specs/phase-0/TETER-CA-AI-INT-DRIVE-001_Drive-Structure.md) |
| TETER-CA-AI-WF-001 | Task Queue & Workflow Engine | [WF-001](specs/phase-0/TETER-CA-AI-WF-001_Task-Queue-Workflow-Engine.md) |
| TETER-CA-AI-AGT-DISPATCH-001 | Dispatcher Agent | [AGT-DISPATCH-001](specs/phase-0/TETER-CA-AI-AGT-DISPATCH-001_Dispatcher-Agent.md) |
| TETER-CA-AI-AGT-RFI-001 | RFI Agent (Construction) | [AGT-RFI-001](specs/phase-0/TETER-CA-AI-AGT-RFI-001_RFI-Agent.md) |
| TETER-CA-AI-UI-001 | Unified Web & Mobile App | [UI-001](specs/phase-0/TETER-CA-AI-UI-001_Unified-Web-Mobile-App.md) |

---

## Phase 0 Success Criteria

One complete end-to-end workflow:

**Email Ingest → Classification → Agent Processing → Human Review → Delivery**

Proven with a single RFI from a contractor: email received, classified, processed by RFI Agent, draft staged for CA staff review, approved, and sent.

---

## Master Specification

Full project specification: [`specs/master/TETER-CA-AI-MPS-001 v0.2.0 Master Project Specification.docx`](specs/master/TETER-CA-AI-MPS-001%20v0.2.0%20Master%20Project%20Specification.docx)
