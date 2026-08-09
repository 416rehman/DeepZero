---
layout: default
title: Pipeline YAML
order: 2
---

## Pipeline Configuration

A **Pipeline** in DeepZero is a declarative execution graph defining a continuous, resilient data transformation process. It translates a raw physical dataset into a high-signal analytical dataset.

The pipeline schema is rigorously defined in YAML. DeepZero resolves configuration dynamically, supporting shell-native variable expansion (e.g., `${VAR:-default}`).

### Configuration Schema

```yaml
name: my_pipeline
description: Standard vulnerability research pipeline
version: "1.0"
model: openai/gpt-4o  # scheme selects the backend, see below

settings:
  work_dir: work
  max_workers: 8  # Global ceiling on ThreadPoolExecutor thread limits

stages:
  # Stage 1: MUST be an IngestProcessor
  - name: discover
    processor: file_discovery
    config:
      extensions: ["*"]

  # Stage 2: Synchronous Filter
  - name: filter
    processor: metadata_filter
    config:
      require:
        is_executable: true

  # Stage 3: High-latency Map processing
  - name: decompile
    processor: ghidra_decompile/ghidra_decompile.py
    parallel: 4           # Restricts concurrency mapping to 4 concurrent Ghidra JVMs
    timeout: 300          # Enforces a strict 300-second kill clock per sample via process.py
    on_failure: skip      # Handles exceptions silently rather than aborting (skip, retry, abort)
    max_retries: 2        # Retry logic execution constraint
    config:
      ghidra_install_dir: ${GHIDRA_INSTALL_DIR}
```

### Stage Options

Every stage defined under the `stages:` array accepts the following attributes:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | string | `stage_N` | Unique stage name within the pipeline |
| `processor` | string | required | Processor reference (see below) |
| `config` | dict | `{}` | Processor-specific configuration |
| `parallel` | int | `4` | Concurrency for Map processors. `0` auto-scales to `os.cpu_count()` |
| `timeout` | int | `0` | Per-sample timeout in seconds (0 = no timeout) |
| `on_failure` | string | `skip` | Defines fault-tolerance behavior: `skip`, `retry`, or `abort` |
| `max_retries` | int | `0` | Retry count when `on_failure: retry` |

### Top-Level Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | string | the pipeline directory's name | Names the pipeline, and names its work directory |
| `description` | string | `""` | Free text |
| `model` | string | `""` | Model for every LLM stage. A pipeline with no LLM stage needs none; `deepzero validate` warns when one is missing |
| `settings` | dict | `{}` | `work_dir` (default `work`) and `max_workers` (default `min(4, cpu_count)`) |
| `knowledge` | dict | `{}` | Arbitrary pipeline-level values, readable by any processor via `ctx.get_knowledge(key)` |
| `report` | dict | `{}` | How `deepzero report` presents this pipeline's results, see below |
| `stages` | list | required | At least one, the first of which must be an ingest processor |

`work_dir` is the root, not the run directory. A run lands in
`<work_dir>/<pipeline name>/<corpus key>/`, where the corpus key is derived from the
target path, so two corpora through one pipeline never collide and each resumes on its
own. See the [CLI reference]({{ '/en/reference/cli.html' | relative_url }}).

### Choosing a Model

The part of `model` before the first `/` is a scheme, and it selects the backend:

| Model string | Backend |
|--------------|---------|
| `claude-code`, `claude-code/<model-id>` | The locally installed, already signed-in Claude Code CLI |
| anything else, e.g. `openai/gpt-4o`, `gemini/...`, `gpt-4o` | LiteLLM, which covers every API-key endpoint it supports |

`claude-code` runs a pipeline against a Claude Code subscription with no API key.
DeepZero never handles credentials for it: it invokes the CLI you already signed in to
and inherits whatever authentication that binary has. The part after the slash is
passed through as the model, so `claude-code/claude-opus-5` picks a specific model and
bare `claude-code` leaves the CLI on its default. Both shipped pipelines declare a
`claude-code` model, and `-m` overrides it for one run.

Because these calls carry untrusted content, decompiler output and source pulled from
strangers' repositories, the CLI is invoked with its tools and MCP servers denied. A
completion needs none of them, and leaving them enabled would let an injected prompt
reach a shell.

The registry is open: `register_backend()` adds a scheme without patching DeepZero, and
nothing in the provider, the pipeline or the stages needs to change to gain one. Any
scheme no backend claims falls through to LiteLLM.

Whichever backend is selected, it is asked whether it can run at all before a stage
needs it: `deepzero validate` checks the API key for a LiteLLM model and the presence of
the binary for an agent CLI, and [`deepzero run --preflight`]({{ '/en/reference/cli.html' | relative_url }})
goes further and confirms the CLI is signed in.

### Resolution Logic (`engine/registry.py`)

The shape of the `processor:` value decides how it is resolved, so a reference is never
ambiguous between an external file and a built-in name:

| Reference | Resolved as |
|-----------|-------------|
| Contains `/` or `\`, e.g. `ghidra_decompile/ghidra_decompile.py` | A file under `processors/` in the working directory. The first Processor subclass in it is used, ignoring the base classes themselves |
| The same, with `:ClassName` appended | That specific class in that file, which is what a file defining more than one processor needs |
| A bare name, e.g. `metadata_filter` | The internal registry, populated in `stages/__init__.py` |
| A bare name containing `:`, e.g. `my.python.module:MyClass` | An importable module on `sys.path`, and a class within it |

Anything else is an error naming the built-ins, rather than a failure later in the run.
Note that external paths resolve against the working directory, not against the pipeline
directory, which is why the shipped pipelines are run from the repository root.

### Dynamic Expansion

Before schema validation binds processors, DeepZero walks the entire YAML DOM tree, evaluating Regex matches against `\$\{([^}]+)\}`. Environment variables dictate the resolved runtime configuration. This explicitly prevents hardcoding API keys or installation directories within committed `.yaml` pipelines.

### Prompt Values

A stage whose `config` carries a `prompt` renders that file as a Jinja template. The
value can be a path or a filename sitting next to the pipeline; either way the file
is loaded, never used as the prompt text itself.

Every prompt can use these:

| Value | Type | Description |
|-------|------|-------------|
| `sample_name` | string | The sample's filename as the ingest stage recorded it |
| `sample_path` | string | Absolute path to the sample on disk |
| `history` | dict | `{stage_name: data}` for every stage that has already run |
| `config` | dict | This stage's own `config` block |

Beyond those, a prompt can use whatever the stages **before it** recorded. Each
processor declares those names in its `provides` attribute, and there are two kinds:

- **Data keys** — anything the processor puts in `data`, such as `device_name` or
  `finding_count`. Available under that name directly, and under `history`.
- **Artifacts** — a file the processor wrote, reachable by its path with the
  separators and the extension folded into the name. `decompiled/dispatch_ioctl.c`
  becomes `decompiled_dispatch_ioctl_c`. JSON is parsed into an object; `.c`, `.h`,
  `.txt`, `.md`, `.py`, `.yaml` and `.yml` arrive as text. Other file types are not
  exposed. Anything over the context budget is truncated, and oversized JSON is
  skipped with a warning rather than parsed.

A value is only available to stages *after* the one recording it, so a prompt cannot
reach its own stage's output.

To see what a given pipeline offers, run:

```bash
deepzero validate <pipeline>
```

A prompt naming something no earlier stage produces is reported as an error listing
what was available instead, and the same check fails the run if it is reached. This
matters because an unknown name would otherwise render as nothing: the model would be
asked to judge an empty payload, and the verdict would come back confident and
meaningless.

### The Report Block

`deepzero report` is built from what the engine guarantees, which is the same for every
pipeline: each stage records `data`, `artifacts` and a status. What differs is the
vocabulary. A kernel driver pipeline, a source-code audit and a licence sweep all
produce the same shapes of outcome and call them completely different things.

So the shapes are fixed and the words are declared:

```yaml
report:
  title: Source repository audit
  entity: repository
  entity_plural: repositories
  target_label: organisation
  classification_key: classification
  positive_when: [vulnerable]
  negative_when: [not exploitable]
  columns:
    - scan.finding_count
    - discover.primary_language
  findings_files: [findings.json]
```

Every field is optional, and every default reproduces the behaviour a pipeline had
before the block existed. A pipeline that declares nothing still gets a usable report.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `title` | string | `<pipeline name> results` | Heading of `index.html` |
| `entity` | string | `sample` | What one result is called in the UI |
| `entity_plural` | string | `entity` + `s` | Only needed where adding an s is wrong, e.g. repository |
| `target_label` | string | `corpus` | What the run was pointed at |
| `classification_key` | string | `classification` | The stage `data` key holding the conclusion |
| `positive_when` | list | `vulnerab`, `exploitab`, `confirmed` | Values counted as the thing you are looking for |
| `negative_when` | list | `safe`, `not vulnerab`, `benign`, `clean` | Values counted as nothing found |
| `columns` | list | picked automatically | `stage.key` values to show against each result |
| `findings_files` | list | `findings.json` | Filenames in a sample's directory to read findings from |
| `lexicon` | dict | see below | The words for the outcomes |

`vulnerable_when` and `safe_when` are accepted as the older names for `positive_when`
and `negative_when` and mean exactly the same thing. `positive_when` wins if both are
given.

`target_label` earns its place because the default, "corpus", assumes a pile of files on
disk. A run against a live application has a scope, a run over an organisation's
repositories has an organisation, and calling either a corpus reads as a mistake in a
report someone else is going to open.

#### How a Verdict is Matched

The value recorded under `classification_key` is lowercased and tested for the
`positive_when` substrings first, then the `negative_when` ones. Substrings, not exact
values, so `vulnerab` covers "vulnerable" and "vulnerability".

Testing positives first is what makes the defaults worth overriding. A pipeline whose
negative verdict is `[NOT EXPLOITABLE]` contains `exploitab`, which is a default
positive, so it would be counted as a hit. Narrowing `positive_when` to `[vulnerable]`
is what the shipped source audit does, and it is the case to check when a run's own
verdicts and the report's counts disagree.

A verdict matching neither list is not silently dropped. It lands under "Unclear
verdict", which is a different claim from having been judged safe.

#### Columns

`columns` names `stage.key` values, using the stage's name from this pipeline, and puts
each against every result. Declare the ones that decide what to read next: whether a
finding can be exercised at all, how much code was actually scanned, which revision was
judged. When none are declared, the report picks up to six numeric or
interestingly-named keys from what the run recorded.

Nothing needs to be added to the report for this. A key is available the moment a
processor records it in `data` and the pipeline names it here.

#### Findings

`findings_files` names files inside each sample's directory to read findings from. Any
JSON artifact whose contents look like a findings list is picked up as well, so a
processor writing under a different name still shows up without configuration.

#### The Lexicon

The report has one bucket for the thing being looked for, one for findings nothing has
ruled on, and one for a result analysed all the way through with nothing flagged. Those
are structural. Only their names are yours:

| Field | Default | Where it appears |
|-------|---------|------------------|
| `discipline` | `vulnerability research` | Beside the product name in the header |
| `positive` | `Vulnerable` | The label on the bucket, and its filter |
| `positive_help` | `an assessment stage concluded these are vulnerable` | The explanation shown against that label |
| `positive_phrase` | `assessed as vulnerable` | Completes "12 repositories ..." in the summary line |
| `nothing_positive` | `Nothing was confirmed vulnerable` | The headline when the run found nothing to act on |
| `unconfirmed` | `Needs assessment` | Findings exist, no assessment has ruled on them |
| `negative` | `Clear` | Analysed all the way through, nothing flagged |

The remaining outcomes are named by the engine and are not configurable, because they
describe what the engine did rather than what the pipeline was looking for: "Errored",
"Ran out of time", "Unclear verdict" and "Filtered out".

This is what takes the tool outside vulnerability research. A pipeline auditing
dependency licences has the same three outcomes and not one of the default words for
them, so it says what they are:

```yaml
report:
  entity: package
  target_label: dependency tree
  classification_key: licence_status
  positive_when: [incompatible]
  negative_when: [compatible]
  lexicon:
    discipline: licence compliance
    positive: Incompatible
    positive_help: the declared licence conflicts with this project's
    positive_phrase: carry an incompatible licence
    nothing_positive: No incompatible licences were found
    unconfirmed: Needs a decision
    negative: Compatible
```

Nothing else changes. The report still ranks, filters, groups and exports exactly as it
does for a driver hunt, because none of that ever depended on what the run was about.

### Review Marks

A pipeline records what it concluded. Whether a person has actually checked that
conclusion is a separate claim, and only the reader can make it, so the report
carries marks they add while reading.

On any result's page there are three:

| Mark | Means |
|------|-------|
| **confirmed** | checked, and it holds |
| **did not hold up** | checked, and it does not — a finished result with a definite answer |
| **outstanding** | looked at, but something is still unproven |

The last two open a note for what you ran, on what, and what happened, so someone
else can repeat the attempt. What counts as outstanding is left to the reader —
reproducing a crash, proving a precondition, reading a diff — because from the
report's side they are all the same shape of unfinished work.

Marks appear against each row in the index and can be filtered on, including
**Unreviewed**, which is the list of results nobody has looked at yet. The summary
counts each of them, so a run can be read as what is actually known rather than only
what was alleged: a result that did not hold up is never mistaken for one nobody has
examined.

The report is a file, so marks live in the browser. **Export marks** writes them out
as `marks.json`; save that next to `index.html` and they become part of the report:
rendered for anyone who opens it, and included in `inventory.csv` as `review` and
`review_note`. Marks are keyed on the pipeline and target rather than on the file
path, so re-running over the same corpus keeps them.
