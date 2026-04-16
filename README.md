<div align="center">
  <h1>DeepZero</h1>
  <p><b>Agentic Vulnerability Research & Binary Analysis at Scale</b></p>

  <p>
    <a href="https://github.com/416rehman/DeepZero/actions"><img src="https://img.shields.io/github/actions/workflow/status/416rehman/DeepZero/ci.yml?branch=main" alt="Build Status"></a>
    <a href="https://pypi.org/project/deepzero/"><img src="https://img.shields.io/pypi/v/deepzero" alt="PyPI - Version"></a>
    <a href="https://pypi.org/project/deepzero/"><img src="https://img.shields.io/pypi/pyversions/deepzero" alt="PyPI - Python Version"></a>
    <a href="https://github.com/416rehman/DeepZero/blob/main/LICENSE"><img src="https://img.shields.io/github/license/416rehman/DeepZero" alt="License"></a>
  </p>
</div>

---

**DeepZero** is a highly parallelized, breadth-first pipeline framework designed to automate massive-scale binary analysis. By flawlessly orchestrating tools like Headless Ghidra and Semgrep alongside modern Foundation Models (via `litellm`), DeepZero enables you to construct complex, declarative vulnerability research workflows capable of traversing thousands of binaries simultaneously.

Unlike traditional ad-hoc scripts, DeepZero features an **Agentic File-Ledger Engine**—a zero-database architecture that writes deterministic state natively to the filesystem. If a pipeline parsing 10,000 Windows kernel drivers is killed halfway through, DeepZero can resume instantly with zero overhead, automatically compiling deep contextual histories into `context.md` files for final LLM analysis.

## 🔥 Key Highlights

* **Declarative Pipelines**: Build massive multi-stage data flows entirely in YAML. Effortlessly stack parsing, filtering, decompilation, and LLM evaluation stages with zero glue code.
* **Idempotent Resurrection**: Abort, kill, and restart. DeepZero picks up exactly where it left off on a per-binary basis. 
* **Zero-DB File Ledger**: Transparent processing. Every processor writes localized JSON chunks to a pipeline `work/` directory, naturally formatting data for LLM context windows.
* **Massive Bulk Execution**: Instantly scan hundreds of Ghidra-decompiled outputs with a single Semgrep invocation using high-performance hardlink abstractions.
* **Model Agnostic**: With built-in LiteLLM integration, route complex security contexts to `gpt-4o`, `gemini-2.5-pro`, or local Oollama instances transparently.

---

## ⚡ The Architecture 

DeepZero forces processing stages into polymorphic primitives, executing horizontally across entire datasets before advancing to the next stage. This ensures you never bottleneck on a single runaway decompiler process.

* **Ingest** (`1:N`): Crawl directories, parse formats, extract headers (e.g., `pe_ingest`).
* **Map** (`1:1`): Apply filters, execute parallel de-compilation (e.g., `ghidra_decompile`).
* **Bulk** (`N:Batch`): Route hundreds of outputs through external batch scanners (e.g., `semgrep_scanner`).
* **Reduce** (`N:1`): Erect synchronization barriers to rank or truncate the active corpus (e.g., `top_k`).

---

## 📦 Installation

DeepZero requires **Python 3.11+**.

```bash
# Clone the repository
git clone https://github.com/416rehman/DeepZero.git
cd DeepZero

# Install with all dependencies (PE parsing, LLM support, CLI)
pip install -e .[full]
```

## 🚀 Quick Start: Hunting Vulnerable Drivers

DeepZero includes highly capable pre-configured pipelines. Let's run the `loldrivers` analysis pipeline against a local folder of `.sys` drivers:

```bash
export GEMINI_API_KEY="your-api-key-here"

deepzero run ./drivers/ \
  --pipeline pipelines/loldrivers/pipeline.yaml \
  --model vertex_ai/gemini-2.5-pro
```

### Checking Status & Interactive Mode

Because DeepZero writes state purely to the filesystem ledger, you can check the status of live runs or drop into an LLM-backed REPL to ask questions about your findings:

```bash
# Get live progress and success/failure statistics
deepzero status -w ./work/

# Drop into a REPL that has access to the full pipeline context
deepzero interactive -w ./work/ -m openai/gpt-4o
```

---

## 🛠️ Building Your Own Pipeline

Pipelines are natively defined in YAML. The built-in framework supports resolving external custom Python classes automatically from your `processors/` directory.

### Example: Basic Vulnerability Funnel
```yaml
name: custom-vr-funnel
settings:
  work_dir: work
  max_workers: 4

stages:
  # 1. Expand the target dataset
  - name: discover
    processor: pe_ingest/pe_ingest.py
    config: { extensions: [".exe", ".dll"] }

  # 2. Decompile parallelized via GHIDRA
  - name: decompile
    processor: ghidra_decompile/ghidra_decompile.py
    timeout: 600

  # 3. Assess with AI
  - name: final_assessment
    processor: generic_llm
    config:
      prompt: pipelines/prompts/assessment.j2
```

## 🎯 Third-Party Dependencies

DeepZero acts as an orchestrator. Depending on the processors you utilize in your pipelines, ensure the following are available in your environment:
* **Headless Ghidra**: `GHIDRA_INSTALL_DIR` must point to a valid unzipped Ghidra release.
* **Semgrep**: Required on your system `PATH` if using `semgrep_scanner.py`.

## 🛠 Anatomy of a Processor

DeepZero revolves around "Processors": self-contained python modules that sequentially transform samples in the payload block. Building a custom processor is effortless because context is deeply insulated and execution cleanly transitions through discrete lifecycle blocks.

### State Containers (What holds what)
* `self.config` : The typed representation of your explicitly assigned YAML variables dictating your specific stage block behavior.
* `ctx` : Provides access to global pipeline bindings (like the LLM Provider) and contextual directory pointers.
* `entry` : Details concerning the exact sample payload currently situated on the execution block.

### Execution Hooks (When do they trigger)

* `validate(self, ctx)` : *Offline Linter Phase*. Executes instantly before operations instantiate to strictly evaluate configuration bounds or missing system credentials early (e.g. absent LLM keys or missing binary paths). 
* `setup(self, ctx)` : *Run-time Binding Phase*. Triggered immediately prior to processing loop. Used strictly for initializing heavy payloads, such as opening WebSocket allocations or spinning up sandbox environments. 
* `process(self, ctx, entry)` : *Execution Loop*. High-throughput transformation, analysis, or filtering payload logic (automatically batched or multiprocessed where applicable by node type).
* `teardown(self)` : *Resource Reclamation*. Terminating DB locks or purging local staging files at pipeline completion.

## 🤝 Contributing

We welcome community pull requests! If you're adapting DeepZero for new architectures, writing custom processors (like IDA Pro integrations), or optimizing the File-Ledger overhead, please feel free to fork and open a PR. 

## 📄 License
Released under the [MIT License](LICENSE).
