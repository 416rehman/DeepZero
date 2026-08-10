---
layout: default
title: CLI Reference
order: 1
---

## Command Line Interface

The `deepzero` CLI is the primary interaction point for executing and managing pipelines.

```bash
# Standard execution
deepzero run ./targets -p pipelines/loldrivers/pipeline.yaml

# Check the LLM backend is signed in before committing to a long run
deepzero run ./targets -p pipelines/source_audit/pipeline.yaml --preflight

# Execute with state cleanup (fresh run)
deepzero run ./targets -p pipelines/loldrivers/pipeline.yaml --clean

# Build a browsable HTML report and open it
deepzero report -p loldrivers --open

# Check execution status
deepzero status -p loldrivers

# Launch interactive analysis REPL
deepzero interactive -w work/loldrivers

# Start the Starlette REST API
deepzero serve -w work/loldrivers --port 8420

# Scaffold a new custom pipeline
deepzero init my_custom_pipeline

# Validate schema without execution
deepzero validate loldrivers

# Inspect system registry
deepzero list-processors
```

`deepzero --version` prints the installed version, and `--help` works on the group and
on every command.

### Core Commands

| Command | Description |
| --------- | ----------- |
| `run` | Execute a pipeline against a target. Resumes automatically if state exists. |
| `report` | Build a browsable HTML report from a run's results. Safe to run while the run is going. |
| `status` | Show current pipeline run status, verdicts, and stage metrics. |
| `validate` | Perform dry-run validation of a pipeline's schema, processor imports, and prompts. |
| `list-processors` | List all built-in and dynamically registered processor types. |
| `init` | Scaffold a new pipeline directory with a boilerplate `pipeline.yaml`. |
| `interactive` | Interactive analysis REPL with LLM-backed conversation over pipeline results. |
| `serve` | Start the REST API server to expose pipeline state externally. |

### `run`

```bash
deepzero run <TARGET> -p <pipeline> [options]
```

| Flag | Default | Description |
|------|---------|-------------|
| `TARGET` | required | Positional argument. Path to the analysis corpus. Must exist; a file or a directory, whichever the pipeline's ingest stage accepts. |
| `-p, --pipeline` | required | Pipeline name, directory, or discrete YAML file path. |
| `-m, --model` | pipeline's `model` | LLM model override for this run, e.g. `openai/gpt-4o`. |
| `-w, --work-dir` | pipeline's `work_dir` setting | Replaces the root the run directory is built under. |
| `--clean` | off | Permanently delete previous run data and start fresh. |
| `--preflight` | off | Verify the LLM backend is authenticated before running. Makes one tiny call. |
| `--redo` | none | Re-run a named stage and everything after it, keeping the earlier work and deleting the output those stages recorded. Repeatable. |
| `--retry-timeouts` | off | Attempt the samples that ran out of time again, keeping every other result. |
| `--timeout-multiplier` | `2.0` | How much longer to allow when retrying a stage that ran out of time. |
| `-v, --verbose` | off | Verbose logging, including tracebacks from DeepZero's own code. |

A run with no state behind it starts from scratch; one with state resumes, and the
header says which run it is picking up. Changing `--model` between runs is allowed and
recorded: the run state is updated to name the model that will actually be called, so
`status` and the report do not describe a model no longer in use.

`--clean` renames the previous directory aside and deletes it in the background, so a
corpus with hundreds of thousands of files does not hold the command open while it is
removed.

#### Where a run's state lives

Work directories are scoped per corpus:

```text
<work_dir setting>/<pipeline name>/<corpus key>/
```

The corpus key is derived from the target path: its basename, plus a short digest of
the resolved absolute path. Two corpora through the same pipeline therefore never share
a sample store, a manifest or a report, and each resumes independently. The same path
always produces the same key, so a rerun lands back in the directory it left.

`-w, --work-dir` on `run` replaces the first segment only. The pipeline and corpus
segments are still appended, because they are what keeps two runs apart.

#### The report a run writes as it goes

A run writes its HTML report to `<work dir>/report` and prints the URL before the first
stage starts. It is rebuilt when results land rather than on a timer, and no more often
than every 15 seconds, so a fast stage cannot spend the run's time writing HTML. It is
written once more when the run stops, interrupted or finished, so what is on disk is
always the final state.

#### Checking the LLM before a long run

`--preflight` asks the backend whether it is ready and refuses to start if it is not.
This exists because the alternative is finding out several hours in, at the first
assessment stage, after the expensive stages before it have already run.

What the check does depends on the backend, because being authenticated means different
things. An agent-CLI backend such as `claude-code` sends one minimal prompt, since
whether that binary is signed in is not something DeepZero can read off disk. An
API-key backend answers from the key check already done at validation and spends
nothing.

A rate limit or a network error is not treated as an auth failure and does not block the
run. The check is opt-in rather than always on because that one prompt is real usage,
however small.

It only runs when the pipeline configures a model. A pipeline with no LLM stage has
nothing to check.

#### Retrying what ran out of time

A stage that hits its `timeout` records the sample as having run out of time rather
than as having failed. That is a statement about the budget, not about the sample:
the ones that hit it are the largest, which in most corpora are the ones worth
looking at, and filing them with genuine errors quietly biases a run away from them.

The budget bounds how long the stage waits, not how long the work takes. The processor's
thread is abandoned rather than killed, so an external process it started is still
running after the stage has moved on. See
[`timeout`]({{ '/en/reference/pipeline-yaml.html' | relative_url }}).

A resumed run does not retry them on its own, because the budget that was too short
still is. Ask for it:

```bash
deepzero run <target> -p <pipeline> --retry-timeouts
```

This forgets only the stages that ran out of time and gives them `--timeout-multiplier`
(default 2x) longer. Every other result the run produced is kept, so a retry costs the
time those stages need and nothing else. Stages that declare no timeout are untouched.
The report groups them separately and shows the budget each one exceeded.

#### Re-running one stage

Editing a prompt, a rule set or a scanner's configuration invalidates that stage's
results and nothing before it. Decompiling a corpus again to re-ask a question of it
would cost hours for no reason, so name the stage instead:

```bash
deepzero run <target> -p <pipeline> --redo assess
```

Every sample forgets that stage and every later stage, and keeps everything earlier.
Later stages go too because they consumed output that is about to change: an
assessment written from findings that no longer exist would leave one sample
describing two different runs. A sample an obsolete stage filtered out rejoins the
run, so a narrowed rule set is free to reach a different verdict about it.

The output those stages recorded goes with the state. Several processors treat their
own file on disk as a cache and adopt it instead of doing the work again, so forgetting
the state alone would have the stage re-adopt the stale file and record it as fresh,
which is worse than not redoing at all. `--redo` therefore deletes each artifact the
dropped stages had recorded, and says how many files it removed. An artifact recorded
outside the sample's own directory is left alone, because it is not this run's to
delete.

`--redo` is repeatable and starts from the earliest stage named. An unknown stage
name is rejected, with the pipeline's actual stage names listed, rather than being
treated as nothing to do. If no sample had reached any of the named stages, it says so
and changes nothing.

### `report`

```bash
deepzero report -p <pipeline> [--open]
deepzero report -w work/loldrivers/drivers-1a2b3c4d
```

| Flag | Default | Description |
|------|---------|-------------|
| `-p, --pipeline` | none | Pipeline name or path. Resolves to that pipeline's most recent corpus. |
| `-w, --work-dir` | none | A run directory, or a pipeline's root, in which case the most recent corpus is read and named. Takes precedence over `--pipeline`. |
| `-o, --out` | `<work_dir>/report` | Where to write the report. |
| `--open` | off | Open the report in a browser when it is finished. |
| `-v, --verbose` | off | Verbose logging. |

One of `--pipeline` or `--work-dir` is required.

The report is derived entirely from run state, so it holds no information the run
directory does not. Delete the report directory and run the command again and you get
it back. It is also safe to build while a run is going: it reads the state files and
writes nothing the runner depends on, so it describes the run as of the moment it was
built.

It writes:

| File | Contents |
|------|----------|
| `index.html` | Summary and a ranked list, bounded in size |
| `items/<id>.html` | One page per sample worth reading, linking to that sample's artifacts |
| `inventory.csv` | Every sample, one row, for a spreadsheet |
| `findings.jsonl` | Every finding, one JSON object per line |
| `report.json` | Summary totals for a machine, plus the vocabulary they are named in |

A sample gets a page of its own when there is something on it to read: findings, an
assessment, an error, or a stage that ran out of time. The rest are still in the CSV,
and the index says when a listing has been capped and where the remainder is.

Resolving by pipeline name picks the most recent corpus, and says so when the pipeline
has seen more than one, naming the others. The newest run is not always the one being
asked about, and silently answering about a different corpus is the failure worth
avoiding. Pass `--work-dir` to name one exactly.

What the pipeline calls its samples, its outcomes and the thing it was pointed at comes
from the pipeline's `report:` block, which lives in the pipeline definition rather than
in the run directory. `--work-dir` still gets it: the run records which pipeline wrote
it, so the block is recovered by name. A run can outlive the pipeline that made it,
though, and when that pipeline no longer loads the report falls back to the default
wording rather than refusing to build. See
[the report block]({{ '/en/reference/pipeline-yaml.html' | relative_url }}).

### `status`

```bash
deepzero status -p loldrivers
```

| Flag | Default | Description |
|------|---------|-------------|
| `-p, --pipeline` | none | Pipeline name or path. Resolves to that pipeline's most recent corpus. |
| `-w, --work-dir` | none | A run directory, or a pipeline's root, in which case the most recent corpus is read and named. Takes precedence over `--pipeline`. |
| `-v, --verbose` | off | Verbose logging. |

One of the two is required. Prints the run id, target, model, timestamps, a per-stage
table of completed, filtered, failed and out-of-time counts, and the sample verdict
totals. Out of time has a column of its own so a stage everything timed out in does not
read as a stage nothing reached, which is the opposite of what happened.

### `validate`

```bash
deepzero validate <PIPELINE_REF>
```

Loads the pipeline, resolves every processor, runs each processor's own `validate()`,
and checks every prompt against the values the stages before it actually produce. It
takes no flags. Run it before a long run: it is the cheapest place to find a missing
binary, an unreadable ruleset or a prompt naming something no stage records.

It exits 1 when it reports an error and 0 otherwise, so it can gate a commit. Warnings,
such as a pipeline that configures no model, are printed but do not fail the command:
they describe a pipeline that will start, not one that cannot.

### `list-processors`

Prints every registered processor with its type and implementing class. Takes no flags.
Only built-ins are listed; an external processor is resolved from its path at load time
and is not registered under a name.

### `init`

```bash
deepzero init <NAME>
```

Creates `pipelines/<NAME>/pipeline.yaml` under the working directory with a commented
skeleton. It refuses rather than overwriting an existing directory.

### `interactive`

```bash
deepzero interactive -w work/loldrivers/drivers-1a2b3c4d
```

| Flag | Default | Description |
|------|---------|-------------|
| `-m, --model` | `claude-code/claude-opus-5` | Model for the conversation. Any model string the backends accept. |
| `-w, --work-dir` | `work` | Run directory to load context from. |
| `-v, --verbose` | off | Verbose logging. |

A REPL that loads a run's state into the system prompt so questions can be asked about
it. `/status`, `/findings [filter]`, `/clear`, `/help` and `/quit` are handled locally;
anything else goes to the model, and an unrecognised `/word` is reported rather than
billed as a chat turn. `/findings` lists every finding the run recorded, narrowed to the
lines matching its argument, in the vocabulary the pipeline that wrote the run declared.

`-w` accepts a run directory or a pipeline's root, naming the corpus it picked when
there is more than one. The default is literally `work`, which is the root above the
pipeline directories and resolves to no run at all; the REPL says so and answers without
run context rather than pretending to have loaded one, so point `-w` at the run you mean.

### `serve` and the REST API

| Flag | Default | Description |
|------|---------|-------------|
| `--host` | `127.0.0.1` | Bind host. Anything other than loopback prints a warning, because the server is then reachable from the network. |
| `--port` | `8420` | Bind port. |
| `-w, --work-dir` | `work` | Work directory to serve. A run directory, or a pipeline's root, in which case the most recent corpus is served and named. |

Requires the extra: `pip install deepzero[serve]`, which brings in Starlette and uvicorn.

> [!WARNING]
> **WIP / Experimental Feature**
> The REST API server is currently incomplete, highly unstable, and **should not be used**. It is provided strictly for experimental local development.

Starts a read-only Starlette REST API for querying run state and sample data. It serves
exactly one run, which is why the work directory is resolved to a single corpus before
the URL is printed rather than after a request comes back empty.

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/health` | GET | Health check, and the work directory being served |
| `/api/runs` | GET | The served run as a one-element list, or an empty one |
| `/api/run` | GET | Full state for that run, or 404 |
| `/api/samples` | GET | List samples (filterable by `?verdict=`, `?classification=`, `?stage=`, `?status=`) |
| `/api/samples/{sample_id}` | GET | Full sample state with historical pipeline data |
| `/api/samples/{sample_id}/artifacts/{name}` | GET | Read a specific file artifact generated by a processor |

`verdict` is where a sample left the pipeline and `classification` is what a stage
concluded about it. Both travel in the response, so each filters the field it is named
after. `stage` matches the sample's current stage; `status` keeps a sample when any
stage in its history carries that status. A sample id containing a path separator is
rejected, because the id becomes a filesystem path and this server can be bound to
every interface.
