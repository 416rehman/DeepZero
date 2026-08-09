# git_ingest

An `IngestProcessor` that turns git repositories into samples, so a pipeline can
research source code the way the shipped one researches binaries. One sample is
one repository, and its `source_path` is the checkout root, which is what a
source scanner wants to be pointed at.

## Pointing it at repositories

The CLI target is always a real path, so both forms below keep resume and corpus
scoping working. Which one you get is decided by what the target is:

| Target | What happens |
|---|---|
| a **directory** | every immediate subdirectory is read as a checkout, nothing is fetched |
| a **file** | it is read as a manifest of repositories and each one is cloned |

### A directory of checkouts

```
repos/
  torvalds-linux/
  openssl-openssl/
  curl-curl/
```

```bash
deepzero run ./repos -p ./pipelines/source_audit/pipeline.yaml
```

Nothing is cloned and nothing is written to the corpus. A subdirectory with no
`.git` is still read; it just has no url, commit or branch to report. A target
that is itself a checkout (it has a `.git`) is treated as a single repository
rather than a container.

### A manifest of repositories

```bash
deepzero run ./repos.txt -p ./pipelines/source_audit/pipeline.yaml
```

Plain text, one repository per line, `#` starts a comment:

```
# core dependencies
https://github.com/psf/requests.git
git@github.com:openssl/openssl.git      # ssh works too
psf/black                               # owner/name means github
/mnt/mirrors/internal-service           # a local clone source
```

YAML is accepted as well, either a bare list or a mapping with a `repos:` key,
and an entry may pin a branch or tag:

```yaml
repos:
  - https://github.com/psf/requests.git
  - url: https://github.com/openssl/openssl.git
    ref: openssl-3.5
```

Clones land in a cache directory, not in the target, and a rerun reuses whatever
is already there so it costs no network at all. Because reuse is untouched, a
pin that changed since the clone was made is reported rather than applied; set
`refresh: true` to fetch it. A repository that cannot be cloned is logged and
skipped; it never ends the run. Nothing this processor did not create is ever
deleted: if the destination already holds something that is not a git checkout,
that repository is skipped and the tree is left alone.

## What it emits

Every key below lands in `history["<stage name>"].data` and is available to any
later stage's prompt, filter or ranking metric.

| Key | Meaning |
|---|---|
| `repo_url` | the url that was cloned, or the checkout's `origin` remote |
| `repo_host` | `github.com`, `gitlab.example.com`, empty for a local path |
| `repo_owner` | owner or group, keeping subgroups (`group/subgroup`) |
| `repo_name` | repository name without `.git` |
| `repo_full_name` | `owner/name`, or the directory name when there is no owner |
| `commit_sha` | the commit that was actually analysed, empty for a tree with no `.git` |
| `default_branch` | the branch the checkout is on |
| `ref` | the branch or tag a manifest pinned, absent when it pinned none |
| `checkout_source` | `cloned`, `reused` or `directory` |
| `total_files` | files in the tree after exclusions |
| `source_files` | of those, files in a counted language |
| `total_loc` | non-blank lines across the counted files |
| `languages` | language -> file count |
| `primary_language` | the language with the most files, ties broken by name |
| `dependency_manifests` | which of `package.json`, `go.mod`, `requirements.txt`, `pom.xml`, `Cargo.toml`, `Gemfile`, `composer.json` were found |
| `has_dependency_manifest` | whether any of them was found |

`host`, `owner` and `ref` are only recorded when they can be derived, so a
prompt should tolerate them being empty.

`sample_id` is derived from the repository's identity (`host/owner/name`, or the
url, or the directory name), so a rerun keeps the same sample and the same
repository reached through a manifest instead of a directory is the same sample.
Two trees that are the same repository are therefore read once, with a warning
naming the one that was kept.

A tree with no `.git` of its own is never asked what revision it is on, even
when it sits inside a checkout. Git would answer with the enclosing repository's
remote and revision, which would both misdescribe the tree and make every such
tree in a corpus look like the same repository.

## Config

| Field | Default | Meaning |
|---|---|---|
| `languages` | all built-in | a list of names to count, or a mapping of name -> extensions to count something the built-in map does not know |
| `extensions` | all of the above | count only these extensions; an unknown one is counted under its own bare name |
| `shallow` | `true` | `false` clones full history, which a pipeline that reads commits needs |
| `clone_depth` | `1` | depth passed to `git clone` when shallow |
| `cache_dir` | `.cache/<stage>/checkouts` | where clones live; relative paths resolve against the working directory |
| `refresh` | `false` | fetch existing clones instead of using them as they are |
| `exclude` | `.git`, `node_modules`, `vendor`, `dist`, `build`, `testdata` | glob patterns matched against each file and directory name, and against its path within the repository |
| `max_file_bytes` | `2000000` | a larger file still counts as a file of its language, but its lines are not read |
| `clone_timeout` | `900` | seconds allowed per clone or fetch |

Setting `exclude` replaces the defaults rather than adding to them, so list the
defaults you still want. `.git` is pruned regardless.

`validate()` checks that git is on PATH, that the depth is usable, and that the
language configuration leaves something to count, all before a single repository
is touched.

## In a pipeline

```yaml
stages:
  - name: discover
    processor: git_ingest/git_ingest.py
    config:
      languages: [python, javascript, typescript, go]
      cache_dir: .cache/repos
      clone_depth: 1

  # only repositories that declare dependencies
  - name: has_deps
    processor: metadata_filter
    config:
      require:
        has_dependency_manifest: true

  # the sample IS the tree to scan, so semgrep_scanner reads source_path itself
  - name: scan
    processor: semgrep_scanner/semgrep_scanner.py
    config:
      target_dir: ""
      extensions: [".py", ".js", ".ts", ".go"]
      rules_dir: pipelines/source_audit/rules
      min_findings: 1

  - name: rank
    processor: top_k
    config:
      metric_path: "scan.finding_count"
      keep_top: 0
      sort_order: desc
```

Because a repository is a tree rather than a file, a report for this kind of
pipeline reads better with the entity named:

```yaml
report:
  title: Source bug hunt
  entity: repository
  target_label: repository set
  columns:
    - scan.finding_count
    - discover.primary_language
    - discover.total_loc
```
