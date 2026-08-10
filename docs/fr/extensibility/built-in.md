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
| `hash_exclude` | Map | Exclusions cryptographiques via des listes intégrées ou des fichiers plats, déduplication au sein d'une exécution via `dedup`, et champ dans lequel le hachage est lu via `hash_field` (`sha256` sauf indication contraire). |
| `generic_llm` | Map | Rendu de modèles Jinja2, appel de LLM, et analyse des réponses. |
| `generic_command` | Map | Exécution arbitraire de commandes shell avec substitution de variables contextuelles. |
| `top_k` | Reduce | Tronque l'ensemble des échantillons en fonction de valeurs scalaires numériques. |
| `sort` | Reduce | Réorganisation déterministe des échantillons sans réduction de l'ensemble de données. |

Un seuil `min_<champ>` lit comme valant zéro un champ qu'aucune étape en amont n'a enregistré, et filtre l'échantillon. C'est la bonne réponse pour un champ réellement absent, et la mauvaise pour un champ qui a été renommé. Une étape qui se met soudain à filtrer un corpus entier en quelques secondes mérite donc d'être confrontée aux noms que son amont fournit réellement.

## Processeurs Externes Fournis

Ceux-ci résident dans `processors/` et sont référencés par leur chemin : ils sont donc lus comme des processeurs externes ordinaires, et non comme des composants intégrés privilégiés. Ce sont ceux qu'utilisent les [pipelines inclus]({{ '/fr/reference/included-pipeline.html' | relative_url }}). `ghidra_decompile`, `git_ingest` et `loldrivers_filter` déclarent les clés qu'ils acceptent sous forme de dataclass `Config` : la source en est donc la liste, et une clé mal orthographiée dans un pipeline est signalée plutôt qu'ignorée. `pe_ingest` et `semgrep_scanner` lisent le dictionnaire de configuration brut, où une clé mal orthographiée n'est ni lue ni signalée. Chacun est accompagné d'un README à côté de ses sources, décrivant ce qu'il produit et les comportements qui surprendraient un lecteur.

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

| Champ | Défaut | Signification |
|-------|---------|---------------|
| `rules_dir` | aucun, requis | Répertoire de règles semgrep à charger. |
| `target_dir` | `decompiled` | Sous-répertoire du répertoire de travail propre à l'échantillon à analyser. Réglez-le sur `""` et c'est le chemin de l'échantillon lui-même qui est analysé. |
| `extensions` | `.c`, `.h`, `.cpp`, `.py` | Quels fichiers sont transmis à semgrep. Un point initial est ajouté s'il manque, et une chaîne seule est acceptée pour une liste à une entrée. |
| `batch_size` | `200` | Échantillons par invocation de semgrep. `0` ou moins place toute l'étape dans une seule passe. |
| `timeout` | `300` | Secondes accordées au processus semgrep d'un lot. |
| `min_findings` | `0` | Filtre un échantillon comptant moins de détections que cela. `0` ne filtre rien. |

`target_dir` et `extensions` sont ce qui permet à un seul scanneur de servir les deux pipelines fournis. Les valeurs par défaut conviennent à un pipeline qui décompile d'abord et écrit du C à côté de chaque échantillon. Un pipeline dont les échantillons sont déjà du code source, une copie de travail d'un dépôt par exemple, règle `target_dir: ""` et élargit `extensions` à tout ce qu'il a réellement ingéré.

`rules_dir` est résolu d'abord par rapport au répertoire de travail, puis par rapport au répertoire du pipeline, et `validate()` comme l'analyse elle-même le résolvent de la même manière, parce que les résoudre différemment a un jour laissé la validation passer pendant que l'analyse s'exécutait sans aucune règle chargée. Un `rules_dir` qui n'existe pas au moment où l'étape s'exécute fait échouer tous ses échantillons, plutôt que d'analyser sans rien de chargé et de rapporter un corpus sain.

#### Un findings.json déjà sur le disque est adopté, non réanalysé

C'est le comportement surprenant. Avant toute analyse, le processeur cherche un `findings.json` dans le répertoire propre à chaque échantillon. S'il est là, que le moteur rapporte le résultat mis en cache comme toujours valide, et que le fichier s'analyse, ces détections sont retenues comme résultat, l'échantillon est enregistré avec `findings_cached: true`, et semgrep n'est jamais interrogé à son sujet. La validité n'appartient pas au processeur : le moteur compare l'empreinte actuelle de cette étape avec celle sous laquelle le résultat précédent a été enregistré, il est donc le seul à savoir si le fichier décrit encore les règles et la configuration en vigueur. Si le fichier est illisible, l'échantillon est réanalysé.

C'est ce qui empêche une exécution interrompue de refaire les lots qu'elle avait déjà terminés. Modifier les règles invalide le cache de soi-même : `rules_dir` est une valeur de configuration désignant un répertoire, les fichiers de règles eux-mêmes sont donc intégrés à l'empreinte, et un résultat enregistré sous une empreinte différente est périmé plutôt qu'adopté. `deepzero run --redo <étape>` reste le moyen de forcer une réanalyse pour ce que l'empreinte ne peut pas voir, et cela fonctionne parce que `findings.json` est enregistré comme artefact sur chaque chemin de code qui en écrit un, y compris le chemin filtré : `--redo` peut donc trouver le fichier et le supprimer. Un résultat enregistré avant l'existence des empreintes porte une empreinte vide, et ceux-là sont retenus tels quels : jeter un corpus au motif qu'il précède cette fonctionnalité serait la pire supposition.

Un résultat adopté ne porte que `finding_count` et `findings_cached`. `files_submitted` et `files_scanned` proviennent de l'exécution de semgrep elle-même : un échantillon qui n'a pas été analysé cette fois-ci ne porte donc ni l'un ni l'autre.

#### Le traitement par lots, et les échecs qu'il vaut la peine de connaître

Les échantillons sont analysés par lots plutôt qu'en une seule passe : un lot qui dépasse son délai ou revient illisible ne coûte donc que ses propres échantillons, au lieu de faire perdre tout un corpus alors que le travail a déjà été effectué. Un lot qui dépasse `timeout` enregistre en échec chacun de ses échantillons.

`extensions` et les règles doivent s'accorder. Un fichier dont l'extension n'est pas listée n'est jamais transmis à semgrep, quel que soit le nombre de règles qui l'auraient couvert, et cet échec est silencieux : l'analyse rapporte zéro détection, ce qui est indiscernable d'un arbre sain. C'est pourquoi le pipeline d'audit de code source enregistre `files_scanned` à côté de `finding_count`.

Deux autres résultats sont refusés plutôt que rapportés comme sains, car vus de l'extérieur ils ressemblent exactement à un corpus sain : semgrep revenant avec des erreurs de chargement et aucun résultat, et semgrep ne listant aucun des fichiers qui lui ont été soumis. Les deux font échouer le lot et le disent.

Un échantillon dont le `target_dir` n'est pas sur le disque échoue de son côté, avant même qu'un lot soit constitué, et le message demande si l'étape qui produit ce répertoire s'exécute bien avant celle-ci, ce qui est la réponse habituelle.

`min_findings` filtre un échantillon à cette étape plutôt que de le faire échouer : il quitte donc l'exécution avec une raison enregistrée et son `findings.json` toujours attaché. Les deux pipelines fournis règlent `min_findings: 1`, ce qui évite qu'un échantillon sur lequel rien n'a été signalé coûte un appel au modèle en aval.
