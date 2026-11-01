---
layout: default
title: State Persistence
order: 1
---

## Persistence Subsystem

Data integrity is handled by the `StateStore` (defined in `engine/state.py`). Operations executing against the filesystem are heavily mitigated against corruption, even against SIGKILL or OS-level interruption, via strict atomic swapping methodologies.

<div class="architecture-diagram" style="margin: 3rem 0;">
    <svg viewBox="0 0 800 250" style="width: 100%; height: auto; max-width: 800px;" xmlns="http://www.w3.org/2000/svg">
        <defs>
            <pattern id="isoGridState" width="40" height="23.094" patternUnits="userSpaceOnUse" patternTransform="scale(1)">
                <path d="M 40 0 L 0 23.094 M 0 0 L 40 23.094 M 20 23.094 L 20 0" fill="none" stroke="var(--border)" stroke-width="0.5"/>
            </pattern>
        </defs>

        <rect width="100%" height="100%" fill="url(#isoGridState)" opacity="0.3"/>
        
        <!-- Memory Node -->
        <g transform="translate(100, 120)">
            <rect x="0" y="-40" width="120" height="80" fill="var(--bg-primary)" stroke="var(--text-primary)" stroke-width="2" rx="8"/>
            <text x="60" y="-5" font-family="JetBrains Mono, monospace" font-size="14" font-weight="bold" text-anchor="middle" fill="var(--text-primary)">Memory</text>
            <text x="60" y="15" font-family="Inter, sans-serif" font-size="12" text-anchor="middle" fill="var(--text-tertiary)">SampleState</text>
        </g>

        <!-- Path to Temp -->
        <path d="M 220 120 L 320 120" fill="none" stroke="var(--text-tertiary)" stroke-width="2" stroke-dasharray="6 6"/>
        <text x="270" y="110" font-family="Inter, sans-serif" font-size="12" text-anchor="middle" fill="var(--text-secondary)">Serialize</text>
        
        <!-- Temp Node -->
        <g transform="translate(320, 120)">
            <rect x="0" y="-40" width="140" height="80" fill="var(--bg-secondary)" stroke="var(--border)" stroke-width="2" stroke-dasharray="4 4" rx="8"/>
            <text x="70" y="-5" font-family="JetBrains Mono, monospace" font-size="14" font-weight="bold" text-anchor="middle" fill="var(--text-secondary)">state.tmp</text>
            <text x="70" y="15" font-family="Inter, sans-serif" font-size="12" text-anchor="middle" fill="var(--text-tertiary)">Buffer</text>
        </g>
        
        <!-- Path to Final -->
        <path d="M 460 120 L 580 120" fill="none" stroke="var(--accent)" stroke-width="3"/>
        <circle cx="0" cy="0" r="5" fill="var(--accent)">
            <animateMotion path="M 460 120 L 580 120" dur="1.5s" repeatCount="indefinite" />
        </circle>
        <text x="520" y="110" font-family="Inter, sans-serif" font-size="12" font-weight="bold" text-anchor="middle" fill="var(--accent)">os.replace</text>
        <text x="520" y="140" font-family="Inter, sans-serif" font-size="10" text-anchor="middle" fill="var(--text-tertiary)">Atomic Swap</text>
        
        <!-- Final Node -->
        <g transform="translate(580, 120)">
            <rect x="-10" y="-30" width="120" height="80" fill="var(--bg-primary)" stroke="var(--border)" stroke-width="1" rx="4"/>
            <rect x="-5" y="-35" width="120" height="80" fill="var(--bg-primary)" stroke="var(--border)" stroke-width="1" rx="4"/>
            <rect x="0" y="-40" width="120" height="80" fill="var(--bg-primary)" stroke="var(--text-primary)" stroke-width="2" rx="4"/>
            <text x="60" y="-5" font-family="JetBrains Mono, monospace" font-size="14" font-weight="bold" text-anchor="middle" fill="var(--text-primary)">state.json</text>
            <text x="60" y="15" font-family="Inter, sans-serif" font-size="12" text-anchor="middle" fill="var(--text-tertiary)">Persistent</text>
        </g>
    </svg>
</div>

### Atomic Swaps (`atomic_replace`)

Instead of writing directly to expected artifacts (e.g., `state.json`), the persistence layer marshals data into temporary `.tmp` buffers. The buffer takes the destination's name with its suffix replaced rather than extended, so `state.json` is staged as `state.tmp`. Once serialization completes, an `os.replace` operation forcibly overwrites the destination atomic inode. A retry-backoff mechanism actively intercepts `PermissionError` locks triggered by host EDR/Antivirus heuristics scanning newly created binaries.

### Schema Versioning

Sample state is the part that is both tagged and gated. `state.json` is written with a
`_version` field carrying the internal `STATE_VERSION`, and on load anything older is
refused: reading a v1 JSON under a v2 runtime returns nothing at all, rather than inducing
unpredictable mutation bugs by interpreting a record under a schema that no longer
describes it.

The other two files are not gated. `run_manifest.json` carries the same `_version` field,
but nothing reads it back, because the manifest is a derived summary rewritten from the
samples every time they are saved. `run.json` is neither tagged nor checked: it is loaded
by filtering the JSON through `RunState`'s own field names and dropping anything
unrecognised, so a record written by an older version loads with whatever fields it has
and the rest left at their defaults.

### Workspace Hierarchy

```text
work/<pipeline_name>/<corpus_key>/
├── run.json             # Serialized `RunState`: execution metrics, pipeline metadata,
│                        #   the corpus-wide conclusion and the run's liveness record
├── pipeline.yaml        # Immutable snapshot of the pipeline YAML config during initialization
├── run_manifest.json    # Aggregated macro-overview of all samples, read by `status` and `interactive`
├── report/              # Browsable HTML report, rebuilt as results land
└── samples/
    └── <sample_id>/     # Isolated sandbox
        ├── state.json   # Serialized `SampleState`: Complete ledger of `StageOutput` maps
        ├── context.md   # Synthesized LLM context generated via `engine/context.py`
        └── ...          # Processor-specific artifacts
```

Two parts of `RunState` are worth naming beyond the metrics. `conclusion` holds a finding
about the corpus rather than about any one sample: which model sits behind an endpoint,
how many distinct bugs a pile of crashes represents, whether a scope is configured
correctly. It is written through `ctx.conclude(...)` by a stage that sees every sample,
and stays empty for the many pipelines whose answers are all per-sample. Alongside it,
`host`, `pid`, `pid_token` and `heartbeat_at` record who is writing the run: a status of
`running` is only a claim until the process behind it can be checked, and a killed run
never gets to withdraw the claim itself, so those four fields are what lets another
process tell a live run from an abandoned one.

### Corpus Scoping

The `<corpus_key>` segment is what keeps two targets through one pipeline apart. It is
derived from the run target: its basename, plus a short digest of the resolved absolute
path, so it is both readable and unambiguous. On Windows the path is case-folded first,
because `C:\Drivers` and `c:\drivers` are the same corpus.

Without that segment, pointing the same pipeline at a second corpus would resume into
the first one's sample store: samples that no longer correspond to anything on disk
would be treated as already analysed, and the run would report results for a corpus it
was never given. With it, each corpus has its own state, its own manifest and its own
report, and each resumes independently.

The same resolved path always maps to the same key, so a rerun lands back where it left
off. Nearly everything under this directory is derived, and deleting `report/` normally
costs a rebuild rather than a run.

There is one exception, and it is not recoverable. `report/marks.json` holds the review
marks: for each sample, whether a reader checked it and found it held or did not hold up,
plus a note. That is what the reader has checked, which no stage can know, so it exists
nowhere in the run state. It is saved back next to the report precisely so it renders for
anyone who opens it instead of being stranded in one person's browser, and it is re-read
on every rebuild. Deleting `report/` destroys it, as does `run --clean`, which removes the
whole corpus directory before starting.

### The `history` Ledger

The `SampleState.history` dictionary strictly maps processor stage names to instances of `StageOutput`. Output data structures are strictly isolated and namespaced. A downstream processor extracting metrics from an upstream map will query: `history["upstream_processor"].data.get("metric")` (see [Building Custom Processors]({{ '/en/extensibility/building-custom.html' | relative_url }})).

This namespacing permanently prevents field collision across divergent heuristic analysis techniques.

### Stage Input Fingerprints

Each `StageOutput` carries an `input_digest`: a fingerprint of the processor, configuration, and file dependencies tracked under the controls below. It is recorded when the stage completes and compared during resume to decide whether its saved result is stale.

Where both digests are present and they differ, the stored result describes inputs the
pipeline no longer has, so it counts as stale rather than done and the stage runs again.
This is what lets a resumed run work out for itself which results still hold, instead of
the reader having to remember what they edited. Where either digest is empty the question
cannot be asked, and an unanswerable question is not grounds for discarding work that may
have taken hours, so results written before the digest was recorded are trusted rather
than redone.

Fingerprints include the processor source, files referenced recursively by its config, and the global configuration the processor declares it reads. Changing the model invalidates LLM assessment and its descendants while preserving bundled non-LLM work such as decompilation. Invalidating an upstream result also discards downstream ledger entries and recorded artifacts. A downstream reducer recomputes its cohort when an upstream result or membership changes.

Custom processors conservatively fingerprint all global configuration unless they declare `cache_global_keys` (for example, `()` for a processor using only its own config). Include file dependencies in config; external resources or environment variables read privately inside processor code are not automatically tracked. Use `--redo <stage>` when such a dependency changes.

`cache_path_keys` selects the top-level config keys followed as file/directory dependencies (`None`: all; `()`: none). Use `cache_files(pipeline_dir)` for explicit dependencies, such as analysis scripts or version metadata, instead of hashing entire tool installations or output/cache directories.

### Refreshing the discovered corpus

A resumed run uses the saved discovery snapshot by default. Use `--refresh` to discover new or changed inputs at the same target path. Samples with unchanged discovery metadata keep their cached results; changed samples and their downstream results are reprocessed. Removed samples move out of the active run into `retired_samples/` with their artifacts preserved. `--redo discover` also repeats discovery for the bundled pipelines. Detection depends on the metadata the ingest processor records; it does not monitor arbitrary file or network changes.

For git manifests, also set `refresh: true` in the ingest stage config to fetch newer remote commits; `--refresh` alone revisits cached clones.

```bash
deepzero run ./drivers -p pipelines/loldrivers/pipeline.yaml --refresh
```

Each pipeline/corpus allows one writer at a time. An OS lock rejects a concurrent `deepzero run` before cleanup, redo, or refresh; it releases when the process exits, so a leftover lock file does not need manual deletion.
