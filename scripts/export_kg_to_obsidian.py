"""
Export a project's Knowledge Graph data to an Obsidian vault.

Pulls live data from Neo4j and writes interlinked markdown files so you can
open the folder in Obsidian and browse the actual document graph, parties,
RFIs, and timeline — including Graph View.

Usage:
    uv run python scripts/export_kg_to_obsidian.py --project-id 11900
    uv run python scripts/export_kg_to_obsidian.py --project-id 11900 --output ~/Desktop/TeterKG_Vault
    uv run python scripts/export_kg_to_obsidian.py --project-id 11900 --output ~/Desktop/TeterKG_Vault --open
"""
import sys
import os
import re
import argparse
from pathlib import Path
from collections import defaultdict

_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(_root, "src"))
sys.path.insert(0, _root)

# Load credentials from ~/.teterai/config.env before any service imports
from config.local_config import LocalConfig
LocalConfig.ensure_exists().push_to_env()

from knowledge_graph.client import KnowledgeGraphClient  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DOC_TYPE_SUBDIR = {
    "RFI": "RFIs",
    "Submittal": "Submittals",
    "SUBMITTAL": "Submittals",
    "Change Order": "Change Orders",
    "CHANGE_ORDER": "Change Orders",
    "CO": "Change Orders",
    "COR": "Change Orders",
    "POTENTIAL_CO": "Change Orders",
    "Pay Application": "Pay Applications",
    "PAY_APP": "Pay Applications",
    "Schedule": "Schedules",
    "Correspondence": "Correspondence",
    "Bulletin": "Bulletins",
    "Drawing": "Drawings",
}


def _safe(s: str, max_len: int = 80) -> str:
    """Sanitize a string for use as a filesystem filename."""
    s = re.sub(r'[\\/:*?"<>|]', "-", s or "")
    s = re.sub(r"\s+", " ", s).strip()
    return s[:max_len].rstrip(". ")


def _write_md(path: Path, frontmatter: dict, body: str) -> None:
    """Write a markdown file with YAML frontmatter."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["---"]
    for k, v in frontmatter.items():
        if v is None or v == "":
            lines.append(f"{k}:")
        elif isinstance(v, bool):
            lines.append(f"{k}: {str(v).lower()}")
        elif isinstance(v, (int, float)):
            lines.append(f"{k}: {v}")
        else:
            escaped = str(v).replace('"', '\\"')
            lines.append(f'{k}: "{escaped}"')
    lines.append("---")
    lines.append("")
    lines.append(body.strip())
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def _party_link(name: str) -> str:
    return f"[[Parties/{_safe(name)}]]"


def _spec_link(ref: str) -> str:
    return f"[[Spec Sections/{_safe(ref)}]]"


def _doc_type_subdir(doc_type: str) -> str:
    return _DOC_TYPE_SUBDIR.get(doc_type, _safe(doc_type or "Other", 40))


# ---------------------------------------------------------------------------
# Section writers
# ---------------------------------------------------------------------------

def write_project_overview(vault: Path, project_id: str, project_name: str,
                            project_number: str, intel: dict) -> None:
    total = intel.get("total_docs", 0)
    responded = intel.get("responded_docs", 0)
    rate = intel.get("response_rate", 0.0)
    party_count = intel.get("party_count", 0)
    earliest = intel.get("earliest_date") or "—"
    latest = intel.get("latest_date") or "—"
    meta_count = intel.get("metadata_only_count", 0)

    type_rows = "\n".join(
        f"| {dt} | {cnt} |"
        for dt, cnt in sorted(
            (intel.get("doc_counts_by_type") or {}).items(),
            key=lambda x: -x[1],
        )
    )

    body = f"""# {project_name}

**Project Number:** {project_number or "—"}
**Project ID:** {project_id}

## KPI Summary

| Metric | Value |
|--------|-------|
| Total Documents | {total} |
| Responded | {responded} ({rate:.0%}) |
| Metadata-Only (extraction failed) | {meta_count} |
| Contributing Parties | {party_count} |
| Date Range | {earliest} → {latest} |

## Documents by Type

| Document Type | Count |
|---------------|-------|
{type_rows}

## Navigation

- [[_Party Network]] — all parties and their submission volumes
- [[_Timeline]] — monthly document activity
"""

    fm = {
        "project_id": project_id,
        "project_number": project_number or "",
        "name": project_name,
        "total_docs": total,
        "response_rate": f"{rate:.1%}",
        "tags": "project-overview",
    }
    _write_md(vault / "_Project Overview.md", fm, body)


def write_timeline(vault: Path, timeline: dict) -> None:
    months = timeline.get("months", [])
    if not months:
        _write_md(vault / "_Timeline.md", {"tags": "timeline"}, "# Timeline\n\nNo timeline data found.")
        return

    all_types = sorted({dt for m in months for dt in m.get("counts", {})})
    header = "| Month | " + " | ".join(all_types) + " | Total |"
    sep = "|-------|" + "|-------" * len(all_types) + "|-------|"
    rows = []
    for m in months:
        counts = m.get("counts", {})
        total = sum(counts.values())
        vals = " | ".join(str(counts.get(dt, "")) for dt in all_types)
        rows.append(f"| {m['month']} | {vals} | {total} |")

    body = "# Document Timeline\n\n" + header + "\n" + sep + "\n" + "\n".join(rows)
    _write_md(vault / "_Timeline.md", {"tags": "timeline"}, body)


def write_party_network(vault: Path, party_network: dict) -> None:
    parties = party_network.get("parties", [])
    if not parties:
        _write_md(vault / "_Party Network.md", {"tags": "parties"}, "# Party Network\n\nNo party data found.")
        return

    rows = []
    for p in parties:
        name = p.get("name") or "Unknown"
        ptype = p.get("type") or "—"
        total = p.get("total_submissions", 0)
        breakdown = ", ".join(
            f"{s['doc_type']}: {s['count']}"
            for s in (p.get("submissions") or [])
        )
        rows.append(f"| {_party_link(name)} | {ptype} | {total} | {breakdown} |")

    body = (
        "# Party Network\n\n"
        "| Party | Type | Total Submissions | By Document Type |\n"
        "|-------|------|-------------------|------------------|\n"
        + "\n".join(rows)
    )
    _write_md(vault / "_Party Network.md", {"tags": "parties"}, body)


def write_party_files(vault: Path, party_network: dict) -> int:
    parties_dir = vault / "Parties"
    count = 0
    for p in party_network.get("parties", []):
        name = p.get("name") or "Unknown"
        ptype = p.get("type") or ""
        party_id = p.get("party_id") or ""
        total = p.get("total_submissions", 0)

        breakdown_rows = "\n".join(
            f"| {s['doc_type']} | {s['count']} |"
            for s in (p.get("submissions") or [])
        )

        body = f"""# {name}

**Type:** {ptype}
**Total Submissions:** {total}

## Submissions by Document Type

| Document Type | Count |
|---------------|-------|
{breakdown_rows}

> **Tip:** Open the Backlinks panel in Obsidian to see every document submitted by this party.
"""
        fm = {
            "party_id": party_id,
            "type": ptype,
            "total_submissions": total,
            "tags": "party",
        }
        _write_md(parties_dir / f"{_safe(name)}.md", fm, body)
        count += 1
    return count


def write_document_files(vault: Path, docs: list) -> int:
    """Write one .md per CADocument node."""
    count = 0
    for doc in docs:
        doc_type = doc.get("doc_type") or "Other"
        subdir = _doc_type_subdir(doc_type)

        doc_num = doc.get("doc_number") or ""
        filename = doc.get("filename") or "Unknown"
        short_name = _safe(filename, 60)
        fname = _safe(f"{doc_num} - {short_name}" if doc_num else short_name)

        summary = doc.get("summary") or "_No summary available._"
        date_sub = doc.get("date_submitted") or "—"
        date_resp = doc.get("date_responded") or "—"
        metadata_only = doc.get("metadata_only", False)
        phase = doc.get("phase") or "—"

        meta_warning = (
            "\n> ⚠️ **Metadata only** — text extraction failed or content was too short "
            "to analyse. Summary may be incomplete.\n"
            if metadata_only
            else ""
        )

        body = f"""# {filename}

**Document Type:** `{doc_type}`
**Document Number:** {doc_num or "—"}
**Phase:** {phase}
**Date Submitted:** {date_sub}
**Date Responded:** {date_resp}
{meta_warning}
## Summary

{summary}
"""
        fm = {
            "doc_type": doc_type,
            "doc_number": doc_num or None,
            "phase": phase,
            "date_submitted": date_sub,
            "date_responded": date_resp if date_resp != "—" else None,
            "metadata_only": metadata_only,
            "tags": doc_type.lower().replace(" ", "-"),
        }
        _write_md(vault / "Documents" / subdir / f"{fname}.md", fm, body)
        count += 1
    return count


def write_rfi_files(vault: Path, rfis: list) -> tuple:
    """Write one .md per RFI node. Returns (count, set_of_spec_refs)."""
    rfis_dir = vault / "Documents" / "RFIs"
    count = 0
    all_spec_refs: set = set()

    for rfi in rfis:
        rfi_num = str(rfi.get("rfi_number") or "???")
        question = rfi.get("question") or "_No question recorded._"
        response = rfi.get("response_text") or "_No response recorded._"
        status = rfi.get("status") or "Unknown"
        date_sub = rfi.get("date_submitted") or "—"
        contractor = rfi.get("contractor_name") or "—"
        spec_refs = rfi.get("referenced_spec_sections") or []
        source_file = rfi.get("source_file_name") or "—"

        for ref in spec_refs:
            all_spec_refs.add(ref)

        spec_links = (
            "  ".join(_spec_link(s) for s in spec_refs)
            if spec_refs
            else "_None recorded._"
        )

        # Truncate question to build a readable filename
        short_q = re.sub(r"\s+", " ", question).strip()[:50].rstrip()
        fname = _safe(f"RFI-{rfi_num} - {short_q}")

        body = f"""# RFI-{rfi_num}

**Status:** `{status}`
**Date Submitted:** {date_sub}
**Contractor:** {contractor}
**Source File:** {source_file}

## Question

{question}

## Response

{response}

## Referenced Spec Sections

{spec_links}
"""
        fm = {
            "rfi_number": rfi_num,
            "status": status,
            "date_submitted": date_sub,
            "contractor": contractor,
            "tags": "rfi",
        }
        _write_md(rfis_dir / f"{fname}.md", fm, body)
        count += 1

    return count, all_spec_refs


def write_spec_section_stubs(vault: Path, spec_refs: set) -> int:
    """Write a placeholder .md for each spec section referenced by RFIs."""
    specs_dir = vault / "Spec Sections"
    count = 0
    for ref in sorted(spec_refs):
        body = f"""# {ref}

> This spec section is referenced by one or more RFIs in this project.
>
> Open the **Backlinks** panel in Obsidian to see which RFIs cite this section.
"""
        fm = {"section_number": ref, "tags": "spec-section"}
        _write_md(specs_dir / f"{_safe(ref)}.md", fm, body)
        count += 1
    return count


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export a TeterAI_CA Knowledge Graph project to an Obsidian vault."
    )
    parser.add_argument(
        "--project-id",
        required=True,
        help='Neo4j project_id (e.g. "11900")',
    )
    parser.add_argument(
        "--output",
        default="./obsidian_kg_export",
        help="Output directory (default: ./obsidian_kg_export)",
    )
    parser.add_argument(
        "--open",
        action="store_true",
        help="Launch Obsidian via obsidian:// URI after export",
    )
    args = parser.parse_args()

    project_id = args.project_id
    vault = Path(args.output).expanduser().resolve()

    print(f"\nVault target : {vault}")
    print(f"Project ID   : {project_id}\n")

    kg = KnowledgeGraphClient()

    # Resolve project name from cross-project summary (avoids a raw Cypher call)
    print("Resolving project name...")
    project_name = f"Project {project_id}"
    project_number = ""
    cross = kg.get_cross_project_summary()
    for proj in cross.get("projects", []):
        if str(proj.get("project_id")) == str(project_id):
            project_name = proj.get("name") or project_name
            project_number = str(proj.get("project_number") or "")
            break

    print(f"  Found: {project_name} ({project_number})\n")

    print("Fetching project intelligence...")
    intel = kg.get_project_intelligence(project_id)
    if not intel:
        print(f"ERROR: No data found for project_id={project_id}.")
        print("  Check the project ID and ensure the KG has been ingested.")
        sys.exit(1)

    print("Fetching documents...")
    docs = kg.get_project_documents(project_id)

    print("Fetching RFIs...")
    rfis = kg.get_project_rfis(project_id)

    print("Fetching party network...")
    party_network = kg.get_party_network(project_id)

    print("Fetching timeline...")
    timeline = kg.get_document_timeline(project_id)

    # ------------------------------------------------------------------
    # Write vault
    # ------------------------------------------------------------------
    vault.mkdir(parents=True, exist_ok=True)
    print(f"\nWriting vault...\n")

    write_project_overview(vault, project_id, project_name, project_number, intel)
    print("  [OK]  _Project Overview.md")

    write_timeline(vault, timeline)
    print("  [OK]  _Timeline.md")

    write_party_network(vault, party_network)
    print("  [OK]  _Party Network.md")

    party_count = write_party_files(vault, party_network)
    print(f"  [OK]  {party_count} party files  ->  Parties/")

    doc_count = write_document_files(vault, docs)
    print(f"  [OK]  {doc_count} document files  ->  Documents/")

    rfi_count, spec_refs = write_rfi_files(vault, rfis)
    print(f"  [OK]  {rfi_count} RFI files  ->  Documents/RFIs/")

    spec_count = write_spec_section_stubs(vault, spec_refs)
    if spec_count:
        print(f"  [OK]  {spec_count} spec section stubs  ->  Spec Sections/")

    total = 3 + party_count + doc_count + rfi_count + spec_count
    print(f"\n  Done -- {total} files written to:\n  {vault}\n")

    print("To open in Obsidian:")
    print('  1. Open Obsidian -> "Open folder as vault"')
    print(f"  2. Select: {vault}")
    print("  3. Press Ctrl+G for Graph View\n")

    if args.open:
        import urllib.parse
        import subprocess
        uri = "obsidian://open?path=" + urllib.parse.quote(str(vault))
        try:
            if sys.platform == "win32":
                os.startfile(uri)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", uri])
            else:
                subprocess.Popen(["xdg-open", uri])
        except Exception as e:
            print(f"  Could not launch Obsidian automatically: {e}")
            print(f"  URI: {uri}")


if __name__ == "__main__":
    main()
