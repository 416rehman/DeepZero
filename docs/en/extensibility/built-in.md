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
| `hash_exclude` | Map | Cryptographic exclusions against inline lists or flat files, in-run deduplication via `dedup`, and the field the hash is read from via `hash_field` (`sha256` unless set). |
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
[included pipelines]({{ '/en/reference/included-pipeline.html' | relative_url }}) use.
`ghidra_decompile`, `git_ingest` and `loldrivers_filter` declare their accepted keys as a
`Config` dataclass, so the source is the list of them and a key misspelled in a pipeline is
reported rather than ignored. `pe_ingest` and `semgrep_scanner` read the raw config dict,
where a misspelled key is neither read nor reported. Each carries a README beside its
source describing what it emits and the behaviour a reader would be surprised by.

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

| Field | Default | Meaning |
|-------|---------|---------|
| `rules_dir` | none, required | Directory of semgrep rules to load. |
| `target_dir` | `decompiled` | Subdirectory of the sample's own work directory to scan. Set it to `""` and the sample's own path is scanned instead. |
| `extensions` | `.c`, `.h`, `.cpp`, `.py` | Which files are handed to semgrep. A leading dot is added if it is missing, and a single string is accepted for a one-entry list. |
| `batch_size` | `200` | Samples per semgrep invocation. `0` or less puts the whole stage in one run. |
| `timeout` | `300` | Seconds allowed for one batch's semgrep process. |
| `min_findings` | `0` | Filter out a sample with fewer findings than this. `0` filters nothing. |

`target_dir` and `extensions` are what let one scanner serve both shipped pipelines. The
defaults suit a pipeline that decompiles first and writes C beside each sample. A
pipeline whose samples are already source, a repository checkout for instance, sets
`target_dir: ""` and widens `extensions` to whatever it actually ingested.

`rules_dir` is resolved against the working directory first, then against the pipeline
directory, and both `validate()` and the scan itself resolve it the same way, because
resolving them differently once let validation pass while the scan ran with no rules
loaded. A `rules_dir` that does not exist when the stage runs fails every sample in it
rather than scanning with nothing loaded and reporting a clean corpus.

#### A findings.json already on disk is adopted, not rescanned

This is the surprising one. Before scanning anything, the processor looks for
`findings.json` in each sample's own directory. If it is there, the engine reports the
cached result as still valid, and the file parses, those findings are taken as the
result, the sample is recorded with `findings_cached: true`, and semgrep is never asked
about it. Validity is not the processor's to judge: the engine compares this stage's
current fingerprint against the one the previous result was recorded under, so it is the
only thing that knows whether the file still describes the rules and config in force. If
the file is unreadable the sample is rescanned instead.

That is what stops an interrupted run from repeating batches it had already finished.
Editing the rules invalidates the cache on its own: `rules_dir` is a config value naming
a directory, so the rule files themselves are folded into the fingerprint, and a result
recorded under a different fingerprint is stale rather than adopted.
`deepzero run --redo <stage>` is still the way to force a rescan for what the fingerprint
cannot see, and it works because `findings.json` is recorded as an artifact on every path
that writes one, including the filtered path, so `--redo` can find the file and delete
it. A result recorded before fingerprinting existed carries an empty digest, and those
are trusted as they stand: discarding a corpus because it predates the feature would be
the worse guess.

An adopted result carries `finding_count` and `findings_cached` only. `files_submitted`
and `files_scanned` come from the semgrep run itself, so a sample that was never scanned
this time has neither.

#### Batching, and the failures worth knowing about

Samples are scanned in batches rather than in one run, so a batch that times out or
comes back unreadable costs only its own samples instead of discarding a whole corpus
after the work has already been done. A batch that exceeds `timeout` records every
sample in it as failed.

`extensions` and the rules have to agree. A file whose extension is not listed is never
handed to semgrep, however many rules would have matched it, and that failure is silent:
the scan reports zero findings, which is indistinguishable from a clean tree. This is
why the source audit pipeline records `files_scanned` alongside `finding_count`.

Two more results are refused rather than reported as clean, because both look exactly
like a clean corpus from the outside: semgrep coming back with load errors and no
results at all, and semgrep listing none of the files that were submitted to it. Both
fail the batch and say so.

A sample whose `target_dir` is not on disk fails on its own, before any batch is built,
and the message asks whether the stage that produces that directory runs before this
one, which is the usual answer.

`min_findings` filters a sample at this stage rather than failing it, so it leaves the
run with a recorded reason and its `findings.json` still attached. The shipped pipelines
both set `min_findings: 1`, which is what stops a sample nothing was flagged on from
costing a model call downstream.
