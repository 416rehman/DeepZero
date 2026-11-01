<div align="center">
  <br>
  <img src=".github/banner.svg" alt="DeepZero" width="700">
  <br><br>
  <p><b>Moteur de pipeline de recherche de vulnérabilités automatisé</b></p>
  <p>Définissez des pipelines via YAML. DeepZero gère l'orchestration, le parallélisme, la tolérance aux pannes et l'état.</p>
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
  <sub>Un seul moteur, deux disciplines. Le rapport tient son vocabulaire du pipeline : le même code affiche <b>6 dépôts</b> / <b>non exploitable</b> à gauche et <b>6 pilotes</b> / <b>sain</b> à droite. Données fournies à titre indicatif.</sub>
</div>

<br>

<div align="center">
  <a href="README.md">English</a> | <a href="README.zh-CN.md">简体中文</a> | <b>Français</b>
</div>

<br>

- 🔗 **Pipeline en YAML** - enchaînez de manière déclarative les étapes d'ingestion, de filtrage, de transformation et d'évaluation LLM
- 🧭 **Indépendant du domaine** - le moteur ne connaît ni les binaires, ni les dépôts, ni les points d'accès web ; c'est le pipeline qui apporte le domaine, et les pipelines fournis sont des exemples, non la finalité
- ⚡ **Exécution parallèle** - ThreadPoolExecutor avec une concurrence configurable par étape
- 💾 **Exécutions reprenables** - état atomique par échantillon sur le disque, cloisonné par corpus ; appuyez sur Ctrl+C et relancez pour reprendre là où vous vous étiez arrêté
- 🔁 **Sait ce qui a vieilli** - chaque étape prend l'empreinte de ses propres entrées : modifier un prompt, un jeu de règles ou une configuration relance exactement les étapes qui les lisaient, et aucune de celles d'avant
- 🤖 **Intégration LLM** - modèles de prompts Jinja2, avec au choix une clé d'API via [LiteLLM](https://github.com/BerriAI/litellm) ou votre abonnement Claude Code et aucune clé d'API du tout
- 📊 **Rapports consultables** - `deepzero report` construit un rapport HTML autonome à partir de l'état de l'exécution ; chaque pipeline nomme lui-même ses entités et ses verdicts
- 🌐 **API REST (WIP)** - interrogez l'état de l'exécution et les données d'échantillons via HTTP (actuellement expérimental et incomplet)
- 🧩 **Extensible** - écrivez des processeurs personnalisés sous forme de classes Python, et référencez-les par leur chemin dans YAML

---

## 📚 Documentation

DeepZero dispose d'une documentation exhaustive couvrant l'architecture, les schémas de pipeline, les références de la CLI et le développement de processeurs personnalisés.

👉 **[Lisez la documentation officielle ici](https://blog.ahmadz.ai/DeepZero/fr/)**

---

## ⚡️ Démarrage Rapide

DeepZero nécessite un corpus cible à analyser et une configuration de pipeline détaillant comment le traiter.

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

   Dans PowerShell : `Copy-Item .env.example .env`. Définissez `DEEPZERO_MODEL` dans `.env` pour les deux pipelines de sécurité, ou passez `-m` pour une exécution. Par exemple, `DEEPZERO_MODEL=openai/gpt-4o` nécessite votre `OPENAI_API_KEY`.
   Les deux pipelines de sécurité utilisent `claude-code` par défaut, donc le modèle choisi dans votre propre CLI Claude Code. Installez cette CLI et connectez-vous avant de lancer une analyse. Utilisez `DEEPZERO_MODEL` ou `-m` pour un modèle LiteLLM avec votre clé API.

3. **Exécuter un Pipeline**
   ```bash
   # des pilotes noyau sur le disque
   deepzero run ./drivers -p pipelines/loldrivers/pipeline.yaml --preflight

   # ou du code source, depuis un manifeste de dépôts ou un répertoire de copies de travail
   deepzero run repos.txt -p pipelines/source_audit/pipeline.yaml --preflight
   ```

   Remplacez `./drivers` par votre corpus de pilotes, ou créez `repos.txt` avec une URL de dépôt par ligne. Ces entrées ne sont pas fournies dans le dépôt.

   `deepzero validate pipelines/loldrivers/pipeline.yaml` / `deepzero validate pipelines/source_audit/pipeline.yaml`
   `--preflight` confirme que le backend LLM est prêt avant que les étapes coûteuses ne s'exécutent, plutôt que de l'apprendre des heures plus tard, à la première étape d'évaluation.

4. **Lire les Résultats**
   ```bash
   deepzero report -p loldrivers --open
   ```
   Peut être exécuté sans risque pendant une exécution. Le rapport est construit à partir de l'état de l'exécution : il peut donc être supprimé et reconstruit à tout moment. `deepzero runs` liste toutes les exécutions présentes sur le disque, quel que soit ce qui les a produites, et `deepzero report` sans argument devine celle que vous vouliez.

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
├── demo/                # local first run; no API keys or external tools
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
