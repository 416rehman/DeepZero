---
layout: default
title: Démarrage Rapide
order: 1
---

## Démarrage Rapide

DeepZero nécessite un corpus cible à analyser et une [configuration de pipeline]({{ '/fr/reference/pipeline-yaml.html' | relative_url }}) détaillant la manière de le traiter. Deux [pipelines de sécurité complets]({{ '/fr/reference/included-pipeline.html' | relative_url }}) sont fournis avec l'outil : l'un recherche de nouveaux candidats BYOVD (Bring Your Own Vulnerable Driver) dans des ensembles de données binaires bruts (par exemple, le corpus Snappy Driver Installer) en filtrant explicitement les hachages connus à l'aide du [projet LOLDrivers](https://www.loldrivers.io/), l'autre audite du code source réparti sur des dépôts git.

### 1. Installation

DeepZero nécessite **Python 3.11+**.

```bash
git clone https://github.com/416rehman/DeepZero.git
cd DeepZero
python -m pip install -e .
```

Cette installation de base suffit pour la démo ci-dessous. Les deux pipelines de sécurité nécessitent la configuration facultative de l'étape 3.

### 2. Essayer la démo locale

Après avoir installé le paquet de base, exécutez les exemples texte inoffensifs depuis la racine du dépôt cloné :

```sh
deepzero run pipelines/demo/samples -p pipelines/demo/pipeline.yaml
deepzero status -p pipelines/demo/pipeline.yaml
deepzero report -p pipelines/demo/pipeline.yaml --open
```

La démo ne nécessite ni clé API, ni outil externe, ni corpus de pilotes. Elle découvre deux fichiers, conserve `hello.txt`, filtre `tiny.txt` selon sa taille et produit un rapport HTML. Elle montre l'orchestration et la reprise d'état, sans recherche de vulnérabilités. Relancer la commande reprend les résultats enregistrés. Consultez le [guide de la démo](https://github.com/416rehman/DeepZero/tree/main/pipelines/demo).

### 3. Configurer les Intégrations de Sécurité

```sh
python -m pip install -e ".[full]"
```

Exécutez les commandes depuis le dépôt cloné. L'extra `full` installe notamment LIEF (analyse PE) et LiteLLM (modèles avec clé API). Pour le moteur seul : `python -m pip install -e .`.

Installez aussi les outils externes dans le même environnement :

- Les deux pipelines de sécurité : **Semgrep** dans PATH (`python -m pip install semgrep`) et un backend LLM.
- Audit de code : **Git** dans PATH.
- Pilotes : **Ghidra**, le **JDK compatible avec cette version**, et `GHIDRA_INSTALL_DIR` dans `.env` pointant vers votre installation.
- LLM par défaut : installez la CLI **Claude Code** et connectez votre propre compte. Son modèle par défaut est utilisé sans clé API. Un modèle avec clé API peut aussi être configuré ci-dessous.

Avec WSL, installez et exécutez les outils, Python et DeepZero dans cet environnement.

#### Configuration de l'Environnement

Si vous intégrez des étapes d'analyse d'IA, configurez vos clés d'API en créant un fichier `.env` :

```bash
cp .env.example .env
```

Dans PowerShell : `Copy-Item .env.example .env`. Définissez `DEEPZERO_MODEL` dans `.env` pour les deux pipelines de sécurité, ou passez `-m` pour une exécution. Par exemple, `DEEPZERO_MODEL=openai/gpt-4o` nécessite votre `OPENAI_API_KEY`.

Les deux pipelines de sécurité déclarent un modèle `claude-code`, qui pilote la CLI Claude Code à laquelle vous êtes déjà connecté et ne nécessite aucune clé d'API. N'importe quel [modèle LiteLLM]({{ '/fr/reference/pipeline-yaml.html' | relative_url }}) fonctionne à la place, via le champ `model` du pipeline ou `-m` en ligne de commande, et c'est à cela que servent les clés d'API ci-dessus.

### 4. Vérifier Avant de Vous Engager dans une Exécution

Ces exécutions sont longues. Celle-ci coûte peu, elle répond en quelques secondes plutôt qu'en quelques heures, et elle ne démarre rien :

```bash
# résout chaque processeur, vérifie ses prérequis, et vérifie chaque prompt
deepzero validate pipelines/loldrivers/pipeline.yaml
```

Elle sort avec le code 1 lorsqu'elle signale une erreur : elle fonctionne donc comme un hook de commit ou une étape d'intégration continue, et pas seulement comme quelque chose à lire.

### 5. Exécution du Pipeline

Exécutez le pipeline LOLDrivers inclus sur un chemin cible :

```bash
deepzero run ./drivers -p pipelines/loldrivers/pipeline.yaml
```

Remplacez `./drivers` par votre corpus de pilotes, ou créez `repos.txt` avec une URL de dépôt par ligne. Ces entrées ne sont pas fournies dans le dépôt.

Ou l'audit de code source, sur un manifeste de dépôts ou un répertoire de copies de travail :

```bash
deepzero run repos.txt -p pipelines/source_audit/pipeline.yaml
```

L'une comme l'autre acceptent `--preflight`, qui passe un unique appel minimal pour confirmer que le backend LLM est bien connecté. Cela s'arrête en quelques secondes si le backend n'est pas prêt, et sinon l'exécution se poursuit normalement : c'est donc un drapeau posé sur une exécution que vous vouliez lancer, et non une vérification à taper pour elle-même. L'alternative est de le découvrir plusieurs heures plus tard, à la première étape d'évaluation :

```bash
deepzero run ./drivers -p pipelines/loldrivers/pipeline.yaml --preflight
```

<div class="callout">
    <p><strong>Remarque :</strong> DeepZero <a href="{{ '/fr/overview/architecture.html' | relative_url }}">parallélise l'exécution</a> en toute sécurité et met en cache les sorties intermédiaires. Pour arrêter l'exécution proprement, envoyez le signal SIGINT (<code>Ctrl+C</code>). Les exécutions ultérieures avec des paramètres identiques reprendront instantanément à partir de l'<a href="{{ '/fr/system/state-persistence.html' | relative_url }}">état persistant sur le disque</a>.</p>
</div>

Chaque corpus dispose de son propre répertoire de travail : pointer le même pipeline vers une seconde cible démarre donc une seconde exécution, au lieu de reprendre dans les résultats de la première. Les deux restent reprenables.

### 6. Lire les Résultats

Une exécution affiche l'URL d'un rapport avant sa première étape et tient ce rapport à jour à mesure que les résultats arrivent : il peut donc être ouvert et suivi pendant que l'exécution se déroule. Pour le reconstruire à tout moment, y compris pour une exécution encore en cours :

```bash
deepzero report -p loldrivers --open
```

Ne nommer que le pipeline le résout vers son corpus le plus récent, et indique quels autres corpus ce pipeline a vus, car l'exécution la plus récente n'est pas toujours celle sur laquelle porte la question. Pour voir à la place toutes les exécutions présentes sous `work`, quels que soient le pipeline et le corpus qui les ont produites, de la plus récente à la plus ancienne :

```bash
deepzero runs
```

Cela liste pour chaque exécution son pipeline, son corpus, son statut et son nombre d'échantillons, et affiche la ligne `deepzero report -w <répertoire>` permettant d'en parcourir une. `deepzero report` sans aucun drapeau répond directement à la même question : s'il n'y a qu'une exécution, elle est retenue, et s'il y en a plusieurs, elles deviennent une liste dans laquelle choisir.

Le rapport est entièrement dérivé de l'état de l'exécution : il peut donc être supprimé puis reconstruit, et la manière dont il nomme ce qu'il a trouvé est [déclarée par le pipeline]({{ '/fr/reference/pipeline-yaml.html' | relative_url }}).
