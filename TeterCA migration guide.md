# TeterAI_CA - IT Handoff & Migration Guide

## 1. System Overview

TeterAI_CA is an AI-powered multi-agent workflow automation system built for the Teter Construction Administration (CA) department. The prototype automates document workflows (RFI responses, Submittal reviews, Change Orders) from ingestion to final delivery.

**Crucial Note:** The system operates on a strictly **human-in-the-loop** model. AI agents draft responses and analyses, but a human user *must* approve all outputs via the UI before anything is sent externally. This ensures accuracy and maintains professional liability standards.

This document outlines the current prototype infrastructure, estimated costs, and deployment options to assist the Teter IT team in evaluating a company-wide migration to official Teter resources (likely AWS).

---

## 2. Current Architecture & Services

The prototype was developed rapidly using a mix of cloud services to minimize upfront infrastructure while proving the concept.

### 2.1 Backend API & AI Engine
*   **Framework:** Python (FastAPI).
*   **Package Manager:** `uv`.
*   **AI Integrations:** LiteLLM acts as the routing layer to multiple AI providers (Anthropic, Google, xAI). The system uses a tiered fallback architecture for reliability.

### 2.2 Frontend UI
*   **Stack:** React, TypeScript, Vite, Tailwind CSS.
*   **Deployment:** Currently bundled and served alongside the FastAPI backend, or run as a standalone desktop application.

### 2.3 Current Data & Hosting Services
*   **Knowledge Graph (KG):** **Neo4j Aura** (managed cloud instance). Stores document metadata, relationships (e.g., Projects to RFIs), and vector embeddings for semantic search.
*   **Relational Database:** **Supabase**. Handles structured application data (users, standard tables).
*   **Cloud Platform (GCP):** Currently leveraging Google Cloud Platform for:
    *   **Firestore:** Stores the Model Registry (AI model configuration).
    *   **Secret Manager:** Secures API keys and JWT session secrets.
    *   **Vertex AI:** Used for generating text embeddings (`text-embedding-004`).
*   **Document Ingestion:** **Google Drive & Gmail**. The system recursively ingests files from specific CA project folders.

---

## 3. Subscriptions & Estimated API Costs

The system relies on external AI providers. Below is the current subscription stack and estimated cost profile.

### Current Subscriptions
*   **Nous Research:** AI Harness for specialized model evaluation/routing.
*   **xAI (Grok):** Subscription for Tier 3 AI fallback.
*   **Anthropic (Claude):** Primary Tier 1 AI provider (e.g., Claude 3.5 Sonnet).
*   **Google AI / Vertex:** Tier 2 AI fallback and primary embedding generation.

### Estimated Costs
During the intensive building and testing phase (1 heavy user), API costs were roughly $75/month. For standard production use by CA staff, we estimate:

*   **Estimated API Cost per active user:** **~$50 / month**.
*   This covers document processing, RFI drafting, and Knowledge Graph embedding generation.

---

## 4. Deployment Options

The application was designed to be flexible. Teter IT has two primary paths for deployment:

### Option A: Web Application (Recommended for Scale)
The standard deployment model where the backend and frontend are hosted on company cloud infrastructure (e.g., AWS).
*   **Pros:** Centralized updates, easier to manage access for 150+ employees across 4 offices and remote locations, leverages existing cloud security perimeters.
*   **Cons:** Requires provisioning servers (e.g., EC2, ECS) and managing web domain routing.

### Option B: Local Desktop Application (WSL2 / Docker)
The application can run entirely on the user's local machine (Surface/Laptop) utilizing WSL2 or local Docker desktop. It still connects to cloud databases and AI APIs.
*   **Pros:** Zero centralized server hosting costs.
*   **Cons:** Harder to push updates; relies on the user's local machine performance; requires WSL2/Docker setup on company laptops.

---

## 5. Security & Data Privacy (API Usage Agreements)

Because we are sending proprietary company documents to external LLM providers, data privacy is paramount.
*   **Zero Data Retention/Training:** Our API subscriptions (Anthropic, Google GCP, xAI API) are configured under enterprise/API terms, which explicitly state that **customer data is NOT used to train their foundational models**.
*   *IT Action Item:* During migration, IT should verify that the official company API keys generated for these services are under the appropriate organizational/enterprise tiers that guarantee data privacy.

---

## 6. Migration Matrix (Prototype to AWS)

Since Teter primarily utilizes Amazon Web Services (AWS), below is a matrix outlining our current prototype services and the recommended AWS equivalents for IT to consider.

| Application Function | Current Prototype Service | Recommended AWS Alternative | Notes |
| :--- | :--- | :--- | :--- |
| **Backend / API Hosting** | Local / Custom VPS | **ECS (Fargate) or EC2** | Containerizing the FastAPI app is recommended. |
| **Frontend Hosting** | Served via FastAPI / Local | **S3 + CloudFront** | Static site hosting for the React/Vite build. |
| **Relational Database** | Supabase (PostgreSQL) | **Amazon RDS (PostgreSQL)** | Standard managed Postgres. |
| **Knowledge Graph** | Neo4j Aura (Cloud) | **Amazon Neptune / EC2 Neo4j** | Neptune supports graph, or we can self-host Neo4j Enterprise on EC2. |
| **Secret Management** | GCP Secret Manager | **AWS Secrets Manager** | Essential for storing AI API keys securely. |
| **NoSQL / Config Store** | GCP Firestore | **Amazon DynamoDB** | Used for the Model Registry. Easy migration. |
| **File Storage / Ingestion**| Google Drive API | **S3 / SharePoint API** | If Teter prefers to move away from G-Drive, integration with O365/SharePoint will need to be built. |
| **Embeddings** | GCP Vertex AI | **Amazon Bedrock / SageMaker** | We can swap the embedding model endpoint easily in the LiteLLM config. |
