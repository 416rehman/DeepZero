---
layout: default
title: Pipeline YAML
order: 2
---

## Pipeline Configuration

A **Pipeline** in DeepZero is a declarative execution graph defining a continuous, resilient data transformation process. It translates a raw physical dataset into a high-signal analytical dataset.

The pipeline schema is rigorously defined in YAML. DeepZero resolves configuration dynamically, supporting shell-native variable expansion (e.g., `${VAR:-default}`).

### Configuration Schema

```yaml
name: my_pipeline
description: Standard vulnerability research pipeline
version: "1.0"
model: openai/gpt-4o  # Default LiteLLM integration target

settings:
  work_dir: work
  max_workers: 8  # Global ceiling on ThreadPoolExecutor thread limits

stages:
  # Stage 1: MUST be an IngestProcessor
  - name: discover
    processor: file_discovery
    config:
      extensions: ["*"]

  # Stage 2: Synchronous Filter
  - name: filter
    processor: metadata_filter
    config:
      require:
        is_executable: true

  # Stage 3: High-latency Map processing
  - name: decompile
    processor: ghidra_decompile/ghidra_decompile.py
    parallel: 4           # Restricts concurrency mapping to 4 concurrent Ghidra JVMs
    timeout: 300          # Enforces a strict 300-second kill clock per sample via process.py
    on_failure: skip      # Handles exceptions silently rather than aborting (skip, retry, abort)
    max_retries: 2        # Retry logic execution constraint
    config:
      ghidra_install_dir: ${GHIDRA_INSTALL_DIR}
```

### Stage Options

Every stage defined under the `stages:` array accepts the following attributes:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | string | `stage_N` | Unique stage name within the pipeline |
| `processor` | string | required | Processor reference (see below) |
| `config` | dict | `{}` | Processor-specific configuration |
| `parallel` | int | `4` | Concurrency for Map processors. `0` auto-scales to `os.cpu_count()` |
| `timeout` | int | `0` | Per-sample timeout in seconds (0 = no timeout) |
| `on_failure` | string | `skip` | Defines fault-tolerance behavior: `skip`, `retry`, or `abort` |
| `max_retries` | int | `0` | Retry count when `on_failure: retry` |

### Resolution Logic (`engine/pipeline.py`)

When invoked via the CLI, the parser attempts to resolve processors in strict hierarchical order:
1. **Path Resolvers:** Direct file paths terminating in `.py` (e.g., `processors/ghidra/ghidra.py:Decompiler`).
2. **Directory Lookup:** `pipeline/my_pipeline/processors/`.
3. **Internal Registry:** System built-ins explicitly registered in `stages/__init__.py`.
4. **Dotted Python Import:** Dynamically evaluated modules (e.g., `my.python.module:MyClass`).

### Dynamic Expansion

Before schema validation binds processors, DeepZero walks the entire YAML DOM tree, evaluating Regex matches against `\$\{([^}]+)\}`. Environment variables dictate the resolved runtime configuration. This explicitly prevents hardcoding API keys or installation directories within committed `.yaml` pipelines.
