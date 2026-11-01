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
    timeout: 300          # Per-sample budget: the stage stops waiting after 300 seconds
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
| `parallel` | int | `4` | Concurrency for Map processors. `0` auto-scales, within the caps below |
| `timeout` | int | `0` | Per-sample budget in seconds for Map stages (0 = no budget) |
| `on_failure` | string | `skip` | Defines fault-tolerance behavior: `skip`, `retry`, or `abort` |
| `max_retries` | int | `0` | Retry count when `on_failure: retry` |
| `limit` | int | `0` | Sits inside `config`, read by the engine: truncate the surviving corpus after this stage (0 = keep everything) |

#### `parallel`

`parallel: 0` means auto rather than unlimited. The runner starts from `os.cpu_count()`
and then lowers it twice: to the ceiling the processor declares in `max_parallelism()`,
and to the pipeline's `max_workers` setting, whichever is smaller. A processor that
spawns one JVM or one external tool per sample declares that ceiling precisely so a
default `parallel: 0` cannot exhaust the machine, and the run logs which cap it applied.
An explicit `parallel: N` is honoured exactly as written and is capped by neither.

#### `timeout`

`timeout` is the budget one sample gets in a Map stage. When it runs out the stage stops
waiting, records that sample as having run out of time, and moves on to the next one.

What it does not do is kill anything. Nothing in Python can stop a thread that is
already running, so the processor's own worker thread is abandoned rather than
terminated: an external process it started keeps running until it ends on its own, and
whatever memory that thread holds is held until it returns. The budget bounds how long
the *stage* waits, not how long the work takes. A processor that shells out should pass
a limit to the tool as well, which is what `semgrep_scanner` does with its own `timeout`
config key.

Only Map stages are covered. Reduce and bulk-map stages are one invocation for the whole
corpus rather than one per sample, and neither runs under this budget.

Running out of time is not a failure, so `on_failure: retry` does not retry it, and a
resumed run leaves it alone because the budget that was too short still is. Asking for
another attempt is what [`--retry-timeouts`]({{ '/en/reference/cli.html' | relative_url }})
is for.

#### `limit`

`limit` goes inside a stage's `config` block, but the engine reads it rather than the
processor, so it can be set on any stage regardless of what that processor accepts, and
a processor declaring a typed `Config` will not warn that the key is unknown to it.

Once the stage finishes, every still-active sample past the first `limit` of them is
marked filtered at that stage and takes no further part in the run. The count is over
the whole surviving corpus, not over the samples this one stage touched.

Order is the order the run is currently carrying the corpus in, which is what makes
`limit` worth setting on a reduce stage or the one after it. A reduce returns its
survivors ranked, the runner adopts that ranking before the truncation happens, and
`limit` then keeps the highest-ranked rather than an arbitrary slice. On a stage with
no ranking behind it, it keeps whichever samples happen to come first.

### Top-Level Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | string | the pipeline directory's name | Names the pipeline, and names its work directory |
| `description` | string | `""` | Free text |
| `version` | string | none | Free-form metadata the engine never reads. Both shipped pipelines declare one by convention, for whoever maintains them |
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
passed through as the model, so `claude-code/opus` picks a specific model and
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
| Contains `/` or `\`, e.g. `ghidra_decompile/ghidra_decompile.py` | A file under one of the processor roots listed below. The first Processor subclass in it is used, ignoring the base classes themselves |
| The same, with `:ClassName` appended | That specific class in that file, which is what a file defining more than one processor needs |
| A bare name, e.g. `metadata_filter` | The internal registry, populated in `stages/__init__.py` |
| A bare name containing `:`, e.g. `my.python.module:MyClass` | An importable module on `sys.path`, and a class within it |

Anything else is an error naming the built-ins, rather than a failure later in the run.

A reference carrying a separator is looked for under five roots, in this order, and the
first one that exists wins:

1. every path in `$DEEPZERO_PROCESSORS`, separated the way this platform separates
   `PATH` entries: `;` on Windows, `:` elsewhere
2. `processors/` in the working directory
3. `processors/` beside the pipeline's own YAML
4. `processors/` in the pipeline directory's parent
5. the pipeline directory itself, for a pipeline keeping a processor next to its YAML
   rather than in a subdirectory

The working directory is searched before the pipeline directory, which is why the
shipped pipelines resolve from the repository root. It is not the only root, though: a
pipeline kept anywhere can carry its own processors beside it and be run from any
directory, without the engine dictating where the command happens to be issued from.

`$DEEPZERO_PROCESSORS` is searched ahead of every other root, which is what makes it a
shared library of processors: a name found there shadows the same name under the working
directory's `processors/` or beside the pipeline. A reference matching no root fails
naming every path it tried, so a typo reads as a typo rather than as a missing file.

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

- **Data keys**: anything the processor puts in `data`, such as `device_name` or
  `finding_count`. Available under that name directly, and under `history`.
- **Artifacts**: a file the processor wrote, reachable by its path with the
  separators and the extension folded into the name. `decompiled/dispatch_ioctl.c`
  becomes `decompiled_dispatch_ioctl_c`. JSON is parsed into an object, and a long
  list of source, markup and plain-text suffixes arrives as text; a stage that needs
  a different set declares `text_extensions` in its own `config`, which replaces the
  list rather than adding to it. Nothing else is exposed. Text beyond the context
  budget, `max_context_tokens` times four characters, is truncated and says so, and
  a JSON file larger than that budget is skipped with a warning rather than parsed.

A value is only available to stages *after* the one recording it, so a prompt cannot
reach its own stage's output.

To see what a given pipeline offers, run:

```bash
deepzero validate <pipeline>
```

A prompt naming something no earlier stage produces is reported as an error listing
what was available instead. Rendering at run time is strict about the same thing, so a
stage that gets there anyway fails on that sample rather than sending the prompt
through. This matters because an unknown name would otherwise render as nothing: the
model would be asked to judge an empty payload, and the verdict would come back
confident and meaningless.

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
  target_label: repository list
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
disk. A run against a live application has a scope, and a run over a set of repositories
has the list or the checkout directory it was pointed at. Calling either a corpus reads
as a mistake in a report someone else is going to open.

Name what the header shows, which is the run's target, rather than what the run is about.
"Organisation" is the tempting one to get wrong: it reads well, and then it labels a
manifest path that can list repositories belonging to several organisations.

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

A finding can also name the thing it is an instance of. The report reads that name from
`finding_id`, falling back to `key` and then to `fingerprint`, and every finding carrying
the same one is grouped as a single thing seen in several places. The
report then gains a "Distinct findings" section listing each name, what it is, and how
many entities it turned up on. The section is absent from a report where no finding
carries a name.

The engine never invents one. Anything it could derive would fold in the location and so
never match across samples, which is the case the name exists for. One advisory across
forty repositories is one finding rather than forty only if the processor says so, and
the same holds for one root cause behind three thousand crashes, or one taint path
reached from two entry points.

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

Every key is read on its own, so declaring one leaves the rest at their defaults. A key
that is not one of the seven above is ignored, as is one left empty, and a `lexicon:`
written as a value rather than as a block falls back to the defaults wholesale rather
than failing the report a long run has just earned.

The wording that ends up in force is written into `report.json` next to the counts, as
`bucket_labels`, `entity`, `entity_plural` and `target_label`, so anything rendering its
own headings from that file names each outcome the way the HTML does.

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

On any result's page there are two, because a review either reached an answer or it
did not:

| Mark | Means |
|------|-------|
| **Confirmed** | checked, and it holds |
| **Refuted** | checked, and it did not hold up |

Either one opens a note for what you ran, on what, and what happened, so someone else
can repeat the attempt. The note belongs to the mark: a result with no mark on it has
nowhere to put one, so a review that settled nothing is recorded by leaving the result
alone rather than by writing down where it got to.

Anything carrying neither mark counts as **Unreviewed**, whether nobody opened it or
somebody opened it and could not settle it. Those two were once separate controls, and
side by side they read as the same thing.

Refuted is deliberately not folded into unreviewed. It is finished work with a definite
answer, and a result that did not hold up should never look like one nobody has
examined.

Marks appear against each row in the index and can be filtered on, Unreviewed included,
which gives the list of results nobody has ruled on yet. The summary counts all three,
so a run can be read as what is actually known rather than only what was alleged.

The report is a file, so marks live in the browser. **Export marks** writes them out
as `marks.json`; save that next to `index.html` and they become part of the report:
rendered for anyone who opens it, and included in `inventory.csv` as `review` and
`review_note`. Marks are keyed on the pipeline and target rather than on the file
path, so re-running over the same corpus keeps them.
