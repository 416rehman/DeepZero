<div align="center">
  <br>
  <img src=".github/banner.svg" alt="DeepZero" width="700">
  <br><br>
  <p><b>Moteur de pipeline de recherche de vulnérabilités automatisé</b></p>
  <p>Définissez des pipelines via YAML. DeepZero gère l'orchestration, le parallélisme, la tolérance aux pannes et l'état.</p>
  <p>
    <a href="https://github.com/416rehman/DeepZero/actions"><img src="https://img.shields.io/github/actions/workflow/status/416rehman/DeepZero/ci.yml?branch=main&style=flat-square" alt="CI"></a>
    <a href="https://github.com/416rehman/DeepZero/blob/main/LICENSE"><img src="https://img.shields.io/github/license/416rehman/DeepZero?style=flat-square" alt="License"></a>
    <img src="https://img.shields.io/badge/python-3.11+-blue?style=flat-square" alt="Python">
    <img src="https://img.shields.io/badge/platform-windows%20%7C%20linux-lightgrey?style=flat-square" alt="Platform">
  </p>
</div>

<br>

<div align="center">
  <img src=".github/terminal.svg" alt="Tableau de bord du terminal DeepZero" width="700">
</div>

<br>

<div align="center">
  <a href="README.md">English</a> | <a href="README.zh-CN.md">简体中文</a> | <b>Français</b>
</div>

<br>

- 🔗 **Pipeline en YAML** - enchaînez de manière déclarative les étapes d'ingestion, de filtrage, de transformation et d'évaluation LLM
- ⚡ **Exécution parallèle** - ThreadPoolExecutor avec une concurrence configurable par étape
- 💾 **Exécutions reprenables** - état atomique par échantillon sur le disque ; appuyez sur Ctrl+C et relancez pour reprendre là où vous vous étiez arrêté
- 🤖 **Intégration LLM** - modèles de prompts Jinja2 avec n'importe quel fournisseur LLM via [LiteLLM](https://github.com/BerriAI/litellm)
- 🌐 **API REST (WIP)** - interrogez l'état de l'exécution et les données d'échantillons via HTTP (actuellement expérimental et incomplet)
- 🧩 **Extensible** - écrivez des processeurs personnalisés sous forme de classes Python, et référencez-les par leur chemin dans YAML

---

## 📚 Documentation

DeepZero dispose d'une documentation exhaustive couvrant l'architecture, les schémas de pipeline, les références de la CLI et le développement de processeurs personnalisés.

👉 **[Lisez la documentation officielle ici (en anglais)](https://416rehman.github.io/DeepZero/)**

---

## ⚡️ Démarrage Rapide

DeepZero nécessite un corpus cible de fichiers à analyser et une configuration de pipeline détaillant comment les traiter.

1. **Cloner & Installer (Python 3.11+)**
   ```bash
   git clone https://github.com/416rehman/DeepZero.git
   cd DeepZero
   pip install -e .
   ```

2. **Configurer l'Environnement**
   ```bash
   cp .env.example .env
   ```

3. **Exécuter un Pipeline**
   ```bash
   deepzero run C:\drivers -p .\pipelines\loldrivers\pipeline.yaml
   ```

Pour des instructions de configuration détaillées et des exemples de corpus, consultez la [Documentation de Démarrage Rapide](https://416rehman.github.io/DeepZero/overview/quickstart.html).

---

## 📁 Structure du Dépôt

```text
src/deepzero/
├── api/                 # API REST (starlette)
├── engine/              # orchestration, persistance de l'état, exécution du pipeline
└── stages/              # processeurs intégrés (map, reduce, ingest)

processors/              # processeurs externes (fournis comme exemples)
├── ghidra_decompile/    # décompilateur headless ghidra (MapProcessor)
├── loldrivers_filter/   # filtre d'exclusion de hachage loldrivers.io (MapProcessor)
├── pe_ingest/           # parseur d'en-tête PE et extracteur de métadonnées (IngestProcessor)
└── semgrep_scanner/     # scanneur de lots semgrep (BulkMapProcessor)

pipelines/
└── loldrivers/          # pipeline de recherche de vulnérabilités pour les pilotes noyau BYOVD
    ├── pipeline.yaml
    ├── assessment.j2    # modèle de prompt LLM
    └── rules/           # règles semgrep

docs/                    # Documentation GitHub Pages basée sur Jekyll
tests/                   # suite de tests pytest
```

---

## 🤝 Contribuer

L'intégration continue (CI) s'exécute sur Python 3.11 et 3.12 via GitHub Actions.

Exécutez les vérifications de linting et de sécurité avant de soumettre :

```bash
ruff check . && ruff format --check . && bandit -ll -ii -c pyproject.toml -r .
```

Veuillez consulter le [Guide de Contribution](CONTRIBUTING.md) et le [Code de Conduite](CODE_OF_CONDUCT.md) avant de soumettre une pull request.

---

## 📄 Licence

DeepZero est publié sous la [Licence MIT](LICENSE).
