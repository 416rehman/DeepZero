# DeepZero

> Configurable, agentic vulnerability research pipeline

DeepZero is an extensible, breadth-first framework for automated binary analysis. It orchestrates configurable toolchains-file discovery, GHIDRA decompilation, Semgrep pattern matching, and LLM-powered context assessment-against any binary target. 

Powered by a **File-Ledger Engine**, DeepZero was built to handle massive uncurated corpora (e.g., thousands of Windows kernel drivers) seamlessly through a robust file-based database, fast resume capabilities, and atomic synchronization barriers.

## Key Features

- **Breadth-First Engine** - executes highly parallelized Map/Reduce/Batch primitives across large corpora in lockstep.
- **Agentic File-Ledger (File-DB)** - zero dependencies; the entire pipeline state is cleanly serialized to `work/` with a global `run_manifest.json`, namespaced tool history, and LLM-ready `context.md` files.
- **Fast, Idempotent Resume** - process a 12,000-file corpus, kill the pipeline, and instantly resume it with zero re-ingestion overhead. Completed states are skipped automatically.
- **Pipeline-as-YAML** - hook up built-in tools or custom Python classes rapidly without modifying the core engine.
- **Hardened for Scale** - atomic file writes with EDR/AV evasion retries, `ProcessGroupKills` for runaway GHIDRA JVMs, process isolation, and poison pill exception handling.
- **Batch Processing** - massive performance boosts using `os.link` temp-copy patterns to scan 500 decompiled drivers instantly in a single Semgrep invocation.
- **Any LLM Provider** - completely abstracted via LiteLLM.

## Quick Start

```bash
# install via pip
pip install deepzero

# run the loldrivers pipeline against your local directory
deepzero run ./drivers/ --pipeline loldrivers --model vertex_ai/gemini-2.5-pro

# check status of the run
deepzero status -p loldrivers

# resume after interruption (instantly skips everything already cached)
deepzero resume -p loldrivers
```

## Architecture: Polymorphic Tool Primitives

DeepZero V2 enforces strict tool interfaces that allow for powerful pipeline semantics:

| Primitive | Operation | Description |
|-----------|-----------|-------------|
| **IngestTool** | 1:N | Discovery phase. Emits `Sample` instances (e.g., PE parsing & hash extraction). |
| **MapTool** | 1:1 | Parallelized 1:1 worker (filters, decompilers, generic commands, LLM renderers). |
| **BatchTool** | N:Batch | Evaluates all active samples via a single external invocation (e.g., Semgrep). |
| **ReduceTool**| N:K | Synchronization barrier used for sorting or truncating the corpus (e.g., `top_k` ranking). |

## File Database Structure

No heavy databases needed. Everything is transparent to the user and accessible to LLM agents:

```
work/<pipeline_name>/
├── run_manifest.json          # Global fast-index of current active/skipped/failed samples
└── samples/
    └── <sample_id>/           # Safe, truncated SHA256 (e.g. 132fd1b8)
        ├── state.json         # Strict namespaced execution ledger (history.<tool>.data)
        ├── context.md         # Auto-generated sync barrier artifact for the LLM
        └── decompiled/        # Work-in-progress artifacts cleanly isolated
```

## Built-in Tools

Available natively off-the-shelf and addressable by bare names in `pipeline.yaml`:
- `file_discovery` - Fast local filesystem crawler.
- `metadata_filter` - Declarative thresholding, checking, and deduping.
- `hash_exclude` - Filter by list or file.
- `generic_command` - Universal shell escape hatch.
- `ghidra_decompile` - Headless GHIDRA integration with extraction script support.
- `semgrep_scanner` - High-performance batched symlink/hardlink rule runner.
- `top_k` - Sort active corpus by any nested `stage.metric` and truncate losers.
- `generic_llm` - Jinja2-rendered structured context builder for LiteLLM.

## CLI Commands

```
deepzero run <target>       - run a pipeline
deepzero resume             - resume an interrupted/killed run
deepzero status             - show run progress and sample outcomes
deepzero interactive        - LLM-backed analysis REPL
deepzero serve              - start REST API (requires deepzero[serve])
deepzero validate <path>    - syntax validity check for pipelines
deepzero list-tools         - list registered Python tools
deepzero init <name>        - scaffold a new pipeline
```

## License

MIT
