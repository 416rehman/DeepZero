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
  <img src=".github/assets/report-source-audit.png" alt="DeepZero HTML report" width="700">
  <br>
  <sub>Every run writes a browsable report and keeps it current while the run is going. Illustrative data.</sub>
</div>

<br>

<div align="center">
  <b>English</b> | <a href="README.zh-CN.md">简体中文</a> | <a href="README.fr.md">Français</a>
</div>

<br>

- 🔗 **Pipeline-as-YAML** - chain ingest, filter, transform, and LLM-assess stages declaratively
- ⚡ **Parallel execution** - ThreadPoolExecutor with configurable concurrency per stage
- 💾 **Resumable runs** - atomic per-sample state on disk, scoped per corpus; Ctrl+C and re-run to pick up where you left off
- 🤖 **LLM integration** - Jinja2 prompt templates, with either an API key via [LiteLLM](https://github.com/BerriAI/litellm) or your Claude Code subscription and no API key at all
- 📊 **Browsable reports** - `deepzero report` builds a self-contained HTML report from run state; each pipeline names its own entities and verdicts
- 🌐 **REST API (WIP)** - query run state and sample data over HTTP (currently experimental and incomplete)
- 🧩 **Extensible** - write custom processors as Python classes, reference them by path in YAML

---

## 📚 Documentation

DeepZero features extensive, exhaustive documentation covering architecture, pipeline schemas, CLI references, and custom processor development. 

👉 **[Read the Official Documentation here](https://blog.ahmadz.ai/DeepZero/)**

---

## ⚡️ Quickstart

DeepZero requires a target corpus to analyze and a pipeline configuration detailing how to process it.

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
   Both bundled pipelines declare `model: claude-code/claude-opus-5`, which drives the Claude Code CLI you are already signed in to. Use `-m` for any LiteLLM model instead.

3. **Run a Pipeline**
   ```bash
   # kernel drivers on disk
   deepzero run C:\drivers -p .\pipelines\loldrivers\pipeline.yaml --preflight

   # or source code, from a manifest of repositories or a directory of checkouts
   deepzero run repos.txt -p .\pipelines\source_audit\pipeline.yaml
   ```
   `--preflight` confirms the LLM backend is ready before the expensive stages run, rather than finding out hours later at the first assessment stage.

4. **Read the Results**
   ```bash
   deepzero report -p loldrivers --open
   ```
   Safe to run mid-run. The report is built from run state, so it can be deleted and rebuilt at any time.

For detailed setup instructions and example corpora, see the [Quickstart Documentation](https://blog.ahmadz.ai/DeepZero/en/overview/quickstart.html).

---

## 📁 Repository Structure

```
src/deepzero/
├── api/                 # REST API (starlette)
├── engine/              # orchestration, state persistence, pipeline execution
└── stages/              # built-in processors (map, reduce, ingest)

processors/              # external processors (shipped as examples)
├── ghidra_decompile/    # ghidra headless decompiler (MapProcessor)
├── git_ingest/          # git repository discovery and cloning (IngestProcessor)
├── loldrivers_filter/   # loldrivers.io hash exclusion filter (MapProcessor)
├── pe_ingest/           # PE header parser and driver metadata extractor (IngestProcessor)
└── semgrep_scanner/     # semgrep batch scanner (BulkMapProcessor)

pipelines/
├── loldrivers/          # BYOVD kernel driver vulnerability research pipeline
│   ├── pipeline.yaml
│   ├── assessment.j2    # LLM prompt template
│   └── rules/           # semgrep rules
└── source_audit/        # source code audit over git repositories
    ├── pipeline.yaml
    ├── assessment.j2    # LLM prompt template
    └── rules/           # 136 semgrep rules across eight languages

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
