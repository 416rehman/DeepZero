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

### Prompt Values

A stage whose `config` carries a `prompt` renders that file as a Jinja template. The
value can be a path or a filename sitting next to the pipeline; either way the file
is loaded, never used as the prompt text itself.

Every prompt can use these:

| Value | Type | Description |
|-------|------|-------------|
| `sample_name` | string | The sample's filename as the ingest stage recorded it |
| `sample_path` | string | Absolute path to the sample on disk |
| `history` | dict | `{stage_name: data}` for every stage that has already run |
| `config` | dict | This stage's own `config` block |

Beyond those, a prompt can use whatever the stages **before it** recorded. Each
processor declares those names in its `provides` attribute, and there are two kinds:

- **Data keys** — anything the processor puts in `data`, such as `device_name` or
  `finding_count`. Available under that name directly, and under `history`.
- **Artifacts** — a file the processor wrote, reachable by its path with the
  separators and the extension folded into the name. `decompiled/dispatch_ioctl.c`
  becomes `decompiled_dispatch_ioctl_c`. JSON is parsed into an object; `.c`, `.h`,
  `.txt`, `.md`, `.py`, `.yaml` and `.yml` arrive as text. Other file types are not
  exposed. Anything over the context budget is truncated, and oversized JSON is
  skipped with a warning rather than parsed.

A value is only available to stages *after* the one recording it, so a prompt cannot
reach its own stage's output.

To see what a given pipeline offers, run:

```bash
deepzero validate <pipeline>
```

A prompt naming something no earlier stage produces is reported as an error listing
what was available instead, and the same check fails the run if it is reached. This
matters because an unknown name would otherwise render as nothing: the model would be
asked to judge an empty payload, and the verdict would come back confident and
meaningless.

### Review Marks

A pipeline records what it concluded. Whether a person has actually checked that
conclusion is a separate claim, and only the reader can make it, so the report
carries marks they add while reading.

On any result's page there are two: **confirmed**, and **outstanding** with a note
saying what is still unproven. What counts as outstanding is left to the reader —
reproducing a crash, proving a precondition, reading a diff — because from the
report's side they are all the same shape of unfinished work.

Marks appear against each row in the index and can be filtered on, including
**Unreviewed**, which is the list of results nobody has looked at yet.

The report is a file, so marks live in the browser. **Export marks** writes them out
as `marks.json`; save that next to `index.html` and they become part of the report:
rendered for anyone who opens it, and included in `inventory.csv` as `review` and
`review_note`. Marks are keyed on the pipeline and target rather than on the file
path, so re-running over the same corpus keeps them.
