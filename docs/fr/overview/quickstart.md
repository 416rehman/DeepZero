---
layout: default
title: Démarrage Rapide
order: 1
---

## Démarrage Rapide

DeepZero nécessite un corpus cible à analyser et une [configuration de pipeline]({{ '/fr/reference/pipeline-yaml.html' | relative_url }}) détaillant la manière de le traiter. Deux [pipelines complets]({{ '/fr/reference/included-pipeline.html' | relative_url }}) sont fournis avec l'outil : l'un recherche de nouveaux candidats BYOVD (Bring Your Own Vulnerable Driver) dans des ensembles de données binaires bruts (par exemple, le corpus Snappy Driver Installer) en filtrant explicitement les hachages connus à l'aide du [projet LOLDrivers](https://www.loldrivers.io/), l'autre audite du code source réparti sur des dépôts git.

### 1. Installation

DeepZero nécessite **Python 3.11+**.

```bash
git clone https://github.com/416rehman/DeepZero.git
cd DeepZero
pip install -e .
```

### 2. Configuration de l'Environnement

Si vous intégrez des étapes d'analyse d'IA, configurez vos clés d'API en créant un fichier `.env` :

```bash
cp .env.example .env
```

Les deux pipelines fournis déclarent un modèle `claude-code`, qui pilote la CLI Claude Code à laquelle vous êtes déjà connecté et ne nécessite aucune clé d'API. N'importe quel [modèle LiteLLM]({{ '/fr/reference/pipeline-yaml.html' | relative_url }}) fonctionne à la place, via le champ `model` du pipeline ou `-m` en ligne de commande, et c'est à cela que servent les clés d'API ci-dessus.

### 3. Vérifier Avant de Vous Engager dans une Exécution

Ces exécutions sont longues. Les deux commandes suivantes coûtent peu, et toutes deux échouent en quelques secondes plutôt qu'en quelques heures :

```bash
# résout chaque processeur, vérifie ses prérequis, et vérifie chaque prompt
deepzero validate pipelines/loldrivers/pipeline.yaml
```

```bash
# un unique appel minimal, pour confirmer que le backend LLM est bien connecté
deepzero run C:\drivers -p .\pipelines\loldrivers\pipeline.yaml --preflight
```

### 4. Exécution du Pipeline

Exécutez le pipeline LOLDrivers inclus sur un chemin cible :

```bash
deepzero run C:\drivers -p .\pipelines\loldrivers\pipeline.yaml
```

Ou l'audit de code source, sur un manifeste de dépôts ou un répertoire de copies de travail :

```bash
deepzero run repos.txt -p .\pipelines\source_audit\pipeline.yaml
```

<div class="callout">
    <p><strong>Remarque :</strong> DeepZero <a href="{{ '/fr/overview/architecture.html' | relative_url }}">parallélise l'exécution</a> en toute sécurité et met en cache les sorties intermédiaires. Pour arrêter l'exécution proprement, envoyez le signal SIGINT (<code>Ctrl+C</code>). Les exécutions ultérieures avec des paramètres identiques reprendront instantanément à partir de l'<a href="{{ '/fr/system/state-persistence.html' | relative_url }}">état persistant sur le disque</a>.</p>
</div>

Chaque corpus dispose de son propre répertoire de travail : pointer le même pipeline vers une seconde cible démarre donc une seconde exécution, au lieu de reprendre dans les résultats de la première. Les deux restent reprenables.

### 5. Lire les Résultats

Une exécution affiche l'URL d'un rapport avant sa première étape et tient ce rapport à jour à mesure que les résultats arrivent : il peut donc être ouvert et suivi pendant que l'exécution se déroule. Pour le reconstruire à tout moment, y compris pour une exécution encore en cours :

```bash
deepzero report -p loldrivers --open
```

Le rapport est entièrement dérivé de l'état de l'exécution : il peut donc être supprimé puis reconstruit, et la manière dont il nomme ce qu'il a trouvé est [déclarée par le pipeline]({{ '/fr/reference/pipeline-yaml.html' | relative_url }}).
