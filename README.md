<div align="center">
  <h1>DeepZero</h1>
  <p><b>A Zero-DB Pipeline Orchestrator</b></p>
  <p>
    <a href="https://github.com/416rehman/DeepZero/actions"><img src="https://img.shields.io/github/actions/workflow/status/416rehman/DeepZero/ci.yml?branch=main" alt="Build Status"></a>
    <a href="https://pypi.org/project/deepzero/"><img src="https://img.shields.io/pypi/v/deepzero" alt="PyPI - Version"></a>
    <a href="https://pypi.org/project/deepzero/"><img src="https://img.shields.io/pypi/pyversions/deepzero" alt="PyPI - Python Version"></a>
    <a href="https://github.com/416rehman/DeepZero/blob/main/LICENSE"><img src="https://img.shields.io/github/license/416rehman/DeepZero" alt="License"></a>
  </p>
</div>

---

**DeepZero** is a generalized, breadth-first pipeline orchestrator. It manages modular pipelines built entirely from decoupled processors.

It enforces a **State Ledger Architecture**, writing state intrinsically to the local filesystem. This implies complete idempotency: if a pipeline parsing tens of thousands of files halts mid-execution, DeepZero resumes instantly without re-processing overhead, natively serializing execution footprints per-sample.

---

## ⚡ Architecture 

DeepZero structurally enforces processing boundaries into distinct primitives, organizing any arbitrary workload across horizontal queues:

* **Ingest** (`1:N`): Crawl directories, parse structure, and yield items.
* **Map** (`1:1`): Apply isolated transformations on individual samples parallelized across system workers.
* **Batch** (`N:Batch`): Route active sets through batch execution nodes asynchronously.
* **Reduce** (`N:1`): Erect synchronous execution walls to truncate, rank, or aggressively filter the active sample volume.

---

## 📦 Installation

DeepZero requires **Python 3.11+**.

```bash
git clone https://github.com/416rehman/DeepZero.git
cd DeepZero
pip install -e .
```

---

## 🚀 Running Pipelines

DeepZero enforces declarative data logic formatted exclusively in YAML.

```bash
deepzero run ./data_directory -p pipelines/demo/pipeline.yaml
```

To survey execution status or query the local state ledger:
```bash
deepzero status -w ./work/
```

---

## 🛠 Anatomy of a Pipeline (YAML)

All executions funnel synchronously down your `stages` block sequentially.

```yaml
name: generic_pipeline
version: "1.0"

settings:
  work_dir: work
  max_workers: 8

stages:
  - name: discover
    processor: pe_ingest/pe_ingest.py
    config:
      extensions: [".exe", ".sys"]

  - name: process_node
    processor: dummy/dummy_processor.py
    timeout: 300
    config: 
      param: true

  - name: synchronization
    processor: sort
    config:
      by: process_node.value
      order: desc
```

---

## 🔧 Building Processors 

DeepZero plugins are self-contained state nodes designed to sequentially mutate or interpret samples. 

### Execution Lifecycle

Processors expose strict sequence hooks executed synchronously by the Engine wrapper:

1. `validate(self, ctx: ProcessorContext) -> list[str]`
    * Executes offline during pipeline validation. Used to block invalid configuration states or missing system paths before runtime execution begins.
2. `setup(self, ctx: ProcessorContext) -> None`
    * Triggered immediately prior to processing map creation. Used for large structural pre-allocations (e.g., spawning persistent local sockets).
3. `process(self, ctx: ProcessorContext, entry: ProcessorEntry) -> ProcessorResult`
    * The primary active workload node invoked dynamically against payloads.
4. `teardown(self) -> None`
    * Reclamation hook to cleanly sever connections upon queue finalization.

### Integration Patterns

**Project-Specific Usage**: 
You can implement logic directly inside generic paths relative to your local codebase:
```yaml
  - name: custom_firewall_bypass
    processor: ./modules/example.py:ExampleImplementation
```

**Contributing Upstream**:
To generalize processors upstream into DeepZero:
1. Target primitives inside `src/deepzero/stages/` (e.g., sort, top-k).
2. Or construct modular folders inside the `processors/` hierarchy for complex independent nodes.

---

## 🤝 Contributing & License

For formatting compliance upstream during module additions, ensure:
```bash
ruff check . && ruff format --check . && bandit -r src processors
```

DeepZero is released under the [MIT License](LICENSE).
