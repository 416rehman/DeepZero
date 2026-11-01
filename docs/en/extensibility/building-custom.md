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
- `ctx.global_config`: TypedDict containing pipeline-level `settings`, `knowledge`, the configured `model`, and `pipeline_dir`, the directory the pipeline was loaded from as a string. That last key exists because `setup()` receives this config and no context, so without it a config value naming a file that ships with the pipeline resolves against the working directory instead. `ctx.get_setting(key)` and `ctx.get_knowledge(key)` are shorthands into it.
- `ctx.llm`: A generic proxy instance (implementing `LLMProtocol`) with native backoff and retry, or `None` when the pipeline configures no model. Which backend it drives is resolved from the pipeline's `model` string, so a processor calling `ctx.llm.complete()` works the same against an API key and against a local agent CLI. See [Choosing a Model]({{ '/en/reference/pipeline-yaml.html' | relative_url }}).
- `ctx.log`: Pre-configured, namespaced `logging.Logger`.
- `ctx.progress`: Progress reporting hook, `update(amount=, total=, description=)`, so a long-running ingest or bulk stage shows movement on the dashboard instead of looking hung.
- `ctx.shutdown_event`: A `threading.Event`, set when the run is interrupted. A processor doing long work should check it and return early rather than being killed mid-write.
- `ctx.conclude(**fields)`: Record a finding about the corpus rather than about any one sample. Some questions only have an answer in aggregate: which model is behind an endpoint, how many distinct bugs a pile of crashes represents. The fields are merged into the run's `conclusion` and the run is saved straight away, so an interrupted run still carries what it had already worked out.

The engine wires `conclude` to a real writer only for a `reduce` or a `bulk_map` stage, which are the ones that see every sample in a single call:

```python
class ModelFingerprint(ReduceProcessor):
    def process(self, ctx: ProcessorContext, entries: list[ProcessorEntry]) -> list[str]:
        ctx.conclude(headline="every probe answers as the same model family", probes=len(entries))
        return [e.sample_id for e in entries]
```

In a map or ingest stage the call logs that `ctx.conclude()` is only available to a reduce or bulk_map stage and that the call was ignored, then does nothing. A per-sample lane spread across a thread pool cannot speak for the corpus without racing itself: whichever sample finished last would win, and the loser would never know it had been overwritten.

### Execution Hooks

Processors implement specific lifecycle hooks invoked by the engine:

1. **`validate(ctx: ProcessorContext) -> list[str]`**: Invoked during initial schema validation (via `deepzero validate` or prior to execution). Return a list of error strings if dependencies (e.g., missing binaries, unparseable YAMLs) fail. The context here is a reduced one: `ctx.global_config` carries `settings`, `knowledge` and `model` only, with no `pipeline_dir` key, and `ctx.llm` is `None` because no provider has been built yet. A check that needs either will misread the pipeline. `ctx.pipeline_dir` itself is populated, so resolve co-located files through that.
2. **`setup(global_config: dict) -> None`**: Executed exactly once before the thread pool activates.
3. **`process(...)`**: The core operation. Signature varies by ProcessorType.
4. **`teardown() -> None`**: Executed upon pipeline completion or fatal interruption.

One more is worth overriding on a Map processor that is expensive per sample:

5. **`max_parallelism() -> int | None`**: A ceiling on auto concurrency. It applies only when the stage's YAML declares `parallel: 0`; any `parallel: N` above zero is honoured as written, before the ceiling or the `max_workers` setting is consulted. Return an int when each sample costs a JVM, a container or a few gigabytes of memory, so a stage that asked to auto-scale cannot take a worker per core. `None`, the default, means no ceiling. Omitting `parallel:` is not the same as writing `parallel: 0`: a stage that does not name it is loaded with 4, which counts as an explicit figure, so the ceiling never reaches it.

### What the Processor Instance Carries

`ctx` describes the run. The processor object itself carries what belongs to the stage:
- `self.config`: the parsed `Config` dataclass, or the raw YAML dict when the processor declares no `Config`.
- `self.spec`: the `StageSpec` this instance was built from: its name, config block, `parallel`, `on_failure`, `max_retries` and `timeout`.
- `self.log`: a logger namespaced to the stage name.
- `self.global_config`: the same `GlobalConfig` `ctx` carries, set by the engine before `setup()` runs.
- `self.processor_dir`: the directory holding this processor's own `.py` file, for scripts, templates and rule files shipped beside it. This is not `ctx.pipeline_dir`: a pipeline can name a processor that lives somewhere else entirely, and then the two point at different places.
- `self.cache_dir`: a persistent directory at `./.cache/<stage name>`, created on first access. Nothing in the engine clears it, so it survives across runs and is the place for downloads and other work too expensive to repeat.

### Defining Processor Configuration

Declare the YAML configuration a processor accepts with an embedded `@dataclass` named `Config`. The engine expands `${VAR}` and `${VAR:-default}` in the [Pipeline YAML]({{ '/en/reference/pipeline-yaml.html' | relative_url }}) and instantiates your `Config` from the stage's `config` block using standard Python [`dataclasses`](https://docs.python.org/3/library/dataclasses.html).

Declaring the fields is not the same as enforcing them. A key the dataclass does not declare is logged as not read by this processor, listed against the names it does accept, then dropped, and the run carries on; `limit` is read by the engine itself and is exempt from that warning. Nothing checks types. An unset `${VAR}` expands to the empty string rather than staying literal, so a missing environment variable arrives as a field that is present and blank rather than as an error. Give every field a default and do the real checking in `validate()`, which runs before any sample is touched.

```python
import json
import math
from collections import Counter
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

        # entry.source_path is the thing under analysis: whatever the ingest
        # stage recorded for this sample, and the only handle you have on it
        entropy = self._shannon_entropy(entry.source_path.read_bytes())

        # ProcessorEntry binds to an isolated sandbox per-sample
        out_file = entry.sample_dir / "heuristics.json"
        out_file.write_text(json.dumps({"sha256": sha, "entropy": entropy}))

        # ProcessorResult determines routing
        if self.config.target_arch != "x86_64":
            return ProcessorResult.filter(reason="unsupported_arch")

        return ProcessorResult.ok(
            artifacts={"heuristics": "heuristics.json"},
            data={"analyzed": True, "entropy_ok": entropy <= self.config.max_entropy}
        )

    @staticmethod
    def _shannon_entropy(blob: bytes) -> float:
        counts = Counter(blob)
        return -sum(
            (n / len(blob)) * math.log2(n / len(blob)) for n in counts.values()
        ) if blob else 0.0
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

Test `entry.cache_is_valid` as well as the path, never the path alone:

```python
def should_skip(self, ctx: ProcessorContext, entry: ProcessorEntry) -> str | None:
    if entry.cache_is_valid and (entry.sample_dir / "out.json").exists():
        return "cached"
    return None
```

`cache_is_valid` is `False` when the file on disk came from a prompt, rule set or config
that has since changed: the engine compares the input digest recorded against the previous
run with the one this stage's inputs produce now. A `should_skip` that only tests
`.exists()` re-adopts output answering a question the pipeline is no longer asking. The
built-in LLM stage and the bundled Semgrep scanner both take this guard where they adopt
an existing file.

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

### What an Entry Carries (`ProcessorEntry`)

Every map, bulk_map and reduce processor is handed entries rather than raw samples:
- `entry.sample_id`: the sample's unique identifier, and the key its state is stored under.
- `entry.source_path`: a `Path` to the thing under analysis, whatever the ingest stage recorded for this sample. This is the only handle a map processor has on its input.
- `entry.filename`: the display name, used in logs and reports.
- `entry.sample_dir`: the isolated working directory for this sample, where output belongs.
- `entry.cache_is_valid`: whether output already sitting in `sample_dir` was produced with this stage's current inputs, as described under `should_skip` above.

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
