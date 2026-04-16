<div align="center">
  <h1>DeepZero</h1>
  <p><b>Agentic Pipeline for Automated Vulnerability Research & Zero-Day Discovery</b></p>
  <p>
    <a href="https://github.com/416rehman/DeepZero/actions"><img src="https://img.shields.io/github/actions/workflow/status/416rehman/DeepZero/ci.yml?branch=main" alt="Build Status"></a>
    <a href="https://pypi.org/project/deepzero/"><img src="https://img.shields.io/pypi/v/deepzero" alt="PyPI - Version"></a>
    <a href="https://pypi.org/project/deepzero/"><img src="https://img.shields.io/pypi/pyversions/deepzero" alt="PyPI - Python Version"></a>
    <a href="https://github.com/416rehman/DeepZero/blob/main/LICENSE"><img src="https://img.shields.io/github/license/416rehman/DeepZero" alt="License"></a>
  </p>
</div>

---

**DeepZero** is an agentic pipeline engine for automated vulnerability research and zero-day discovery. It provides the scaffolding to turn raw binary corpora into ranked, LLM-assessed vulnerability candidates at scale without babysitting.

The engine is fully **platform and target agnostic**. Whether you're hunting bugs in kernel drivers, firmware images, native executables, or anything else that can be ingested and transformed, DeepZero handles orchestration. You supply the analysis logic as composable processors; DeepZero handles parallelism, fault tolerance, and state.

It enforces a **State Ledger Architecture**, writing execution state intrinsically to the local filesystem. Every run is fully idempotent: interrupt a scan across tens of thousands of samples and `deepzero resume` picks up exactly where it left off without re-processing or data loss.

---

## ⚡ Architecture

DeepZero organizes any analysis workload into four processor primitives running across horizontal queues:

| Type | Cardinality | Purpose |
|------|------------|---------|
| **Ingest** | `1 → N` | Discover and yield samples from a target source |
| **Map** | `1 → 1` | Isolated per-sample transforms, parallelized via thread pool |
| **BulkMap** | `N → batch` | Single external process invocation across all active samples |
| **Reduce** | `N → N` | Synchronization barrier: ranking, top-k selection, deduplication |

---

## 📦 Installation

DeepZero requires **Python 3.11+**.

```bash
git clone https://github.com/416rehman/DeepZero.git
cd DeepZero

# Install with all optional extras
pip install -e ".[full]"

# Or install only what you need
pip install -e ".[llm]"    # LLM support via litellm
pip install -e ".[pe]"     # PE header parsing
pip install -e ".[serve]"  # REST API server

# Copy and populate environment variables
cp .env.example .env
```

---

## 🚀 Running Pipelines

```bash
# Run a pipeline against a target directory or file
deepzero run ./targets -p loldrivers

# Resume after an interruption
deepzero resume -p loldrivers

# Check run status
deepzero status -p loldrivers

# Validate a pipeline definition without executing it
deepzero validate loldrivers

# List all registered built-in processors
deepzero list-processors

# Scaffold a new pipeline
deepzero init my_pipeline

# LLM-backed interactive analysis REPL over current run data
deepzero interactive -m openai/gpt-4o

# Start the REST API server
deepzero serve --host 127.0.0.1 --port 8420 -w work/
```

---

## 🛠 Anatomy of a Pipeline (YAML)

```yaml
name: my_vuln_pipeline
description: custom vulnerability research pipeline
version: "1.0"

# LiteLLM model string — required for any generic_llm stage
model: openai/gpt-4o

settings:
  work_dir: work
  max_workers: 4

stages:
  # Stage 1: must always be an IngestProcessor
  - name: discover
    processor: file_discovery       # bare name = built-in processor
    config:
      extensions: ["*"]
      recursive: true

  # Stage 2: 1:1 per-sample filter
  - name: filter
    processor: metadata_filter
    config:
      require:
        is_executable: true
      dedup_field: sha256

  # Stage 3: external processor from processors/ directory
  - name: decompile
    processor: my_decompiler/my_decompiler.py
    parallel: 0         # 0 = use max_workers from settings
    timeout: 300
    on_failure: skip    # skip | retry | abort
    config:
      tool_path: ${DECOMPILER_PATH}   # env-var expansion

  # Stage 4: bulk external tool (one process, all samples)
  - name: scan
    processor: semgrep_scanner/semgrep_scanner.py
    config:
      min_findings: 1
      rules_dir: pipelines/my_vuln_pipeline/rules

  # Stage 5: reduce — keep top candidates
  - name: pick_top_20
    processor: top_k
    config:
      metric_path: "scan.finding_count"
      keep_top: 20
      sort_order: desc

  # Stage 6: LLM deep analysis
  - name: assess
    processor: generic_llm
    parallel: 2
    on_failure: skip
    config:
      prompt: pipelines/my_vuln_pipeline/prompt.j2
      output_file: assessment.md
      classify_by: "\\[VULNERABLE\\]|\\[SAFE\\]"
      max_context_tokens: 900000
      max_retries: 3
```

**Processor reference formats:**

```yaml
processor: metadata_filter                  # built-in (bare name)
processor: my_dir/my_proc.py               # processors/my_dir/my_proc.py
processor: my_dir/my_proc.py:MyClass       # specific class in that file
processor: my.python.module:MyClass        # dotted Python import path
```

---

## 🔧 Built-in Processors

| Name | Type | Description |
|------|------|-------------|
| `file_discovery` | Ingest | Generic file finder by extension |
| `metadata_filter` | Map | Field equality, min/max thresholds, deduplication |
| `hash_exclude` | Map | SHA256 blocklist filter |
| `generic_llm` | Map | Jinja2 prompt → LLM → optional regex classification |
| `generic_command` | Map | Run any shell command as a pipeline stage |
| `top_k` | Reduce | Keep top N samples by a numeric metric from any upstream stage |
| `sort` | Reduce | Reorder samples by a numeric metric (no filtering) |

Run `deepzero list-processors` to see all registered processors with their types.

---

## 🔌 Building Processors

Subclass one of the four base classes from `deepzero.engine.stage`:

```python
from deepzero.engine.stage import MapProcessor, ProcessorContext, ProcessorEntry, ProcessorResult
from dataclasses import dataclass

class MyAnalyzer(MapProcessor):
    description = "custom analysis processor"

    @dataclass
    class Config:
        output_name: str = "result.json"
        threshold: float = 0.5

    def validate(self, ctx: ProcessorContext) -> list[str]:
        # Called at pipeline load time — return errors or []
        return []

    def setup(self, global_config: dict) -> None:
        # Called once before any sample is processed
        pass

    def process(self, ctx: ProcessorContext, entry: ProcessorEntry) -> ProcessorResult:
        # Called once per sample — must be thread-safe
        sha = entry.upstream_data("discover", "sha256", default="")
        result_path = entry.sample_dir / self.config.output_name
        result_path.write_text(sha)
        return ProcessorResult.ok(
            artifacts={"result": self.config.output_name},
            data={"analyzed": True},
        )

    def teardown(self) -> None:
        pass
```

**Result types:**

```python
ProcessorResult.ok(data={...}, artifacts={"name": "relative/path"})  # passes sample downstream
ProcessorResult.filter("reason")                                       # excludes sample from further stages
ProcessorResult.fail("error message")                                  # marks sample as failed
```

**Accessing upstream stage data:**

```python
# Shorthand for a specific field from a previous stage
sha = entry.upstream_data("discover", "sha256", default="")

# Full output object from a previous stage
output = entry.upstream("scan")
output.data["finding_count"]
output.artifacts["findings_file"]
```

**Base classes:**

| Base Class | Processor Type | `process()` signature |
|-----------|---------------|----------------------|
| `IngestProcessor` | `ingest` | `(ctx, target: Path) → list[Sample]` |
| `MapProcessor` | `map` | `(ctx, entry: ProcessorEntry) → ProcessorResult` |
| `BulkMapProcessor` | `bulk_map` | `(ctx, entries: list[ProcessorEntry]) → list[ProcessorResult]` |
| `ReduceProcessor` | `reduce` | `(ctx, entries: list[ProcessorEntry]) → list[str]` (sample IDs to keep) |

Place custom processors under `processors/` and reference them in YAML as `dir/file.py`.

---

## 📁 Repository Structure

```
src/deepzero/
├── cli.py               # CLI entry point (click)
├── api/server.py        # REST API (Starlette)
├── engine/
│   ├── llm.py           # LiteLLM wrapper with adaptive retry/backoff
│   ├── pipeline.py      # Pipeline loader, env-var expansion, validator
│   ├── registry.py      # Processor registry and file-based resolution
│   ├── runner.py        # Breadth-first executor (ThreadPoolExecutor)
│   ├── stage.py         # Base classes: IngestProcessor, MapProcessor, etc.
│   ├── state.py         # StateStore: atomic filesystem state ledger
│   └── types.py         # Enums: RunStatus, SampleStatus, StageStatus, Verdict
└── stages/              # Built-in processors

processors/              # Domain-specific processors (examples)
├── ghidra_decompile/    # Ghidra headless decompiler
├── loldrivers_filter/   # Known-vulnerable driver blocklist
├── pe_ingest/           # PE header parser
└── semgrep_scanner/     # Semgrep batch scanner

pipelines/
└── loldrivers/          # Example: BYOVD vulnerability research pipeline
    ├── pipeline.yaml
    ├── assessment.j2    # LLM prompt template
    └── rules/           # Semgrep rules

tests/
```

---

## 🤝 Contributing & License

Run linting and security checks before submitting:

```bash
ruff check . && ruff format --check . && bandit -ll -ii -c pyproject.toml -r .
```

To add a built-in processor, place it in `src/deepzero/stages/` and register it in `src/deepzero/stages/__init__.py`.

To add a community processor, create a folder under `processors/` and reference it in your pipeline YAML.

DeepZero is released under the [MIT License](LICENSE).
