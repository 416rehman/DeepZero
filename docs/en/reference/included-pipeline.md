---
layout: default
title: Included Pipelines
order: 3
---

## Included Pipelines

Two complete pipelines ship with DeepZero. They exist to be run, and to be read as
worked examples of what a pipeline definition looks like when it is doing something
real.

| Pipeline | Corpus | What it looks for |
|----------|--------|-------------------|
| `pipelines/loldrivers` | Windows kernel drivers on disk | BYOVD candidates: IOCTL surfaces reachable without the hardware |
| `pipelines/source_audit` | Git repositories | Source-level vulnerabilities reachable from untrusted input |

Both declare `model: claude-code/claude-opus-5`, so they run against a Claude Code
subscription with no API key. Override with `-m` for any LiteLLM model. See
[Choosing a Model]({{ '/en/reference/pipeline-yaml.html' | relative_url }}).

---

## LOLDrivers Pipeline

A reference BYOVD (Bring Your Own Vulnerable Driver) pipeline is maintained in
`pipelines/loldrivers/`.

| Stage | Processor | What it does |
|-------|-----------|--------------|
| `discover` | `pe_ingest/pe_ingest.py` | PE ingestion and LIEF header parsing |
| `kernel_filter` | `metadata_filter` | Constrains to kernel-mode drivers exposing IOCTL surfaces, and deduplicates on hash |
| `loldrivers_filter` | `loldrivers_filter/loldrivers_filter.py` | Excludes known entities cataloged via loldrivers.io |
| `decompile` | `ghidra_decompile/ghidra_decompile.py` | Executes Ghidra headless decompilation |
| `semgrep_scanner` | `semgrep_scanner/semgrep_scanner.py` | Bulk static analysis against the exported C source. A driver with nothing flagged stops here (`min_findings: 1`) |
| `rank_by_findings` | `top_k` | Orders every surviving driver by finding count, worst first |
| `assess` | `generic_llm` | Renders `assessment.j2` per driver and records the verdict |

The ranking stage keeps everything (`keep_top: 0`) and only changes the order. That is
deliberate: dropping all but a top tier saves assessment calls but decides which drivers
are worth reading using a finding count, which is exactly the judgement the assessment
stage exists to make. Ordering worst-first gets the same drivers looked at first
without throwing the rest away, and a run stopped early has still spent its time on the
noisiest drivers.

The exclusions run before decompilation for the same reason in reverse: Ghidra is by far
the most expensive stage, so every driver removed by a cheap header check or a hash
lookup is minutes not spent.

### Whether a finding can be exercised without the hardware

Many drivers create their device object only once their hardware is enumerated. On a
machine or VM without that device, `\.\<name>` never opens, so nothing the driver
exposes can be reached — and from the report alone that is indistinguishable from the
driver not being vulnerable.

The `decompile` stage records where the device object is created:

| Value | Meaning |
|-------|---------|
| `device_created_in` | the function that calls `IoCreateDevice` |
| `device_on_load_path` | whether that function is `DriverEntry`, or something it calls |

`device_on_load_path: true` means the device appears on any machine that will load the
driver, so a finding against it can be confirmed today. `false` means it is created
somewhere else — typically a PnP add-device or start-device callback — and confirming
anything needs the physical device. Neither is recorded when `IoCreateDevice` is not
found at all, rather than guessing.

The bundled pipeline lists `decompile.device_on_load_path` under `report.columns`, so
it shows against each driver. That is all it takes: the value is declared in the
processor's `provides` and named by the pipeline, and the report stays unaware of what
a device object is.

### What decompilation writes per driver

The `decompile` stage writes into each sample's `decompiled/` directory:

| File | Contents |
|------|----------|
| `dispatch_ioctl.c` | The dispatch routine, recorded once |
| `ioctls/0xXXXXXXXX.c` | One per IOCTL code: what the code decodes to, pointing at the routine above |
| `ghidra_result.json` | Metadata — device name, symbolic link, dispatch name, and one entry per IOCTL code |

Every code in a driver is handled by the same routine, so it is stored once and
referenced, never copied per code. An entry in `ioctl_handlers` holds only the code and
its decoded fields (`hex`, `device_type`, `function`, `method`, `access`).

Size is worth watching, because the failure mode here is silent — output still looks
correct, just enormous. As a reference point, a pack of 1,388 decompiled drivers
produces roughly **28 MB** of `ghidra_result.json` in total. Storing the routine per
code instead produced **734 MB** for the same corpus, with a single driver reaching
52 MB. A stage run whose output is orders of magnitude above this has regressed to
repeating the routine, and the assessment stage will then parse that document per
driver when building its prompt.

`tests/test_extract_dispatch.py` guards the entry shape directly.

### Prerequisites

- Ghidra, with `GHIDRA_INSTALL_DIR` set. `JAVA_HOME` is read if present.
- `semgrep` on PATH: `pip install semgrep`.

---

## Source Audit Pipeline

A source-code audit over git repositories, in `pipelines/source_audit/`. Each
repository is taken at one revision, scanned with semgrep, then read by a model whose
job is to separate a real vulnerability from a rule matching a shape in the code.

| Stage | Processor | What it does |
|-------|-----------|--------------|
| `discover` | `git_ingest/git_ingest.py` | Clones each repository at depth 1, or reads a checkout already on disk, and records the revision everything downstream is judging |
| `size_filter` | `metadata_filter` | Drops checkouts with no source in them and trees too large to be worth scanning; a commit reached under two names is scanned once |
| `scan` | `semgrep_scanner/semgrep_scanner.py` | Runs `rules/` over each checkout. A repository with nothing flagged stops here |
| `rank` | `top_k` | Orders every surviving repository by finding count, worst first, dropping none |
| `assess` | `generic_llm` | Renders `assessment.j2` per repository and records the verdict |

The two halves matter in that order. Semgrep is cheap and finds every place worth
looking; almost all of those places are fine. The assessment stage is where a finding
either gains a path from attacker input to the sink or is written off, by name, as
unreachable.

### What to point it at

`deepzero run` takes one target, and the ingest stage reads either shape:

- **A directory**, where every immediate subdirectory is one checkout. Nothing is
  fetched, so private code never has to leave the machine it is already on. A directory
  that is itself a checkout is read as a single repository, and a plain source drop with
  no `.git` is still read; it simply has no revision or origin to report.
- **A file**, read as a manifest of repositories to clone. Plain text, one per line,
  with `#` comments, or YAML as a list or a mapping with a `repos:` key whose entries
  may pin a ref.

```bash
# audit the repositories listed in a manifest
deepzero run repos.txt -p pipelines/source_audit/pipeline.yaml

# or a directory of checkouts already on disk
deepzero run C:\code\vendor -p pipelines/source_audit/pipeline.yaml
```

Clones live in the ingest stage's own cache directory rather than in the work
directory, so a rerun costs no network and `--clean` does not throw them away.

### Rules and languages

`rules/` holds 136 semgrep rules covering Python, JavaScript, TypeScript, Go, Java,
Ruby, PHP and C#, grouped by what they look for: injection, path traversal and SSRF,
authentication and authorisation, crypto and secrets, deserialisation, and XSS and
response headers.

Three places have to agree: the rules, the `extensions` list on `discover`, and the
identical list on `scan`. They fail in opposite directions. An extension the lists miss
is neither counted nor scanned, so the repository comes out looking smaller and cleaner
than it is. An extension the lists carry that no rule covers is walked, counted and
staged for a scan that can never match it. Adding a language means all three, and
`tests/test_source_audit_pipeline.py` fails if they drift apart.

A repository written in a language `rules/` does not cover therefore counts zero source
files and is dropped by `size_filter`. That reads as "no source" when it means "nothing
here this pipeline can audit", and it is still the outcome worth having: the tree is
dropped one stage after the clone rather than staged for a scan whose rules could never
fire.

### Reading its report

The pipeline declares its own vocabulary, because a repository is not a file on disk:

```yaml
report:
  title: Source repository audit
  entity: repository
  entity_plural: repositories
  target_label: organisation
  classification_key: classification
  vulnerable_when: [vulnerable]
  safe_when: [not exploitable]
  lexicon:
    negative: Not exploitable
```

`vulnerable_when` is narrowed for a reason worth knowing about. The assessment answers
`[VULNERABLE]` or `[NOT EXPLOITABLE]`, and the default positive list includes
`exploitab`, which the negative verdict contains. See
[How a Verdict is Matched]({{ '/en/reference/pipeline-yaml.html' | relative_url }}).
`vulnerable_when` and `safe_when` are the older spellings of `positive_when` and
`negative_when` and still mean the same thing.

The one lexicon override is there because a repository only reaches the assessment when
the scan flagged something. Nothing in the negative bucket is untouched code: it is a
repository whose findings were read and none of them reached. "Clear", the default word
for that bucket, says the opposite.

Its `columns` put finding count, files scanned, source file count, primary language and
revision against each repository. Files scanned earns its place: a repository with no
findings and a repository whose files semgrep never opened both show zero findings, and
only one of those is a result.

### Prerequisites

- `git` on PATH, for the `discover` stage.
- `semgrep` on PATH: `pip install semgrep`.

Check all of it, for either pipeline, before committing to a long run:

```bash
deepzero validate pipelines/source_audit/pipeline.yaml
```

It exits 1 if it reports an error, so it can gate a commit rather than only being read.
