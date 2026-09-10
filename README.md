<div align="center">
  <br>
  <img src=".github/banner.svg" alt="DeepZero" width="700">
  <br><br>
  <p><b>Automated vulnerability research pipeline engine</b></p>
  <p>Define pipelines as YAML. DeepZero handles orchestration, parallelism, fault tolerance, and state.</p>
  <p>
    <a href="https://github.com/416rehman/DeepZero/actions"><img src="https://img.shields.io/github/actions/workflow/status/416rehman/DeepZero/ci.yml?branch=main&style=flat-square" alt="CI"></a>
    <a href="https://github.com/416rehman/DeepZero/blob/main/LICENSE"><img src="https://img.shields.io/github/license/416rehman/DeepZero?style=flat-square" alt="License"></a>
    <a href="https://blog.ahmadz.ai/DeepZero/"><img src="https://img.shields.io/badge/docs-DeepZero-orange?style=flat-square" alt="Docs"></a>
    <img src="https://img.shields.io/badge/python-3.11+-blue?style=flat-square" alt="Python">
    <img src="https://img.shields.io/badge/platform-windows%20%7C%20linux-lightgrey?style=flat-square" alt="Platform">
  </p>
</div>

<br>

<div align="center">
  <img src=".github/terminal.svg" alt="DeepZero terminal dashboard" width="700">
</div>

<br>

<div align="center">
  <b>English</b> | <a href="README.zh-CN.md">简体中文</a> | <a href="README.fr.md">Français</a>
</div>

<br>

- 🔗 **Pipeline-as-YAML** - chain ingest, filter, transform, and LLM-assess stages declaratively
- ⚡ **Parallel execution** - ThreadPoolExecutor with configurable concurrency per stage
- 💾 **Resumable runs** - atomic per-sample state on disk; Ctrl+C and re-run to pick up where you left off
- 🤖 **LLM integration** - Jinja2 prompt templates with any LLM provider via [LiteLLM](https://github.com/BerriAI/litellm)
- 🌐 **REST API (WIP)** - query run state and sample data over HTTP (currently experimental and incomplete)
- 🧩 **Extensible** - write custom processors as Python classes, reference them by path in YAML

---

## 📚 Documentation

The documentation covers architecture, pipeline schemas, CLI references, and custom processor development.

👉 **[Read the Official Documentation here](https://blog.ahmadz.ai/DeepZero/)**

---

## ⚡️ Quickstart

Try a complete local run with the included text samples. **No API keys, Ghidra, or driver corpus needed.** Requires Python 3.11+.

```sh
git clone https://github.com/416rehman/DeepZero.git
cd DeepZero
python -m pip install -e .
deepzero run pipelines/demo/samples -p pipelines/demo/pipeline.yaml
deepzero report -p pipelines/demo/pipeline.yaml --open
```

These commands work in PowerShell and POSIX shells. For an isolated installation, create and activate a Python virtual environment before installing.

The demo discovers two harmless text files, keeps one, filters the smaller one, and generates a browsable HTML report. Run the same pipeline command again to resume from saved state. This demonstrates the engine; it does not run vulnerability analysis. See the [demo walkthrough](pipelines/demo/README.md) for expected results and configuration experiments.

For the driver analysis pipeline, follow the [full setup guide](https://blog.ahmadz.ai/DeepZero/en/overview/quickstart.html) and [pipeline prerequisites](https://blog.ahmadz.ai/DeepZero/en/reference/included-pipeline.html). Optional integrations require their own dependencies and configuration.

If DeepZero is useful to your work, **star this repository** to help others discover it. Feedback on your first run is welcome in the [issue tracker](https://github.com/416rehman/DeepZero/issues).

---

## 📁 Repository Structure

```
src/deepzero/
├── api/                 # REST API (starlette)
├── engine/              # orchestration, state persistence, pipeline execution
└── stages/              # built-in processors (map, reduce, ingest)

processors/              # external processors (shipped as examples)
├── ghidra_decompile/    # ghidra headless decompiler (MapProcessor)
├── loldrivers_filter/   # loldrivers.io hash exclusion filter (MapProcessor)
├── pe_ingest/           # PE header parser and driver metadata extractor (IngestProcessor)
└── semgrep_scanner/     # semgrep batch scanner (BulkMapProcessor)

pipelines/
├── demo/                # local first run with harmless text files; no API keys
└── loldrivers/          # BYOVD kernel driver vulnerability research pipeline
    ├── pipeline.yaml
    ├── assessment.j2    # LLM prompt template
    └── rules/           # semgrep rules

docs/                    # Jekyll-based GitHub Pages documentation
tests/                   # pytest suite
```

---

## 🤝 Contributing

CI runs on Python 3.11, 3.12, 3.13, and 3.14 via GitHub Actions.

Run linting and security checks before submitting:

```bash
ruff check . && ruff format --check . && bandit -ll -ii -c pyproject.toml -r .
```

Please refer to the [Contributing Guide](CONTRIBUTING.md) and the [Code of Conduct](CODE_OF_CONDUCT.md) before submitting pull requests.

---

## 📄 License

DeepZero is released under the [MIT License](LICENSE).
