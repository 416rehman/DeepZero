---
layout: default
title: Quickstart
order: 1
---

## Quickstart

DeepZero requires a target corpus to analyze and a [pipeline configuration]({{ '/en/reference/pipeline-yaml.html' | relative_url }}) detailing how to process it. Two [complete pipelines]({{ '/en/reference/included-pipeline.html' | relative_url }}) ship with it: one hunting for new BYOVD (Bring Your Own Vulnerable Driver) candidates across raw binary datasets (e.g., the Snappy Driver Installer corpus) while explicitly filtering out known hashes using the [LOLDrivers project](https://www.loldrivers.io/), and one auditing source code across git repositories.

### 1. Installation

DeepZero requires **Python 3.11+**.

```bash
git clone https://github.com/416rehman/DeepZero.git
cd DeepZero
pip install -e .
```

### 2. Environment Configuration

If integrating AI analysis stages, configure API keys by creating a `.env` file:

```bash
cp .env.example .env
```

Both bundled pipelines declare a `claude-code` model, which drives the Claude Code CLI
you are already signed in to and needs no API key at all. Any [LiteLLM model]({{ '/en/reference/pipeline-yaml.html' | relative_url }}) works instead, via the pipeline's `model` field or `-m` on the command line, and that is what the API keys above are for.

### 3. Check Before You Commit to a Run

These runs are long. This one is cheap, it answers in seconds rather than hours, and it
starts nothing:

```bash
# resolves every processor, checks its prerequisites, and checks every prompt
deepzero validate pipelines/loldrivers/pipeline.yaml
```

It exits 1 when it reports an error, so it works as a commit hook or a CI step rather
than only as something to read.

### 4. Pipeline Execution

Execute the included LOLDrivers pipeline against a target path:

```bash
deepzero run C:\drivers -p .\pipelines\loldrivers\pipeline.yaml
```

Or the source audit, against a manifest of repositories or a directory of checkouts:

```bash
deepzero run repos.txt -p .\pipelines\source_audit\pipeline.yaml
```

Either of those takes `--preflight`, which makes one tiny call to confirm the LLM
backend is actually signed in. It stops in seconds if the backend is not ready, and
otherwise the run carries on normally, so it is a flag on a run you meant to start
rather than a check to type on its own. The alternative is finding out several hours
in, at the first assessment stage:

```bash
deepzero run C:\drivers -p .\pipelines\loldrivers\pipeline.yaml --preflight
```

<div class="callout">
    <p><strong>Note:</strong> DeepZero safely <a href="{{ '/en/overview/architecture.html' | relative_url }}">parallelizes execution</a> and caches intermediate outputs. To halt gracefully, send SIGINT (<code>Ctrl+C</code>). Subsequent executions with identical parameters will instantly resume from <a href="{{ '/en/system/state-persistence.html' | relative_url }}">persistent disk state</a>.</p>
</div>

Each corpus gets its own work directory, so pointing the same pipeline at a second
target starts a second run rather than resuming into the first one's results. Both
remain resumable.

### 5. Reading the Results

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
