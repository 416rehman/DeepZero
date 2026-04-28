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
└── stages/              # Standard library processors

processors/              # Contributed and reference processors
pipelines/               # Pipeline declarations and logic
tests/                   # Pytest validation suite
```
