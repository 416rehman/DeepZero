---
layout: default
title: Core Architecture
order: 2
---

## Engine Architecture

DeepZero's orchestration engine operates on a strictly directional processing graph defined by [pipelines]({{ '/en/reference/pipeline-yaml.html' | relative_url }}). The execution engine guarantees fault-tolerant, resumable [state management]({{ '/en/system/state-persistence.html' | relative_url }}) while fanning out parallel operations across a bounded thread pool ([`ThreadPoolExecutor`](https://docs.python.org/3/library/concurrent.futures.html#threadpoolexecutor)).

<div class="architecture-diagram" style="margin: 3rem 0;">
    <svg viewBox="0 0 800 400" style="width: 100%; height: auto; max-width: 800px;" xmlns="http://www.w3.org/2000/svg">
        <defs>
            <linearGradient id="flowGrad" x1="0%" y1="0%" x2="100%" y2="0%">
                <stop offset="0%" stop-color="var(--border)" />
                <stop offset="50%" stop-color="var(--text-tertiary)" />
                <stop offset="100%" stop-color="var(--border)" />
            </linearGradient>
            <pattern id="isoGridSmall" width="40" height="23.094" patternUnits="userSpaceOnUse" patternTransform="scale(1)">
                <path d="M 40 0 L 0 23.094 M 0 0 L 40 23.094 M 20 23.094 L 20 0" fill="none" stroke="var(--border)" stroke-width="0.5"/>
            </pattern>
        </defs>
        
        <rect width="100%" height="100%" fill="url(#isoGridSmall)" opacity="0.3"/>

        <!-- Ingest Node -->
        <g transform="translate(150, 200)">
            <path d="M 0 0 L 60 -30 L 120 0 L 60 30 Z" fill="var(--bg-primary)" stroke="var(--text-primary)" stroke-width="1.5" stroke-linejoin="round"/>
            <path d="M 0 0 L 0 40 L 60 70 L 120 40 L 120 0 L 60 30 Z" fill="var(--bg-secondary)" stroke="var(--text-primary)" stroke-width="1.5" stroke-linejoin="round"/>
            <path d="M 60 30 L 60 70" stroke="var(--text-primary)" stroke-width="1.5"/>
            <text x="60" y="-5" font-family="JetBrains Mono, monospace" font-size="12" font-weight="bold" text-anchor="middle" fill="var(--text-secondary)" transform="skewX(30) rotate(-30)">INGEST</text>
            <text x="60" y="30" font-family="Inter, sans-serif" font-size="10" text-anchor="middle" fill="var(--text-tertiary)" transform="skewX(30) rotate(-30)">1 → N</text>
        </g>

        <!-- Connecting Lines to Map -->
        <path d="M 210 170 L 250 150 L 300 150 L 350 125" fill="none" stroke="url(#flowGrad)" stroke-width="2" stroke-dasharray="6 6">
            <animate attributeName="stroke-dashoffset" from="100" to="0" dur="2s" repeatCount="indefinite" />
        </path>
        <path d="M 210 170 L 350 170" fill="none" stroke="url(#flowGrad)" stroke-width="2" stroke-dasharray="6 6">
            <animate attributeName="stroke-dashoffset" from="100" to="0" dur="2s" repeatCount="indefinite" />
        </path>
        <path d="M 210 170 L 250 190 L 300 190 L 350 215" fill="none" stroke="url(#flowGrad)" stroke-width="2" stroke-dasharray="6 6">
            <animate attributeName="stroke-dashoffset" from="100" to="0" dur="2s" repeatCount="indefinite" />
        </path>

        <!-- Map Nodes -->
        <g transform="translate(350, 90)">
            <path d="M 0 0 L 40 -20 L 80 0 L 40 20 Z" fill="var(--bg-primary)" stroke="var(--text-primary)" stroke-width="1.5" stroke-linejoin="round"/>
            <path d="M 0 0 L 0 20 L 40 40 L 80 20 L 80 0 L 40 20 Z" fill="var(--bg-secondary)" stroke="var(--text-primary)" stroke-width="1.5" stroke-linejoin="round"/>
            <path d="M 40 20 L 40 40" stroke="var(--text-primary)" stroke-width="1.5"/>
            <circle cx="40" cy="0" r="3" fill="var(--text-primary)"/>
            <text x="40" y="-10" font-family="JetBrains Mono, monospace" font-size="10" text-anchor="middle" fill="var(--text-secondary)" transform="skewX(30) rotate(-30)">MAP</text>
        </g>
        <g transform="translate(350, 160)">
            <path d="M 0 0 L 40 -20 L 80 0 L 40 20 Z" fill="var(--bg-primary)" stroke="var(--text-primary)" stroke-width="1.5" stroke-linejoin="round"/>
            <path d="M 0 0 L 0 20 L 40 40 L 80 20 L 80 0 L 40 20 Z" fill="var(--bg-secondary)" stroke="var(--text-primary)" stroke-width="1.5" stroke-linejoin="round"/>
            <path d="M 40 20 L 40 40" stroke="var(--text-primary)" stroke-width="1.5"/>
            <circle cx="40" cy="0" r="3" fill="var(--text-primary)"/>
            <text x="40" y="-10" font-family="JetBrains Mono, monospace" font-size="10" text-anchor="middle" fill="var(--text-secondary)" transform="skewX(30) rotate(-30)">MAP</text>
        </g>
        <g transform="translate(350, 230)">
            <path d="M 0 0 L 40 -20 L 80 0 L 40 20 Z" fill="var(--bg-primary)" stroke="var(--text-primary)" stroke-width="1.5" stroke-linejoin="round"/>
            <path d="M 0 0 L 0 20 L 40 40 L 80 20 L 80 0 L 40 20 Z" fill="var(--bg-secondary)" stroke="var(--text-primary)" stroke-width="1.5" stroke-linejoin="round"/>
            <path d="M 40 20 L 40 40" stroke="var(--text-primary)" stroke-width="1.5"/>
            <circle cx="40" cy="0" r="3" fill="var(--text-primary)"/>
            <text x="40" y="-10" font-family="JetBrains Mono, monospace" font-size="10" text-anchor="middle" fill="var(--text-secondary)" transform="skewX(30) rotate(-30)">MAP</text>
        </g>

        <!-- Connecting Lines to Reduce -->
        <path d="M 430 90 L 480 115 L 520 115 L 560 170" fill="none" stroke="url(#flowGrad)" stroke-width="2" stroke-dasharray="6 6">
            <animate attributeName="stroke-dashoffset" from="100" to="0" dur="2s" repeatCount="indefinite" />
        </path>
        <path d="M 430 160 L 560 170" fill="none" stroke="url(#flowGrad)" stroke-width="2" stroke-dasharray="6 6">
            <animate attributeName="stroke-dashoffset" from="100" to="0" dur="2s" repeatCount="indefinite" />
        </path>
        <path d="M 430 230 L 480 205 L 520 205 L 560 170" fill="none" stroke="url(#flowGrad)" stroke-width="2" stroke-dasharray="6 6">
            <animate attributeName="stroke-dashoffset" from="100" to="0" dur="2s" repeatCount="indefinite" />
        </path>

        <!-- Reduce Node -->
        <g transform="translate(560, 180)">
            <path d="M 0 0 L 60 -30 L 120 0 L 60 30 Z" fill="var(--accent)" stroke="var(--bg-primary)" stroke-width="1.5" stroke-linejoin="round"/>
            <path d="M 0 0 L 0 40 L 60 70 L 120 40 L 120 0 L 60 30 Z" fill="var(--text-secondary)" stroke="var(--bg-primary)" stroke-width="1.5" stroke-linejoin="round"/>
            <path d="M 60 30 L 60 70" stroke="var(--bg-primary)" stroke-width="1.5"/>
            <text x="60" y="-5" font-family="JetBrains Mono, monospace" font-size="12" font-weight="bold" text-anchor="middle" fill="var(--bg-primary)" transform="skewX(30) rotate(-30)">REDUCE</text>
            <text x="60" y="30" font-family="Inter, sans-serif" font-size="10" text-anchor="middle" fill="var(--text-tertiary)" transform="skewX(30) rotate(-30)">N → M</text>
            
            <!-- Output stream -->
            <path d="M 60 10 L 90 -5" fill="none" stroke="var(--bg-primary)" stroke-width="2" stroke-dasharray="2 2"/>
            <path d="M 70 20 L 100 5" fill="none" stroke="var(--bg-primary)" stroke-width="2" stroke-dasharray="2 2"/>
        </g>
    </svg>
</div>

### Component Lifecycles

The data model transitions across these abstractions as a sample progresses:

1. **`Sample`**: The foundational struct yielded by an `IngestProcessor`. It binds a physical `source_path` to a unique `sample_id` (typically a SHA-256 hash or deterministic UUID) and initializes the sample's `data` dict.
2. **`SampleState`**: The persistent record maintained by the `StateStore`. Tracks the sample's `verdict` (`PENDING`, `ACTIVE`, `FILTERED`, `FAILED`, `TIMED_OUT`) and maintains a `history` mapping of `StageOutput` instances per processor. A sample that reaches the end of the pipeline stays `ACTIVE`. `FILTERED`, `FAILED` and `TIMED_OUT` are the verdicts that took a sample out of the run, so arriving at the end means never having been given one. `TIMED_OUT` is kept apart from `FAILED` because it says nothing about the sample, and it is the one outcome a longer budget can change.
3. **`ProcessorEntry`**: The dynamically generated, memory-efficient facade passed into Map/BulkMap/Reduce processors. It injects a lazy-load mechanism (`_store`) which only retrieves historical execution data from disk when `.history` or `.upstream_data()` is accessed. It also carries `cache_is_valid`, which any processor that adopts its own earlier output instead of doing the work again has to consult: `False` means that output was produced from a prompt, rule set or config that has since changed, so adopting it would report an answer to a question nobody is asking any more.

Each `StageOutput` also records an `input_digest`, a fingerprint of the processor, its config
and any file that config names: a prompt, a rule set, an analysis script. A resumed run
recomputes the fingerprint once per stage and compares it with the recorded one, so a stage
whose inputs have changed is run again while the stages that still hold are restored from
disk. Results written before fingerprints were recorded carry an empty digest and are trusted
rather than redone, because discarding a corpus that may have taken hours to produce, over a
question that cannot be asked of it, is the worse guess.

### Processing Paradigms

Processors dictate execution topology and concurrency models. All inherit from the base `Processor` class, exposing lifecycle hooks: `validate()`, `setup()`, `process()`, and `teardown()`. For instructions on writing your own, see [Building Custom Processors]({{ '/en/extensibility/building-custom.html' | relative_url }}).

#### `IngestProcessor` (1 → N)
- **Type Signature:** `process(ctx: ProcessorContext, target: Path) -> list[Sample]`
- **Concurrency:** Synchronous. Runs once, and only when the run directory holds no samples yet. A resumed run lists what is already on disk first and, finding anything at all, logs that it is skipping ingest and never calls the processor.
- **Role:** Generates the initial corpus. No upstream data exists prior to Ingest.
- **Consequence:** Because resume never re-ingests, anything added to the target after the first run is not picked up by running the pipeline again. `--clean` discards the corpus and starts it over, and a different target is a different corpus with its own run directory; either one ingests afresh. `--redo` on the ingest stage does not: it forgets what that stage recorded, but the sample state it forgot it on is still on disk, and finding sample state is what makes a run a resumed one.

#### `MapProcessor` (1 → 1)
- **Type Signature:** `process(ctx: ProcessorContext, entry: ProcessorEntry) -> ProcessorResult`
- **Concurrency:** Threaded fan-out. Configured via the `parallel:` field in pipeline YAML. `parallel: 0` auto-scales, bounded by `max_workers` and by whatever the processor returns from `max_parallelism()`.
- **Constraints:** Must be strictly thread-safe. Avoid shared mutable state.
- **Budget:** `timeout:` bounds how long the stage waits on one sample, not how long the work runs. The worker thread is abandoned, never killed, so a processor that starts an external process should bound that process itself.

#### `BulkMapProcessor` (N → N)
- **Type Signature:** `process(ctx: ProcessorContext, entries: list[ProcessorEntry]) -> list[ProcessorResult]`
- **Concurrency:** Synchronous execution over a subset or totality of active samples.
- **Role:** Optimizes external process invocations (e.g., launching a monolithic JVM tool or Semgrep batch scan) to amortize heavy startup costs across multiple samples. Outputs must be strictly indexed to match the input `entries` list.
- **Corpus findings:** Receives every pending sample in one call, so `ctx.conclude()` is live here.

#### `ReduceProcessor` (N → M)
- **Type Signature:** `process(ctx: ProcessorContext, entries: list[ProcessorEntry]) -> list[str]`
- **Concurrency:** Global synchronization barrier. Pauses threaded execution until all active samples reach this stage.
- **Role:** Returns an ordered list of `sample_id` strings defining which samples survive. Any sample ID absent from the returned list is permanently tagged with `SampleStatus.FILTERED`.
- **Corpus findings:** Sees every active sample in one call, so `ctx.conclude()` is live here.

### The Output Contract

Whatever a processor is doing, it records the same three things: `data`, an arbitrary
namespaced dict; `artifacts`, a mapping of label to relative file path; and a status.
That contract is deliberately domain-free, and it is what everything downstream of the
engine is built on.

A stage that sees the whole corpus at once has one more thing it can record.
`ctx.conclude(**fields)` files a finding about the corpus rather than about any one sample:
which model is behind an endpoint, how many distinct bugs a pile of crashes represents,
whether a scope is configured correctly. The fields merge into `RunState.conclusion` in
`run.json` and are written the moment they are made, so an interrupted run keeps the
conclusion it had already reached. In a map stage the call does nothing and logs why: that
lane runs once per sample across a thread pool, so several of them writing a corpus verdict
would be a race whose winner is whichever sample finished last.

The [report]({{ '/en/reference/cli.html' | relative_url }}) is the clearest consequence. It
is a projection of persisted state, not a stage in the pipeline: it reads the same
`data` and `artifacts` any processor could have read, which is why a driver hunt, a
source audit and anything else render without the reporting code knowing what any of
them are. A pipeline supplies only the vocabulary, and that is a
[block of YAML]({{ '/en/reference/pipeline-yaml.html' | relative_url }}) rather than code.

Because the report holds nothing the run directory does not, it can be built while a run
is going, rebuilt after being deleted, and rebuilt again for a run that ended weeks ago.
The same property is what makes the LLM layer swappable: a backend is selected from the
pipeline's model string, and no processor, stage or state file is aware of which one
answered.
