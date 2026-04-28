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
            <text x="70" y="-5" font-family="JetBrains Mono, monospace" font-size="14" font-weight="bold" text-anchor="middle" fill="var(--text-secondary)">state.json.tmp</text>
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

Instead of writing directly to expected artifacts (e.g., `state.json`), the persistence layer marshals data into temporary `.tmp` buffers. Once serialization completes, an `os.replace` operation forcibly overwrites the destination atomic inode. A retry-backoff mechanism actively intercepts `PermissionError` locks triggered by host EDR/Antivirus heuristics scanning newly created binaries.

### Schema Versioning

All state objects are tagged with an internal `STATE_VERSION`. If the engine encounters schema drift during deserialization (e.g., reading a v1 JSON under a v2 runtime), it explicitly deprecates the state object rather than inducing unpredictable mutation bugs.

### Workspace Hierarchy

```text
work/<pipeline_name>/
├── run.json             # Serialized `RunState`: Execution metrics and pipeline metadata
├── pipeline.yaml        # Immutable snapshot of the pipeline YAML config during initialization
├── run_manifest.json    # Aggregated macro-overview of all samples (used by Starlette API)
└── samples/
    └── <sample_id>/     # Isolated sandbox
        ├── state.json   # Serialized `SampleState`: Complete ledger of `StageOutput` maps
        ├── context.md   # Synthesized LLM context generated via `engine/context.py`
        └── ...          # Processor-specific artifacts
```

### The `history` Ledger

The `SampleState.history` dictionary strictly maps processor stage names to instances of `StageOutput`. Output data structures are strictly isolated and namespaced. A downstream processor extracting metrics from an upstream map will query: `history["upstream_processor"].data.get("metric")` (see [Building Custom Processors]({{ '/extensibility/building-custom.html' | relative_url }})).

This namespacing permanently prevents field collision across divergent heuristic analysis techniques.
