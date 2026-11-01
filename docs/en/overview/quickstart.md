---
layout: default
title: Quickstart
order: 1
---

## Quickstart

DeepZero requires a target corpus to analyze and a [pipeline configuration]({{ '/en/reference/pipeline-yaml.html' | relative_url }}) detailing how to process it. Two [complete security pipelines]({{ '/en/reference/included-pipeline.html' | relative_url }}) ship with it: one hunting for new BYOVD (Bring Your Own Vulnerable Driver) candidates across raw binary datasets (e.g., the Snappy Driver Installer corpus) while explicitly filtering out known hashes using the [LOLDrivers project](https://www.loldrivers.io/), and one auditing source code across git repositories.

### 1. Installation

DeepZero requires **Python 3.11+**.

```bash
git clone https://github.com/416rehman/DeepZero.git
cd DeepZero
python -m pip install -e .
```

This base installation is enough for the demo below. The two security pipelines require the optional setup in step 3.

### 2. Try the local demo

After installing the base package, run the included harmless text samples from the cloned repository root:

```sh
deepzero run pipelines/demo/samples -p pipelines/demo/pipeline.yaml
deepzero status -p pipelines/demo/pipeline.yaml
deepzero report -p pipelines/demo/pipeline.yaml --open
```

The demo needs no API keys, external tools, or driver corpus. It discovers two files, keeps `hello.txt`, filters `tiny.txt` by size, and writes an HTML report. It demonstrates orchestration and saved state, not vulnerability detection. Repeating the run command resumes saved results. See the [demo walkthrough](https://github.com/416rehman/DeepZero/tree/main/pipelines/demo) for details.

### 3. Configure Security Integrations

```sh
python -m pip install -e ".[full]"
```

Run the commands below from the cloned repository. The `full` extra installs optional Python dependencies, including LIEF for PE parsing and LiteLLM for API-backed models. The engine alone can be installed with `python -m pip install -e .`.

Before running a security pipeline, install its external tools in the same environment:

- Both security pipelines: **Semgrep** on PATH (`python -m pip install semgrep`) and an LLM backend.
- Source audit: **Git** on PATH.
- Driver analysis: **Ghidra** and the **JDK supported by that Ghidra release**; set `GHIDRA_INSTALL_DIR` to your installation in `.env`.
- Default LLM: install the **Claude Code CLI** and sign in with your own account. Its default model is used; no API key is required. Alternatively, configure an API-backed model and its key below.

If using WSL, install and run the tools, Python, and DeepZero inside that environment.

#### Environment Configuration

Copy the environment template for your tool paths and optional API keys:

```bash
cp .env.example .env
```

In PowerShell, use `Copy-Item .env.example .env`. Set `DEEPZERO_MODEL` in `.env` to override the backend/model for both security pipelines, or pass `-m` for one run. For example, `DEEPZERO_MODEL=openai/gpt-4o` requires your `OPENAI_API_KEY`.

Both security pipelines default to `claude-code`, which uses the default model of your
installed, signed-in Claude Code CLI and needs no API key. Any [LiteLLM model]({{ '/en/reference/pipeline-yaml.html' | relative_url }}) works instead, via the pipeline's `model` field or `-m` on the command line, and that is what the API keys above are for.

### 4. Check Before You Commit to a Run

These runs are long. This one is cheap, it answers in seconds rather than hours, and it
starts nothing:

```bash
# resolves every processor, checks its prerequisites, and checks every prompt
deepzero validate pipelines/loldrivers/pipeline.yaml
```

It exits 1 when it reports an error, so it works as a commit hook or a CI step rather
than only as something to read.

### 5. Pipeline Execution

Execute the included LOLDrivers pipeline against a target path:

```bash
deepzero run ./drivers -p pipelines/loldrivers/pipeline.yaml
```

Replace `./drivers` with your driver corpus path, or create `repos.txt` with one repository URL per line. These example inputs are not included in the repository.

Or the source audit, against a manifest of repositories or a directory of checkouts:

```bash
deepzero run repos.txt -p pipelines/source_audit/pipeline.yaml
```

Either of those takes `--preflight`, which makes one tiny call to confirm the LLM
backend is actually signed in. It stops in seconds if the backend is not ready, and
otherwise the run carries on normally, so it is a flag on a run you meant to start
rather than a check to type on its own. The alternative is finding out several hours
in, at the first assessment stage:

```bash
deepzero run ./drivers -p pipelines/loldrivers/pipeline.yaml --preflight
```

<div class="callout">
    <p><strong>Note:</strong> DeepZero safely <a href="{{ '/en/overview/architecture.html' | relative_url }}">parallelizes execution</a> and caches intermediate outputs. To halt gracefully, send SIGINT (<code>Ctrl+C</code>). Subsequent executions with identical parameters will instantly resume from <a href="{{ '/en/system/state-persistence.html' | relative_url }}">persistent disk state</a>.</p>
</div>

Each corpus gets its own work directory, so pointing the same pipeline at a second
target starts a second run rather than resuming into the first one's results. Both
remain resumable.

### 6. Reading the Results

A run prints a report URL before its first stage and keeps that report up to date as
results land, so it can be opened and watched while the run is going. To build it again
at any time, including against a run still in progress:

```bash
deepzero report -p loldrivers --open
```

Naming only the pipeline resolves to its most recent corpus, and says which other
corpora that pipeline has seen, because the newest run is not always the one being
asked about. To see every run under `work` instead, whatever pipeline or corpus produced
it, newest first:

```bash
deepzero runs
```

That lists each run's pipeline, corpus, status and sample count, and prints the
`deepzero report -w <dir>` line for browsing one. `deepzero report` with no flags
answers the same question directly: a single run is taken, and several become a list to
pick from.

The report is derived entirely from run state, so it can be deleted and rebuilt, and
what it calls the things it found is [declared by the pipeline]({{ '/en/reference/pipeline-yaml.html' | relative_url }}).
