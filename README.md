# TeterAI_CA

AI-powered multi-agent workflow automation system for the Teter Construction Administration (CA) department.

## Overview

TeterAI_CA is a multi-agent framework that automates the construction administration document workflow — from email ingest through classification, agent processing, human review, and final delivery. The system operates on a **human-in-the-loop** model: agents draft all outputs; humans approve before anything is sent externally.

## Setup Instructions

This project uses `uv` for fast dependency management.

1. Install `uv`: `curl -LsSf https://astral.sh/uv/install.sh | sh`
2. Run `uv sync` to install dependencies.
3. Obtain a GCP Service Account JSON key with `Cloud Datastore User` and `Secret Manager Secret Accessor` roles.
4. Save the key locally as `gcp-credentials.json` (this file is gitignored).
5. Set your environment variable: `export GOOGLE_APPLICATION_CREDENTIALS="gcp-credentials.json"`
6. Run tests: `uv run pytest tests/`
