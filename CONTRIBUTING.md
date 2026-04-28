# Contributing to DeepZero

Thank you for your interest in contributing to DeepZero! This document explains
how to get started, what we expect from contributions, and how the review
process works.

Please also read our [Code of Conduct](CODE_OF_CONDUCT.md) before
participating.

---

## Table of Contents

- [Getting Started](#getting-started)
- [Development Setup](#development-setup)
- [Project Structure](#project-structure)
- [Making Changes](#making-changes)
- [Code Style & Linting](#code-style--linting)
- [Testing](#testing)
- [Commit Messages](#commit-messages)
- [Pull Request Process](#pull-request-process)
- [What to Contribute](#what-to-contribute)
- [Security](#security)

---

## Getting Started

1. **Fork** the repository on GitHub.
2. **Clone** your fork locally:
   ```bash
   git clone https://github.com/<your-username>/DeepZero.git
   cd DeepZero
   ```
3. **Add the upstream remote**:
   ```bash
   git remote add upstream https://github.com/416rehman/DeepZero.git
   ```
4. **Create a feature branch** from `main`:
   ```bash
   git checkout -b my-feature main
   ```

---

## Development Setup

DeepZero requires **Python 3.11+**.

```bash
# Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate   # Linux/macOS
# .venv\Scripts\activate    # Windows

# Install in editable mode with dev dependencies
pip install -e ".[dev]"

# Install linting and security tools
pip install ruff bandit
```

The `[dev]` extra pulls in all optional dependency groups (`llm`, `serve`, `pe`)
plus `pytest` and `pytest-asyncio`.

If you plan to work on the Ghidra-related processors, you will also need:
- **Java JDK 17+**
- **Ghidra 11.x** (set `GHIDRA_INSTALL_DIR` accordingly)

---

## Project Structure

```
src/deepzero/
├── cli.py               # CLI (click + rich)
├── api/                 # REST API server (starlette)
├── engine/              # Core engine: runner, pipeline loader, state, registry
└── stages/              # Built-in processors

processors/              # Community / external processors (shipped as examples)

pipelines/               # Example pipeline definitions

tests/                   # pytest test suite (28 test files)
```

- **Built-in processors** live in `src/deepzero/stages/` and are registered in
  `src/deepzero/stages/__init__.py`.
- **Community processors** live under `processors/<name>/` and are referenced
  by path in pipeline YAML.
- **Pipelines** live under `pipelines/<name>/` with a `pipeline.yaml` and any
  supporting files (prompt templates, semgrep rules, etc.).

---

## Making Changes

### Branching Strategy

- All work should be done on a feature branch off of `main`.
- Keep branches focused on a single change. Avoid combining unrelated fixes.

### Types of Changes

| Change Type | Where |
|---|---|
| New built-in processor | `src/deepzero/stages/` + register in `__init__.py` |
| New community processor | `processors/<name>/` directory |
| New pipeline | `pipelines/<name>/` directory |
| Engine changes | `src/deepzero/engine/` |
| CLI changes | `src/deepzero/cli.py` |
| API changes | `src/deepzero/api/` |
| Tests | `tests/` |

---

## Code Style & Linting

We use [Ruff](https://docs.astral.sh/ruff/) for linting and formatting, and
[Bandit](https://bandit.readthedocs.io/) for security scanning. **CI will reject
PRs that fail these checks.**

Run all checks locally before pushing:

```bash
# Linting
ruff check .

# Format check (does not modify files)
ruff format --check .

# Auto-format (modifies files in place)
ruff format .

# Security scan
bandit -ll -ii -c pyproject.toml -r .
```

### Style Summary

- **Line length**: 100 characters (E501 is ignored, but keep it reasonable)
- **Quote style**: double quotes
- **Indent style**: spaces
- **Import sorting**: handled by Ruff (`I` rules)
- **Target version**: Python 3.11

---

## Testing

Tests live in the `tests/` directory and are run with `pytest`:

```bash
# Run the full suite
pytest

# Run a specific test file
pytest tests/test_runner.py

# Run with verbose output
pytest -v

# Run only tests matching a keyword
pytest -k "test_pipeline"
```

### Writing Tests

- Place test files in `tests/` and name them `test_<module>.py`.
- Use `tmp_path` fixtures for filesystem operations. Never write to the
  project directory.
- Mock external dependencies (LLM APIs, Ghidra, semgrep) rather than requiring
  them to be installed.
- If your change adds a new processor, add corresponding tests covering at
  least: valid config, `ok` / `filter` / `fail` result paths, and edge cases.

---

## Commit Messages

We prefer [Conventional Commits](https://www.conventionalcommits.org/) style:

```
<type>(<scope>): <short summary>

<optional body>
```

**Types**: `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `ci`, `chore`

**Examples**:
```
feat(stages): add regex_filter built-in processor
fix(runner): prevent deadlock on Ctrl+C during BulkMap stage
docs: update CLI reference with new --timeout flag
test(state): add atomicity tests for concurrent writes
```

---

## Pull Request Process

1. **Ensure CI passes.** The GitHub Actions workflow runs linting, security
   scanning, and the full test suite on Python 3.11 and 3.12.

2. **Fill out the PR template.** Describe what changed, why, and how to test
   it. Link any related issues.

3. **Keep PRs focused.** One logical change per PR. If you find an unrelated
   bug while working, open a separate issue or PR for it.

4. **Respond to review feedback.** Maintainers may request changes. Please
   address them or explain your reasoning.

5. **Clean history.** PRs may be squash-merged into `main` at the
   maintainer's discretion.

### PR Checklist

Before requesting review, verify:

- [ ] `ruff check .` passes
- [ ] `ruff format --check .` passes
- [ ] `bandit -ll -ii -c pyproject.toml -r .` passes
- [ ] `pytest` passes
- [ ] New code has corresponding tests
- [ ] Documentation is updated if behavior changed

---

## What to Contribute

We welcome contributions of all kinds. Here are some ideas:

### Good First Issues

Look for issues labeled
[`good first issue`](https://github.com/416rehman/DeepZero/labels/good%20first%20issue)
on GitHub.

### New Processors

Community processors are the easiest way to contribute. Create a directory
under `processors/`, subclass one of the four base classes
(`IngestProcessor`, `MapProcessor`, `BulkMapProcessor`, `ReduceProcessor`),
and include a README explaining what it does. See the
[Building Processors](README.md#-building-processors) section of the README.

### New Pipelines

Have a creative vulnerability research workflow? Add it under
`pipelines/<name>/` with a `pipeline.yaml`, any prompt templates or rules, and
a README describing the use case and required tooling.

### Bug Fixes & Improvements

Check the [issue tracker](https://github.com/416rehman/DeepZero/issues) for
reported bugs. Engine improvements (better error messages, performance
optimizations, new CLI features) are also highly valued.

### Documentation

README clarifications, docstring improvements, and usage examples are always
appreciated.

---

## Security

If you discover a security vulnerability, **do not open a public issue.**
Follow the process in our [Security Policy](SECURITY.md) to report it
privately.

When writing processors, follow the security best practices outlined in
SECURITY.md. Avoid `eval`/`exec`, don't hardcode credentials, and ensure
`setup()`/`teardown()` are symmetric.

---

Thank you for helping make DeepZero better! 🚀
