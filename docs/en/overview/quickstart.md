---
layout: default
title: Quickstart
order: 1
---

## Quickstart

DeepZero requires a target corpus of files to analyze and a [pipeline configuration]({{ '/reference/pipeline-yaml.html' | relative_url }}) detailing how to process them. We provide a [complete example pipeline]({{ '/reference/included-pipeline.html' | relative_url }}) designed to hunt for new BYOVD (Bring Your Own Vulnerable Driver) candidates across raw binary datasets (e.g., the Snappy Driver Installer corpus) by explicitly filtering out known hashes using the [LOLDrivers project](https://www.loldrivers.io/).

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

### 3. Pipeline Execution

Execute the included LOLDrivers pipeline against a target path:

```bash
deepzero run C:\drivers -p .\pipelines\loldrivers\pipeline.yaml
```

<div class="callout">
    <p><strong>Note:</strong> DeepZero safely <a href="{{ '/en/overview/architecture.html' | relative_url }}">parallelizes execution</a> and caches intermediate outputs. To halt gracefully, send SIGINT (<code>Ctrl+C</code>). Subsequent executions with identical parameters will instantly resume from <a href="{{ '/system/state-persistence.html' | relative_url }}">persistent disk state</a>.</p>
</div>
