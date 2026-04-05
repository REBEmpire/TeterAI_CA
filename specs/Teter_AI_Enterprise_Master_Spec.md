# Teter A/E AI HUB: Project Master Spec

## 1. Executive Summary & Core Philosophy

The **Teter A/E AI HUB** is an enterprise-wide, multi-agent AI platform designed to serve all 150 employees of Teter, an ESOP architectural and engineering firm.

Building upon the success of the initial TeterAI_CA (Construction Administration) and BPR&D pilot projects, this platform scales the AI integration across 15 distinct departments. The core philosophy driving this architecture is **elegant efficiency and extreme accuracy ("dead nuts accurate")**. It is designed to be highly secure, seamlessly integrated into existing workflows, and free of the "crossed wires" and technical debt typical of complex integrations.

The AI Hub acts as a centralized orchestrator (Hermes) that provides role-specific "Co-Pilots" to each department, while maintaining a unified knowledge base where any employee can access any tool when appropriate.

## 2. Core Infrastructure & Deployment

To maintain absolute security and workflow continuity, the AI infrastructure is decoupled from the firm's primary data storage.

*   **File System (Source of Truth):** SharePoint. Teter retains full control, and the existing structure is *never* altered by the AI.
*   **Communications Integration:** Deep integration with Microsoft Outlook and Microsoft Teams.
*   **Deployment Platform:** Centralized CIO Cloud running a Windows 11 environment.
*   **AI Runtime Home:** WSL2 (Windows Subsystem for Linux 2) Service hosted on the CIO Cloud.
*   **Agent Framework:** **Hermes** — A highly customized, centralized agent harness/orchestrator.
*   **User Interface:** Seamless integration with the existing Teter A/E desktop UI.
*   **AI Model Providers:** A flexible, tiered routing system utilizing xAI (Grok), Google Gemini, Anthropic Claude, local models, and Google Cloud hosted models based on task capability.

## 3. Data Transfer & Optimization Strategy ("Copy-and-Optimize")

Teter’s live file system remains untouched. The system uses a strict "copy-and-optimize" approach to protect original project files while providing the AI with clean, high-fidelity data.

1.  **Detection:** The system detects new files arriving in SharePoint.
2.  **Transfer:** A read-only copy is automatically transferred to the isolated WSL2 environment.
3.  **Processing & Optimization:**
    *   **Small Documents** (RFIs, submittals, daily reports, small specs): Automatically analyzed, indexed, and ingested directly into the Knowledge Graph.
    *   **Large Documents** (Product data, manufacturer guides, code references, full drawing sets): Processed, chunked, and optimized specifically for rapid AI ingestion and precise semantic retrieval.

## 4. Hermes Agent Framework (The 15 Departments)

The Hermes framework provides 15 specialized Primary Agents ("Role-Specific Co-Pilots"). While agents are "fine-tuned" for their specific department, the overarching rule is cross-departmental access: **all employees work on all projects and have access to all primary agent tools when appropriate.**

### Executive & Design Disciplines
1.  Executive Team (EMT)
2.  Public Sector Architecture
3.  Private Sector Architecture
4.  Healthcare Architecture
5.  Interior Design

### Technical & Engineering Disciplines
6.  Structural Engineering
7.  Mechanical Engineering
8.  Electrical Engineering

### Construction & Project Delivery Disciplines
9.  Construction Administration (Module 1 - Baseline)
10. Specification Writer
11. Building Code Expert ("Bureaucracy Navigator")
12. Building a Better Valley (Firm-wide initiative / project tag)

### Support Disciplines
13. Marketing
14. Accounting
15. Human Resources
16. Information Technology (Note: Listed as 16th in raw spec, integrated as core support).

## 5. Memory & Knowledge Layers

The AI Hub utilizes a sophisticated, multi-layered memory architecture powered by Vector Databases and Neo4j Knowledge Graphs (`.md` file representations).

*   **Teter Corporate Knowledge Base:** Firm-wide standards, templates, and historical data.
*   **Primary Agents Layer:** Role-specific memory and specialized operational heuristics.
*   **Individual Projects Layer:** Knowledge graphs isolated to specific ongoing and past projects.
*   **Individual Employees Layer:** User-specific preferences and personalized interaction histories.
*   **Research Layer:** General architectural/engineering reference data.
*   **Custom / OS-Specific Knowledge:** Bespoke knowledge graphs.

## 6. Human-in-the-Loop (HITL) & Approval Workflows

The AI Hub adheres to a strict Human-in-the-Loop (HITL) governance model. AI agents *draft* outputs, but human professionals must approve them before external delivery.

*   **Baseline Workflow:** The CA department's split-pane review and approval UI serves as the foundation.
*   **Customizable Sign-offs:** Because different departments have different liability profiles, the system supports customized sign-off requirements (e.g., multi-manager approvals for Structural Engineering vs. single approval for Marketing drafts).

## 7. Next-Level Enhancements (Quick Wins)

To immediately elevate the platform's value beyond basic text processing, the following enhancements are prioritized:

1.  **BIM/Revit Integration Layer:** Enable agents to pull model data directly from Revit files, bridging the gap between 2D documents and 3D models.
2.  **Security & Compliance Framework:** Implement robust SOC-2 compliance measures, strict client data isolation protocols, and comprehensive audit logging (via Firestore).
3.  **Construction Field Photo Protocol:** Implement multimodal image analysis. Agents will auto-analyze field photos (e.g., concrete defects, structural issues) and output actionable repair sketches or marked-up specification documents.
