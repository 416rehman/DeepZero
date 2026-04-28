---
layout: default
title: LOLDrivers Pipeline
order: 3
---

## LOLDrivers Pipeline Reference

A reference BYOVD (Bring Your Own Vulnerable Driver) pipeline is maintained in `pipelines/loldrivers/`.

1. **discover:** PE ingestion and LIEF header parsing.
2. **kernel_filter:** Constraints processing to kernel-mode drivers exposing IOCTL surfaces.
3. **loldrivers_filter:** Excludes known entities cataloged via loldrivers.io.
4. **decompile:** Executes Ghidra headless decompilation.
5. **semgrep_scanner:** Bulk static analysis against exported C source.
6. **pick_top_10:** Heuristic reduction to top candidate tier.
7. **assess:** LLM prompt injection and logical assessment.
