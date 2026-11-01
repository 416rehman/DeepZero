# semgrep_scanner

A `BulkMapProcessor` that scans every active sample with semgrep. Starting one
semgrep process per sample would spend most of the run on process startup, so the
samples are gathered into batches, each batch is scanned in one invocation, and
the results are routed back to the sample each file came from.

It serves both shipped pipelines because what it scans is configurable. The
defaults suit a pipeline that decompiles first and writes C beside each sample,
so it reads `<sample dir>/decompiled`. A pipeline whose samples are already
source, a repository checkout for instance, sets `target_dir: ""` and the
sample's own path is scanned instead.

## How a batch is built

For each sample, every file under the scan directory whose suffix is in
`extensions` is hard linked into one flat directory, falling back to a copy when
the link fails. The flat name is the sample id, then the file's path within the
sample with the separators turned into `__`, so a checkout with forty files named
`index.js` keeps them apart. semgrep is pointed at that directory once, and each
result is attributed by looking its filename back up.

The batch directory is `.bulk_temp/semgrep_<n>` inside the run's own directory,
beside `samples/`, and it is removed after the batch, whether the batch worked or
not. The results document is
written to a file beside it rather than read back through a pipe, because
scanning thousands of files produces more JSON than a pipe wants to carry, and
that file is deleted once it has been read.

Some consequences of the flattening:

- The `file` recorded in each finding is the path semgrep reported, which is
  inside a batch directory that no longer exists by the time anyone reads
  `findings.json`. The path within the sample is still recoverable from the
  mangled name, but it is not a path you can open.
- Extension matching is an exact match on the file's last suffix, so it is case
  sensitive: a file named `Handler.C` is not collected by `extensions: [".c"]`.
- Nothing is excluded. semgrep runs with `--no-git-ignore`, and the ingest
  stage's own `exclude` patterns do not reach here, so vendored and generated
  code in a checkout is scanned and can produce findings. Discounting those is
  the assessment stage's job.

`PYTHONUTF8=1` is set for the semgrep process. semgrep writes its `--output` file
with the interpreter's default encoding, which on Windows is the ANSI codepage; a
scan that quotes a byte that codepage cannot represent, which any non-UTF-8 file
guarantees because the parse error quotes the bytes, then dies encoding its own
report and leaves an empty file behind, failing every sample in the batch.

## A findings.json already on disk is adopted, not rescanned

This is the surprising one, and it is a cache that lives outside the run state.

Before anything is scanned, each sample's own directory is checked for
`findings.json`. Three conditions have to hold together: the file exists, the
engine set `ProcessorEntry.cache_is_valid` on this entry, and the JSON parses.
Then those findings are the result, the sample is recorded with
`findings_cached: true`, and semgrep is never asked about it. A file that is
there but unreadable sends the sample to a real scan, and so does one the engine
has already declared stale.

`cache_is_valid` is the engine's answer to whether this stage's own output on
disk still describes the pipeline as it stands, and any processor that adopts its
previous output rather than doing the work again has to consult it. The engine is
what answers, because it is the only thing that knows what this stage read last
time.

Adoption is what stops an interrupted run from repeating batches it had already
finished. Editing the rules and running again does not get the old findings back,
though: `stage_input_digest` folds in the contents of every file or directory a
config string points at, and `rules_dir` is one of those, so an edited rule set
changes this stage's fingerprint and the findings already on disk stop counting
as a cache.

`deepzero run --redo <stage>` remains the way to force a rescan the fingerprint
cannot ask for on its own. The fingerprint covers the config and the files the
config names, not the processor's own code, not a new semgrep version, and not
the contents of the directory being scanned, because the corpus is deliberately
not hashed. A result recorded before fingerprinting existed carries an empty
digest and is trusted rather than redone, which is the other case for `--redo`.
It works because `findings.json` is recorded as an artifact on every path that
writes one, including the filtered path, so `--redo` can find the file and delete
it. Without that the file would outlive the run state that describes it, and the
next run would report findings the current rules cannot produce.

The check happens before the scan directory is looked for, so a sample whose
`findings.json` survives is adopted even if the directory that produced it is
gone. That holds only while the fingerprint still matches. Once it does not, the
sample goes looking for a scan directory that is no longer there and fails on
that instead.

## What it emits

Every key below lands in `history["<stage name>"].data` and is available to any
later stage's prompt, filter or ranking metric.

| Key | Meaning |
|---|---|
| `finding_count` | how many findings this sample has |
| `findings_cached` | whether they were adopted from disk rather than scanned for |
| `files_submitted` | how many of this sample's files were handed to semgrep |
| `files_scanned` | how many of those semgrep listed as read |
| `findings_json` | the name a prompt uses to reach `findings.json` |

`findings_json` is an artifact name, not a value: an artifact is addressed by its
path with the dot folded into the name.

An adopted result carries `finding_count` and `findings_cached` only.
`files_submitted` and `files_scanned` come from the semgrep run itself, so a
sample that was not scanned this time has neither. `files_scanned` is also absent
when semgrep returned no list of scanned paths.

The two counts are worth carrying in a report. Nothing found and nothing read
both show as `finding_count: 0`, and they are entirely different results: the
first says the rules did not match, the second says the files were never opened,
usually because `extensions` and the rules disagree about what the language is.

Each entry in `findings.json` has `rule_id`, `severity`, `message`, `file`,
`line_start`, `line_end` and `matched_code`. Severity is mapped from semgrep's
own: `ERROR` to `HIGH`, `WARNING` to `MEDIUM`, `INFO` to `LOW`, anything else to
`MEDIUM`.

`matched_code` is not always semgrep's. An unauthenticated semgrep CLI withholds
the matched source and returns the literal string `requires login` in its place,
with no flag to turn that off. That string is what an assessment prompt would
quote to a model and what a report would render, so when it appears the lines are
read back off the file semgrep scanned, using the span it reported. The snippet
stops at 40 lines with a note saying how many more there were.

## Results that are refused rather than reported as clean

Three outcomes look exactly like a clean corpus from the outside, and all three
fail the batch instead:

- semgrep returning load errors and no results at all, which is what a rule set
  that did not load looks like while still exiting 0.
- semgrep listing none of the files that were submitted to it. The scan never
  looked, and recording zero findings would send every sample on to assessment
  described as clean.
- no readable results document, in which case the failure message carries
  semgrep's exit code and the first 500 characters of its stderr.

A parseable results document wins over the exit code, because semgrep has been
seen emitting a complete document while exiting with an unexpected code.
Non-fatal errors alongside real results are logged and the results are kept.

A sample whose scan directory does not exist fails on its own, before any batch
is built, and the message asks whether the stage that produces that directory
runs before this one, which is usually the answer. A batch in which no sample had
a single matching file runs no semgrep at all, and every sample in it is recorded
with zero submitted, zero scanned and zero findings. That is the one case where
zero findings really does mean there was nothing to scan.

A batch that exceeds `timeout` fails every sample in it and nothing else, which
is the whole reason for batching: one timeout costs its own samples instead of
discarding a corpus after the work has already been done.

## Config

| Field | Default | Meaning |
|---|---|---|
| `rules_dir` | none, required | directory of semgrep rules to load |
| `target_dir` | `decompiled` | subdirectory of the sample's own work directory to scan; `""` scans the sample's own path instead |
| `extensions` | `.c`, `.h`, `.cpp`, `.py` | which files are handed to semgrep; a missing leading dot is added, and a single string is accepted for a one-entry list |
| `batch_size` | `200` | samples per semgrep invocation; `0` or less puts the whole stage in one run |
| `timeout` | `300` | seconds allowed for one batch's semgrep process |
| `min_findings` | `0` | filter out a sample with fewer findings than this; `0` filters nothing |

`min_findings` filters rather than fails, so the sample leaves the run with a
recorded reason and its `findings.json` still attached as an artifact. Both
shipped pipelines set `1`, which is what stops a sample nothing was flagged on
from costing a model call downstream. It applies to adopted findings too.

`timeout` here is the batch's own budget, read from this processor's config. The
engine's per-sample `timeout:` key is not applied to a bulk stage, which runs as
one invocation for the whole corpus, so this is the only timeout in play.

`rules_dir` is resolved against the working directory first, then against the
pipeline directory, and `validate()` and the scan resolve it the same way,
because resolving them differently once let validation pass while the scan ran
with no rules loaded.

This processor reads the raw config dict rather than declaring a `Config`
dataclass, so a key misspelled here is neither read nor reported.

`validate()` checks that the semgrep CLI is on PATH and that `rules_dir` is set
and exists. It does not check that the directory holds rules that load, so an
empty or broken rule set gets as far as the scan, where the batch fails rather
than reporting a clean corpus.

## In a pipeline

Scanning what an earlier stage decompiled:

```yaml
  - name: semgrep_scanner
    processor: semgrep_scanner/semgrep_scanner.py
    config:
      target_dir: decompiled
      rules_dir: pipelines/loldrivers/rules
      batch_size: 200
      min_findings: 1
```

Scanning the sample itself, when ingest produced a checkout rather than a file to
decompile. Keep `extensions` in step with the languages the rules are written
for, and with whatever the ingest stage counted:

```yaml
  - name: scan
    processor: semgrep_scanner/semgrep_scanner.py
    config:
      target_dir: ""
      rules_dir: pipelines/source_audit/rules
      extensions: [".py", ".js", ".ts", ".go"]
      # a repository contributes thousands of files where a driver contributed a
      # handful, so batches stay smaller here
      batch_size: 25
      timeout: 900
      min_findings: 1
```

```yaml
report:
  columns:
    - scan.finding_count
    # nothing found and nothing read both show as zero above
    - scan.files_scanned
```
