---
layout: default
title: Building Processors
order: 2
---

## Building Custom Processors

Custom logic is injected into DeepZero by subclassing the typed abstractions provided in `deepzero.engine.stage`. See the [Core Architecture]({{ '/en/overview/architecture.html' | relative_url }}) to understand how these stages map to execution phases.

### Processor Context (`ProcessorContext`)

The `ctx` object injected into every lifecycle hook provides systemic context and utilities:
- `ctx.pipeline_dir`: Root directory of the invoked pipeline, useful for resolving local templates or rulesets.
- `ctx.global_config`: TypedDict containing pipeline-level `settings`, `knowledge`, and the configured `model`. `ctx.get_setting(key)` and `ctx.get_knowledge(key)` are shorthands into it.
- `ctx.llm`: A generic proxy instance (implementing `LLMProtocol`) with native backoff and retry, or `None` when the pipeline configures no model. Which backend it drives is resolved from the pipeline's `model` string, so a processor calling `ctx.llm.complete()` works the same against an API key and against a local agent CLI. See [Choosing a Model]({{ '/en/reference/pipeline-yaml.html' | relative_url }}).
- `ctx.log`: Pre-configured, namespaced `logging.Logger`.
- `ctx.progress`: Progress reporting hook, `update(amount=, total=, description=)`, so a long-running ingest or bulk stage shows movement on the dashboard instead of looking hung.
- `ctx.shutdown_event`: A `threading.Event`, set when the run is interrupted. A processor doing long work should check it and return early rather than being killed mid-write.

### Execution Hooks

Processors implement specific lifecycle hooks invoked by the engine:

1. **`validate(ctx: ProcessorContext) -> list[str]`**: Invoked during initial schema validation (via `deepzero validate` or prior to execution). Return a list of error strings if dependencies (e.g., missing binaries, unparseable YAMLs) fail.
2. **`setup(global_config: dict) -> None`**: Executed exactly once before the thread pool activates.
3. **`process(...)`**: The core operation. Signature varies by ProcessorType.
4. **`teardown() -> None`**: Executed upon pipeline completion or fatal interruption.

One more is worth overriding on a Map processor that is expensive per sample:

5. **`max_parallelism() -> int | None`**: A ceiling on auto concurrency. It applies only when the stage declares `parallel: 0`; an explicit `parallel: N` is always honoured as written. Return an int when each sample costs a JVM, a container or a few gigabytes of memory, so a pipeline left at the default cannot exhaust the machine. `None`, the default, means no ceiling.

### Defining Processor Configuration

Use an embedded `@dataclass` named `Config` to strictly define and validate accepted YAML configurations. The engine parses the [Pipeline YAML]({{ '/en/reference/pipeline-yaml.html' | relative_url }}) dictionary and instantiates your `Config` object, fully expanding `${ENV_VARS}` automatically using standard Python [`dataclasses`](https://docs.python.org/3/library/dataclasses.html).

```python
from dataclasses import dataclass
from deepzero.engine.stage import MapProcessor, ProcessorContext, ProcessorEntry, ProcessorResult

class BinaryAnalyzer(MapProcessor):
    description = "Static heuristics extraction"

    @dataclass
    class Config:
        target_arch: str = "x86_64"
        max_entropy: float = 7.5

    def process(self, ctx: ProcessorContext, entry: ProcessorEntry) -> ProcessorResult:
        # Retrieve data emitted by an upstream IngestProcessor
        sha = entry.upstream_data("discover", "sha256", default="UNKNOWN")
        
        # ProcessorEntry binds to an isolated sandbox per-sample
        out_file = entry.sample_dir / "heuristics.json"
        out_file.write_text('{"entropy": 7.1}')
        
        # ProcessorResult determines routing
        if self.config.target_arch != "x86_64":
            return ProcessorResult.filter(reason="unsupported_arch")
            
        return ProcessorResult.ok(
            artifacts={"heuristics": "heuristics.json"},
            data={"analyzed": True, "entropy_ok": True}
        )
```

### Result Outcomes (`ProcessorResult`)

Map/BulkMap processors must return a strictly formatted `ProcessorResult`:
- **`.ok(data={...}, artifacts={...})`**: Flags execution as `COMPLETED`. The `data` dict is namespaced to the processor's history block. `artifacts` maps keys to relative file paths.
- **`.filter(reason="...", data={...})`**: Terminates sample processing silently. `SampleState.verdict` mutates to `FILTERED`.
- **`.fail(error="...")`**: Terminates processing due to a fatal, unexpected error. `SampleState.verdict` mutates to `FAILED`.
- **`.timed_out(budget)`**: The work ran out of time rather than going wrong. `SampleState.verdict` mutates to `TIMED_OUT`, and the budget travels with it so the report can say what to give it instead. Return this from a processor enforcing its own budget; the stage-level `timeout:` produces it on its own.

A Map processor can also override **`should_skip(ctx, entry) -> str | None`**, returning
a reason to declare the work already done, typically because its own output file is
already on disk. A skipped sample counts as passed and carries on downstream. Record
that output as an artifact when you do this: `deepzero run --redo` deletes recorded
artifacts precisely so a cached file cannot be re-adopted, and a file the run never
recorded outlives the state describing it.

### Declaring What Later Stages Can Use

A processor's `data` keys and artifacts become available to the prompts of stages that
run after it. Declare those names in `provides` so `deepzero validate` can check a
prompt before a run instead of letting an unknown name render as nothing:

```python
class Decompiler(MapProcessor):
    description = "Static heuristics extraction"
    provides = (
        "device_name",                    # a key this processor puts in data
        "decompiled_dispatch_ioctl_c",    # the artifact decompiled/dispatch_ioctl.c
    )
```

An artifact is named by its path with the separators and the extension folded in;
`template_key_for_artifact` in `engine/stage.py` is the single rule both rendering and
validation use. List names that are only sometimes recorded — a prompt is expected to
tolerate them being absent. See [Prompt Values]({{ '/en/reference/pipeline-yaml.html' | relative_url }})
for what a prompt receives.

### Accessing Upstream Data

Processors inherently rely on artifacts and data generated by predecessors. The `ProcessorEntry` facade exposes lazy-loaded helper methods to retrieve this data seamlessly:

```python
# Shorthand extraction of a specific field (with fallback)
sha = entry.upstream_data("discover", "sha256", default="")

# Full extraction of a previous stage's StageOutput object
output = entry.upstream("scan")
findings = output.data.get("finding_count", 0)
json_file = output.artifacts.get("findings_file")
```

### Base Classes

Depending on your pipeline topology requirements, extend the appropriate base class:

| Base Class | Processor Type | `process()` Signature |
|-----------|---------------|----------------------|
| `IngestProcessor` | `ingest` | `(ctx, target: Path) → list[Sample]` |
| `MapProcessor` | `map` | `(ctx, entry: ProcessorEntry) → ProcessorResult` |
| `BulkMapProcessor` | `bulk_map` | `(ctx, entries: list[ProcessorEntry]) → list[ProcessorResult]` |
| `ReduceProcessor` | `reduce` | `(ctx, entries: list[ProcessorEntry]) → list[str]` |
