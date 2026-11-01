# Source audit

A source-code audit over git repositories. Each repository is taken at one revision,
scanned with semgrep, and then read by a model whose job is to separate a real
vulnerability from a rule matching a shape in the code.

The two halves matter in that order. Semgrep is cheap and finds every place worth
looking; almost all of those places are fine. The assessment stage is where a finding
either gains a path from attacker input to the sink or is written off, by name, as
unreachable.

## Stages

| Stage | Processor | What it does |
|-------|-----------|--------------|
| `discover` | `git_ingest/git_ingest.py` | Clones each repository at depth 1, or reads a checkout already on disk, and records the revision and what is in the tree |
| `size_filter` | `metadata_filter` | Drops checkouts with no source in them and trees too large to be worth scanning, and scans a commit once however many names reach it |
| `scan` | `semgrep_scanner/semgrep_scanner.py` | Runs `rules/` over each checkout. A repository with nothing flagged stops here |
| `rank` | `top_k` | Orders every surviving repository by finding count, worst first, dropping none |
| `assess` | `generic_llm` | Renders `assessment.j2` per repository and records the verdict |

The assessment answers one question per finding: does untrusted input reach the sink,
what does an attacker get, and what would confirm it. Its first line is `[VULNERABLE]`
or `[NOT EXPLOITABLE]`, which is what the report groups on.

`min_findings: 1` means a repository only reaches the assessment when the scan flagged
something, so a rendered prompt with no findings in it means the scan output could not
be read back, not that the tree is clean. The prompt says so and asks for neither
marker, which lands the repository under "Unclear verdict" rather than among the
repositories something actually looked at.

## What to point it at

`deepzero run` takes one target, and this pipeline accepts either shape.

**A manifest file**, for code that is not on the machine yet. One repository per line:

```
https://github.com/acme/widget.git
git@github.com:acme/gadget.git
acme/thing                          # shorthand, resolved against github
/srv/mirrors/internal-lib           # a local repository is a fine clone source
```

Blank lines and `#` comments are ignored. A `.yaml` manifest works too, either a list
or a mapping with a `repos` key, and its entries may pin a ref:

```yaml
repos:
  - url: https://github.com/acme/widget.git
    ref: v2.1.0
  - https://github.com/acme/gadget.git
```

**A directory of checkouts**, for code that is already cloned or that is private
enough that fetching it is somebody else's step. Each subdirectory is one repository;
a directory that is itself a checkout is taken as a single repository. A plain source
drop with no `.git` is still read, it simply has no revision or origin to report.

Clones live in the `discover` stage's own cache, outside the work directory, so a
rerun costs no network and `--clean` does not throw them away. Set `refresh: true` on
that stage to fetch before reading.

A normal resume keeps its saved discovery snapshot. Pass `--refresh` to discover the
corpus again. For a manifest, also set `refresh: true` in the `discover` stage's config
to fetch newer remote commits; `--refresh` by itself revisits the cached clones.

## Prerequisites

- `git` on PATH, for the `discover` stage.
- `semgrep` on PATH: `pip install semgrep`.
- Rules in `rules/`. The scan stage fails loudly if that directory is missing rather
  than scanning with nothing loaded.
- A model. The pipeline defaults to `claude-code`, which uses your Claude Code CLI
  default model. Install that CLI and sign in with your own account. No API key
  is needed. For an API-backed model, install `python -m pip install -e ".[llm]"`,
  configure its API key, and set `DEEPZERO_MODEL` in `.env` or pass `-m`.

Check all of it before a long run:

```bash
deepzero validate pipelines/source_audit/pipeline.yaml
```

## Example

Run these commands from the cloned repository. Replace `./checkouts` with your own
directory, or create `repos.txt` with one repository URL per line.

```bash
# audit the repositories listed in a manifest
deepzero run repos.txt -p pipelines/source_audit/pipeline.yaml

# or a directory of checkouts already on disk
deepzero run ./checkouts -p pipelines/source_audit/pipeline.yaml

# read the results
deepzero report -p source_audit --open
```

## Languages

`rules/` covers Python, JavaScript, TypeScript, Go, Java, Ruby, PHP and C#. The
`extensions` list on `discover` and the identical list on `scan` name the file
extensions those eight are written in, and nothing else.

Three places have to agree, and they fail in opposite directions. An extension the
lists miss is neither counted nor scanned, so the repository comes out looking smaller
and cleaner than it is. An extension the lists carry that no rule covers is walked,
counted and staged for a scan that can never match it. Adding a language means all
three; `tests/test_source_audit_pipeline.py` fails if they drift apart.

A repository in a language `rules/` does not cover therefore counts zero source files
and is dropped by `size_filter` with `source_files=0 < min 1`. That reads as "no
source" when it means "nothing here this pipeline can audit". It is still the outcome
worth having: the tree is dropped one stage after the clone rather than staged for a
scan whose rules could never fire.

## What the stages record

`size_filter` and `assessment.j2` are written in terms of the keys below, so renaming
one breaks them. `size_filter` is the one that bites: `metadata_filter` reads a
missing numeric field as zero, so if `source_files` ever stops being recorded under
that name, every repository is filtered out as empty at the second stage and the run
looks finished in seconds.

| Key | From | Used by |
|-----|------|---------|
| `source_files` | discover | `min_source_files` / `max_source_files`, the report, the prompt |
| `total_loc` | discover | `max_total_loc`, the prompt |
| `commit_sha` | discover | dedup, the report, the prompt |
| `repo_url`, `ref`, `default_branch` | discover | the prompt |
| `languages`, `primary_language` | discover | the report, the prompt |
| `finding_count` | scan | ranking, the report, the prompt |
| `files_scanned`, `files_submitted` | scan | the report, the prompt |
| `findings_json` | scan | the prompt |

`ref` is only recorded when a manifest pinned one, and `repo_url` and `commit_sha`
are empty for a source tree that is not a git checkout, so the prompt treats all of
them as optional.

The exclusions on `discover` (`vendor`, `node_modules`, `third_party` and the rest)
keep those trees out of the counts, but the scanner takes no exclusions and does scan
them. That is why the prompt is told to discount a finding in vendored or generated
code: it belongs to the upstream project, if to anyone.

## Reading the report

`report.columns` names finding count, files scanned, source file count, primary
language and revision, in the order they are worth reading. The summary page has room
for the first few of them beside each repository's name; every one of them is on the
repository's own page and in `inventory.csv`. Files scanned earns its place at the
front: a repository with no findings and a repository whose files semgrep never opened
both show zero findings, and only one of those is a result.

The verdict a run records and what a person has checked are separate claims. Mark
each repository you work through in the report itself, and export the marks so they
survive the next run.
