<div align="center">
  <br>
  <img src=".github/banner.svg" alt="DeepZero" width="700">
  <br><br>
  <p><b>Automated vulnerability research pipeline engine</b></p>
  <p>Define pipelines as YAML. DeepZero handles orchestration, parallelism, fault tolerance, and state.</p>
  <p>
    <a href="https://github.com/416rehman/DeepZero/actions"><img src="https://img.shields.io/github/actions/workflow/status/416rehman/DeepZero/ci.yml?branch=main&style=flat-square" alt="CI"></a>
    <a href="https://github.com/416rehman/DeepZero/blob/main/LICENSE"><img src="https://img.shields.io/github/license/416rehman/DeepZero?style=flat-square" alt="License"></a>
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

DeepZero features extensive, exhaustive documentation covering architecture, pipeline schemas, CLI references, and custom processor development. 

👉 **[Read the Official Documentation here](https://416rehman.github.io/DeepZero/)**

---

## ⚡️ Quickstart

DeepZero requires a target corpus of files to analyze and a pipeline configuration detailing how to process them. 

1. **Clone & Install (Python 3.11+)**
   ```bash
   git clone https://github.com/416rehman/DeepZero.git
   cd DeepZero
   pip install -e .
   ```

2. **Configure Environment**
   ```bash
   cp .env.example .env
   ```

3. **Run a Pipeline**
   ```bash
   deepzero run C:\drivers -p .\pipelines\loldrivers\pipeline.yaml
   ```

For detailed setup instructions and example corpora, see the [Quickstart Documentation](https://416rehman.github.io/DeepZero/overview/quickstart.html).

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
└── loldrivers/          # BYOVD kernel driver vulnerability research pipeline
    ├── pipeline.yaml
    ├── assessment.j2    # LLM prompt template
    └── rules/           # semgrep rules

docs/                    # Jekyll-based GitHub Pages documentation
tests/                   # pytest suite
```

---

## 🤝 Contributing

CI runs on Python 3.11 and 3.12 via GitHub Actions.

Run linting and security checks before submitting:

```bash
ruff check . && ruff format --check . && bandit -ll -ii -c pyproject.toml -r .
```

Please refer to the [Contributing Guide](CONTRIBUTING.md) and the [Code of Conduct](CODE_OF_CONDUCT.md) before submitting pull requests.

---

## 📄 License

DeepZero is released under the [MIT License](LICENSE).
