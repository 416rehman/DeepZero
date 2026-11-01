<div align="center">
  <br>
  <img src=".github/banner.svg" alt="DeepZero" width="700">
  <br><br>
  <p><b>Moteur de pipeline de recherche de vulnérabilités automatisé</b></p>
  <p>Définissez des pipelines en YAML, traitez les échantillons en parallèle et reprenez les exécutions interrompues.</p>
  <p>
    <a href="https://github.com/416rehman/DeepZero/actions"><img src="https://img.shields.io/github/actions/workflow/status/416rehman/DeepZero/ci.yml?branch=main&style=flat-square" alt="CI"></a>
    <a href="https://github.com/416rehman/DeepZero/blob/main/LICENSE"><img src="https://img.shields.io/github/license/416rehman/DeepZero?style=flat-square" alt="License"></a>
    <a href="https://blog.ahmadz.ai/DeepZero/fr/"><img src="https://img.shields.io/badge/docs-DeepZero-orange?style=flat-square" alt="Docs"></a>
    <img src="https://img.shields.io/badge/python-3.11+-blue?style=flat-square" alt="Python">
    <img src="https://img.shields.io/badge/platform-windows%20%7C%20linux-lightgrey?style=flat-square" alt="Platform">
  </p>
</div>

<br>

<div align="center">
  <img src=".github/terminal.svg" alt="Tableau de bord du terminal DeepZero" width="700">
</div>

<br>

<table align="center">
  <tr>
    <td width="50%"><img src=".github/assets/report-source-audit.png" alt="Rapport HTML DeepZero pour un audit de code source"></td>
    <td width="50%"><img src=".github/assets/report-loldrivers.png" alt="Rapport HTML DeepZero pour une revue de pilotes noyau"></td>
  </tr>
</table>

<div align="center">
  <sub>Exemples de rapports avec des données fictives.</sub>
</div>

<br>

<div align="center">
  <a href="README.md">English</a> | <a href="README.zh-CN.md">简体中文</a> | <b>Français</b>
</div>

<br>

- **Pipelines YAML** - combinez ingestion, filtrage, transformation et évaluation LLM.
- **Exécution parallèle** - configurez la concurrence par étape.
- **État sauvegardé** - reprenez les exécutions interrompues à partir des résultats sur disque.
- **Réexécution après modification** - une modification des prompts, règles ou paramètres relance l'étape concernée et les suivantes.
- **Modèles LLM** - utilisez des prompts Jinja2 avec [LiteLLM](https://github.com/BerriAI/litellm) ou la CLI Claude Code.
- **Rapports HTML** - générez un rapport autonome avec `deepzero report`.
- **Processeurs personnalisés** - écrivez des classes Python et référencez-les par leur chemin en YAML.
- **API REST expérimentale** - consultez l'état des exécutions et les données des échantillons via HTTP.

---

## 📚 Documentation

[Architecture, configuration des pipelines, référence CLI et processeurs personnalisés](https://blog.ahmadz.ai/DeepZero/fr/).

---

## ⚡️ Démarrage Rapide

Pour un premier essai sans clé API ni outil externe, suivez la [démo locale](https://blog.ahmadz.ai/DeepZero/fr/overview/quickstart.html) : `python -m pip install -e .` suffit. Les étapes ci-dessous configurent les deux pipelines de sécurité.

1. **Cloner & Installer (Python 3.11+)**
   ```bash
   git clone https://github.com/416rehman/DeepZero.git
   cd DeepZero
   python -m pip install -e ".[full]"
   ```

   Exécutez les commandes depuis le dépôt cloné. L'extra `full` installe notamment LIEF (analyse PE) et LiteLLM (modèles avec clé API). Pour le moteur seul : `python -m pip install -e .`.

   Installez aussi les outils externes dans le même environnement :

   - Les deux pipelines de sécurité : **Semgrep** dans PATH (`python -m pip install semgrep`) et un backend LLM.
   - Audit de code : **Git** dans PATH.
   - Pilotes : **Ghidra**, le **JDK compatible avec cette version**, et `GHIDRA_INSTALL_DIR` dans `.env` pointant vers votre installation.
   - LLM par défaut : installez la CLI **Claude Code** et connectez votre propre compte. Son modèle par défaut est utilisé sans clé API. Un modèle avec clé API peut aussi être configuré ci-dessous.

   Avec WSL, installez et exécutez les outils, Python et DeepZero dans cet environnement.

2. **Configurer l'Environnement**
   ```bash
   cp .env.example .env
   ```

   Dans PowerShell : `Copy-Item .env.example .env`. Les deux pipelines utilisent `claude-code` par défaut et le modèle de votre CLI Claude Code. Pour choisir un modèle LiteLLM, définissez `DEEPZERO_MODEL` dans `.env` ou passez `-m`. Par exemple, `DEEPZERO_MODEL=openai/gpt-4o` nécessite votre `OPENAI_API_KEY`.

3. **Exécuter un Pipeline**
   ```bash
   # des pilotes noyau sur le disque
   deepzero run ./drivers -p pipelines/loldrivers/pipeline.yaml --preflight

   # ou du code source, depuis un manifeste de dépôts ou un répertoire de copies de travail
   deepzero run repos.txt -p pipelines/source_audit/pipeline.yaml --preflight
   ```

   Remplacez `./drivers` par votre corpus de pilotes, ou créez `repos.txt` avec une URL de dépôt par ligne. Ces entrées ne sont pas fournies dans le dépôt.

   `deepzero validate pipelines/loldrivers/pipeline.yaml` / `deepzero validate pipelines/source_audit/pipeline.yaml`
   `--preflight` vérifie le backend LLM avant le début du traitement.

4. **Lire les Résultats**
   ```bash
   deepzero report -p loldrivers --open
   ```
   Les rapports peuvent être générés pendant ou après une exécution. `deepzero runs` liste les exécutions sous `work/`, ou dans le répertoire indiqué par `--work-dir`. Sans argument, `deepzero report` utilise l'unique exécution sous `work/` ou vous demande de choisir s'il y en a plusieurs. Dans un script, utilisez `--work-dir` pour sélectionner une exécution.

Pour des instructions de configuration détaillées et des exemples de corpus, consultez la [Documentation de Démarrage Rapide](https://blog.ahmadz.ai/DeepZero/fr/overview/quickstart.html).

---

## 📁 Structure du Dépôt

```text
src/deepzero/
├── cli.py               # groupe de commandes click (run, report, runs, status, validate, ...)
├── api/                 # API REST (starlette)
├── engine/              # orchestration, persistance de l'état, exécution du pipeline
└── stages/              # processeurs intégrés (map, reduce, ingest)

processors/              # processeurs externes (fournis comme exemples)
├── ghidra_decompile/    # décompilateur headless ghidra (MapProcessor)
├── git_ingest/          # découverte et clonage de dépôts git (IngestProcessor)
├── loldrivers_filter/   # filtre d'exclusion de hachage loldrivers.io (MapProcessor)
├── pe_ingest/           # parseur d'en-tête PE et extracteur de métadonnées (IngestProcessor)
└── semgrep_scanner/     # scanneur de lots semgrep (BulkMapProcessor)

pipelines/
├── demo/                # démo locale, sans clé API ni outil externe
├── loldrivers/          # pipeline de recherche de vulnérabilités pour les pilotes noyau BYOVD
│   ├── pipeline.yaml
│   ├── assessment.j2    # modèle de prompt LLM
│   └── rules/           # règles semgrep
└── source_audit/        # audit de code source sur des dépôts git
    ├── pipeline.yaml
    ├── assessment.j2    # modèle de prompt LLM
    └── rules/           # 136 règles semgrep couvrant huit langages

docs/                    # Documentation GitHub Pages basée sur Jekyll
tests/                   # suite de tests pytest
```

---

## 🤝 Contribuer

L'intégration continue (CI) exécute la suite de tests sur chaque interpréteur pris en charge via GitHub Actions.

Exécutez les vérifications de linting et de sécurité avant de soumettre :

```bash
ruff check . && ruff format --check . && bandit -ll -ii -c pyproject.toml -r .
```

Veuillez consulter le [Guide de Contribution](CONTRIBUTING.md) et le [Code de Conduite](CODE_OF_CONDUCT.md) avant de soumettre une pull request.

---

## 📄 Licence

DeepZero est publié sous la [Licence MIT](LICENSE).
