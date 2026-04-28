---
layout: default
title: Démarrage Rapide
order: 1
---

## Démarrage Rapide

DeepZero nécessite un corpus cible de fichiers à analyser et une [configuration de pipeline]({{ '/fr/reference/pipeline-yaml.html' | relative_url }}) détaillant la manière de les traiter. Nous fournissons un [pipeline complet d'exemple]({{ '/fr/reference/included-pipeline.html' | relative_url }}) conçu pour rechercher de nouveaux candidats BYOVD (Bring Your Own Vulnerable Driver) dans des ensembles de données binaires bruts (par exemple, le corpus Snappy Driver Installer) en filtrant explicitement les hachages connus à l'aide du [projet LOLDrivers](https://www.loldrivers.io/).

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

### 3. Exécution du Pipeline

Exécutez le pipeline LOLDrivers inclus sur un chemin cible :

```bash
deepzero run C:\drivers -p .\pipelines\loldrivers\pipeline.yaml
```

<div class="callout">
    <p><strong>Remarque :</strong> DeepZero <a href="{{ '/fr/overview/architecture.html' | relative_url }}">parallélise l'exécution</a> en toute sécurité et met en cache les sorties intermédiaires. Pour arrêter l'exécution proprement, envoyez le signal SIGINT (<code>Ctrl+C</code>). Les exécutions ultérieures avec des paramètres identiques reprendront instantanément à partir de l'<a href="{{ '/fr/system/state-persistence.html' | relative_url }}">état persistant sur le disque</a>.</p>
</div>
