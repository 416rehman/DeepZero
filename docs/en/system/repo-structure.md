---
layout: default
title: Repository Structure
order: 2
---

## Repository Structure

```text
src/deepzero/
├── __init__.py          # SemVer definitions
├── __main__.py          # Module entrypoint
├── cli.py               # Click application interface
├── api/                 # Starlette REST endpoints
├── engine/              # Core execution and orchestration logic
│   ├── backends/        # Pluggable LLM backends, resolved by model scheme
│   └── report.py        # Builds the browsable report from run state
└── stages/              # Standard library processors

processors/              # Contributed and reference processors
├── ghidra_decompile/    # Ghidra headless decompiler (Map)
├── git_ingest/          # Git repository discovery and cloning (Ingest)
├── loldrivers_filter/   # loldrivers.io hash exclusion filter (Map)
├── pe_ingest/           # PE header parser and driver metadata extractor (Ingest)
└── semgrep_scanner/     # Semgrep batch scanner (BulkMap)

pipelines/               # Pipeline declarations and logic
├── loldrivers/          # BYOVD kernel driver research
└── source_audit/        # Source code audit over git repositories

docs/                    # Jekyll-based GitHub Pages documentation
tests/                   # Pytest validation suite
```

Each pipeline directory holds its `pipeline.yaml`, the Jinja prompt templates its LLM
stages render, and the semgrep rules its scan stage loads. Nothing outside that
directory has to change to add one, which is the point: `pipelines/` and `processors/`
are read by path, not registered in code.
