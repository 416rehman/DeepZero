---
layout: default
title: Processeurs Intégrés
order: 1
---

## Processeurs Intégrés

Référencés par leur nom simple. Exécutez `deepzero list-processors` pour les afficher avec leurs classes d'implémentation.

| Identifiant | Type | Fonctionnalité |
| ----------- | ---- | -------------- |
| `file_discovery` | Ingest | Parcours récursif du système de fichiers et hachage cryptographique. |
| `metadata_filter` | Map | Égalité de champs via `require:`, seuils numériques via n'importe quelle clé `min_<champ>` / `max_<champ>`, et déduplication via `dedup_field`. Les champs sont lus dans les données fusionnées de toutes les étapes en amont. |
| `hash_exclude` | Map | Exclusions cryptographiques via des listes intégrées ou des fichiers plats. |
| `generic_llm` | Map | Rendu de modèles Jinja2, appel de LLM, et analyse des réponses. |
| `generic_command` | Map | Exécution arbitraire de commandes shell avec substitution de variables contextuelles. |
| `top_k` | Reduce | Tronque l'ensemble des échantillons en fonction de valeurs scalaires numériques. |
| `sort` | Reduce | Réorganisation déterministe des échantillons sans réduction de l'ensemble de données. |

Un seuil `min_<champ>` lit comme valant zéro un champ qu'aucune étape en amont n'a enregistré, et filtre l'échantillon. C'est la bonne réponse pour un champ réellement absent, et la mauvaise pour un champ qui a été renommé. Une étape qui se met soudain à filtrer un corpus entier en quelques secondes mérite donc d'être confrontée aux noms que son amont fournit réellement.

## Processeurs Externes Fournis

Ceux-ci résident dans `processors/` et sont référencés par leur chemin : ils sont donc lus comme des processeurs externes ordinaires, et non comme des composants intégrés privilégiés. Ce sont ceux qu'utilisent les [pipelines inclus]({{ '/fr/reference/included-pipeline.html' | relative_url }}), et chacun est accompagné d'un README, à côté de ses sources, décrivant sa configuration complète.

| Chemin | Type | Fonctionnalité |
| ------ | ---- | -------------- |
| `pe_ingest/pe_ingest.py` | Ingest | Découvre les fichiers PE, analyse leurs en-têtes et extrait les métadonnées des pilotes. |
| `git_ingest/git_ingest.py` | Ingest | Transforme des dépôts git en échantillons, à partir d'un répertoire de copies de travail ou d'un manifeste d'URL. |
| `loldrivers_filter/loldrivers_filter.py` | Map | Exclut les échantillons dont le SHA-256 correspond à une entrée connue de la base loldrivers.io. |
| `ghidra_decompile/ghidra_decompile.py` | Map | Décompilation Ghidra headless avec un post-script configurable. |
| `semgrep_scanner/semgrep_scanner.py` | BulkMap | Analyse semgrep par lots sur les échantillons actifs. |

### `git_ingest`

Un échantillon correspond à un dépôt, et son `source_path` est la racine de la copie de travail, ce qui est exactement ce vers quoi un scanneur de code source veut être pointé. La cible de la CLI est toujours un chemin réel : les deux formes d'entrée préservent donc la reprise et le cloisonnement par corpus. Un répertoire est lu comme un conteneur de copies de travail et rien n'est récupéré sur le réseau, tandis qu'un fichier est lu comme un manifeste dont chaque entrée est clonée.

Le `sample_id` est dérivé de l'identité du dépôt plutôt que d'un chemin : un même dépôt atteint via un manifeste ou via un répertoire constitue donc le même échantillon, et une nouvelle exécution conserve ses résultats.

### `semgrep_scanner`

Deux valeurs de configuration déterminent ce qui est analysé, et ce sont elles qui permettent à un seul scanneur de servir les deux pipelines fournis :

| Champ | Défaut | Signification |
|-------|---------|---------------|
| `target_dir` | `decompiled` | Sous-répertoire du répertoire de travail propre à l'échantillon à analyser. Réglez-le sur `""` et c'est le chemin de l'échantillon lui-même qui est analysé. |
| `extensions` | `.c`, `.h`, `.cpp`, `.py` | Quels fichiers sont transmis à semgrep. |

La valeur par défaut convient à un pipeline qui décompile d'abord et écrit du C à côté de chaque échantillon. Un pipeline dont les échantillons sont déjà du code source, une copie de travail d'un dépôt par exemple, règle `target_dir: ""` et élargit `extensions` à tout ce qu'il a réellement ingéré.

`extensions` et les règles doivent s'accorder. Un fichier dont l'extension n'est pas listée n'est jamais transmis à semgrep, quel que soit le nombre de règles qui l'auraient couvert, et cet échec est silencieux : l'analyse rapporte zéro détection, ce qui est indiscernable d'un arbre sain. C'est pourquoi le pipeline d'audit de code source enregistre `files_scanned` à côté de `finding_count`.

Les échantillons sont analysés par lots (`batch_size`, `200` par défaut) plutôt qu'en une seule passe : un lot qui dépasse son délai ou revient illisible ne coûte donc que ses propres échantillons, au lieu de faire perdre tout un corpus alors que le travail a déjà été effectué.
