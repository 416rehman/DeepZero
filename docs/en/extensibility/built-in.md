---
layout: default
title: Built-in Processors
order: 1
---

## Built-in Processors

Referenced by bare name. Run `deepzero list-processors` to see them with their
implementing classes.

| Identifier | Type | Functionality |
| ---------- | ---- | ------------- |
| `file_discovery` | Ingest | Recursive filesystem traversal and cryptographic hashing. |
| `metadata_filter` | Map | Field equality via `require:`, numeric thresholds via any `min_<field>` / `max_<field>` key, and deduplication via `dedup_field`. Fields are read from the merged data of every upstream stage. |
| `hash_exclude` | Map | Cryptographic exclusions against inline lists or flat files. |
| `generic_llm` | Map | Jinja2 template rendering, LLM invocation, and response parsing. |
| `generic_command` | Map | Arbitrary shell execution with contextual variable substitution. |
| `top_k` | Reduce | Truncates sample set based on numeric scalar values. |
| `sort` | Reduce | Deterministic sample reordering without dataset reduction. |

A `min_<field>` threshold reads a field no upstream stage recorded as zero, and filters
the sample. That is the right answer for a field that is genuinely absent and the wrong
one for a field that got renamed, so a stage that suddenly filters an entire corpus in
seconds is worth checking against the names its upstream actually provides.

## Bundled External Processors

These live in `processors/` and are referenced by path, so they are read as ordinary
external processors rather than as privileged built-ins. They are the ones the
[included pipelines]({{ '/en/reference/included-pipeline.html' | relative_url }}) use, and
each carries a README next to its source with its full configuration.

| Path | Type | Functionality |
| ---- | ---- | ------------- |
| `pe_ingest/pe_ingest.py` | Ingest | Discovers PE files, parses headers, and extracts driver metadata. |
| `git_ingest/git_ingest.py` | Ingest | Turns git repositories into samples, from a directory of checkouts or a manifest of URLs. |
| `loldrivers_filter/loldrivers_filter.py` | Map | Excludes samples whose SHA-256 matches a known entry in the loldrivers.io database. |
| `ghidra_decompile/ghidra_decompile.py` | Map | Ghidra headless decompilation with a configurable post-script. |
| `semgrep_scanner/semgrep_scanner.py` | BulkMap | Batched semgrep scan across the active samples. |

### `git_ingest`

One sample is one repository, and its `source_path` is the checkout root, which is what
a source scanner wants to be pointed at. The CLI target is always a real path, so both
input shapes keep resume and corpus scoping working: a directory is read as a container
of checkouts and nothing is fetched, while a file is read as a manifest and each entry
is cloned.

`sample_id` is derived from the repository's identity rather than from a path, so the
same repository reached through a manifest and through a directory is the same sample,
and a rerun keeps its results.

### `semgrep_scanner`

Two config values decide what gets scanned, and they are what let one scanner serve both
shipped pipelines:

| Field | Default | Meaning |
|-------|---------|---------|
| `target_dir` | `decompiled` | Subdirectory of the sample's own work directory to scan. Set it to `""` and the sample's own path is scanned instead. |
| `extensions` | `.c`, `.h`, `.cpp`, `.py` | Which files are handed to semgrep. |

The default suits a pipeline that decompiles first and writes C beside each sample. A
pipeline whose samples are already source, a repository checkout for instance, sets
`target_dir: ""` and widens `extensions` to whatever it actually ingested.

`extensions` and the rules have to agree. A file whose extension is not listed is never
handed to semgrep, however many rules would have matched it, and that failure is silent:
the scan reports zero findings, which is indistinguishable from a clean tree. This is
why the source audit pipeline records `files_scanned` alongside `finding_count`.

Samples are scanned in batches (`batch_size`, default 200) rather than in one run, so a
batch that times out or comes back unreadable costs only its own samples instead of
discarding a whole corpus after the work has already been done.
