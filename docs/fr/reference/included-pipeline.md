---
layout: default
title: Pipelines Inclus
order: 3
---

## Pipelines Inclus

Deux pipelines complets sont fournis avec DeepZero. Ils existent pour être exécutés, et pour être lus comme des exemples concrets de ce à quoi ressemble une définition de pipeline lorsqu'elle fait quelque chose de réel.

| Pipeline | Corpus | Ce qu'il recherche |
|----------|--------|--------------------|
| `pipelines/loldrivers` | Pilotes noyau Windows sur le disque | Candidats BYOVD : surfaces IOCTL atteignables sans le matériel |
| `pipelines/source_audit` | Dépôts git | Vulnérabilités au niveau du code source atteignables depuis une entrée non fiable |

Tous deux déclarent `model: claude-code/claude-opus-5` : ils s'exécutent donc via un abonnement Claude Code, sans clé d'API. Remplacez-le avec `-m` pour n'importe quel modèle LiteLLM. Consultez [Choisir un Modèle]({{ '/fr/reference/pipeline-yaml.html' | relative_url }}).

---

## Pipeline LOLDrivers

Un pipeline de référence BYOVD (Bring Your Own Vulnerable Driver) est maintenu dans `pipelines/loldrivers/`.

| Étape | Processeur | Ce qu'elle fait |
|-------|------------|-----------------|
| `discover` | `pe_ingest/pe_ingest.py` | Ingestion de PE et analyse des en-têtes LIEF |
| `kernel_filter` | `metadata_filter` | Restreint aux pilotes en mode noyau exposant des surfaces IOCTL, et déduplique sur le hachage |
| `loldrivers_filter` | `loldrivers_filter/loldrivers_filter.py` | Exclut les entités connues répertoriées via loldrivers.io |
| `decompile` | `ghidra_decompile/ghidra_decompile.py` | Exécute la décompilation Ghidra sans interface graphique (headless) |
| `semgrep_scanner` | `semgrep_scanner/semgrep_scanner.py` | Analyse statique en masse sur le code source C exporté. Un pilote dont rien n'est signalé s'arrête ici (`min_findings: 1`) |
| `rank_by_findings` | `top_k` | Ordonne chaque pilote survivant par nombre de détections, du pire au meilleur |
| `assess` | `generic_llm` | Effectue le rendu de `assessment.j2` pour chaque pilote et enregistre le verdict |

L'étape de classement conserve tout (`keep_top: 0`) et ne fait que modifier l'ordre. C'est délibéré : ne garder qu'une élite économise des appels d'évaluation, mais décide quels pilotes méritent d'être lus en se fondant sur un nombre de détections, ce qui est précisément le jugement que l'étape d'évaluation existe pour rendre. Ordonner du pire au meilleur fait examiner les mêmes pilotes en premier sans jeter le reste, et une exécution arrêtée tôt aura tout de même consacré son temps aux pilotes les plus bruyants.

Les exclusions s'exécutent avant la décompilation pour la même raison, prise à l'envers : Ghidra est de loin l'étape la plus coûteuse, donc chaque pilote écarté par une vérification d'en-tête bon marché ou une recherche de hachage représente des minutes économisées.

### Savoir si une détection peut être exercée sans le matériel

De nombreux pilotes ne créent leur objet périphérique qu'une fois leur matériel énuméré. Sur une machine ou une VM dépourvue de ce périphérique, `\.\<name>` ne s'ouvre jamais, et rien de ce que le pilote expose ne peut être atteint. À la seule lecture du rapport, cela est indiscernable d'un pilote non vulnérable.

L'étape `decompile` enregistre où l'objet périphérique est créé :

| Valeur | Signification |
|--------|---------------|
| `device_created_in` | la fonction qui appelle `IoCreateDevice` |
| `device_on_load_path` | si cette fonction est `DriverEntry`, ou quelque chose qu'elle appelle |

`device_on_load_path: true` signifie que le périphérique apparaît sur toute machine capable de charger le pilote : une détection le concernant peut donc être confirmée dès aujourd'hui. `false` signifie qu'il est créé ailleurs, typiquement dans un rappel PnP add-device ou start-device, et que confirmer quoi que ce soit nécessite le périphérique physique. Ni l'un ni l'autre n'est enregistré lorsque `IoCreateDevice` n'est pas trouvé du tout, plutôt que de deviner.

Le pipeline fourni liste `decompile.device_on_load_path` sous `report.columns`, de sorte que la valeur s'affiche en regard de chaque pilote. Il n'en faut pas plus : la valeur est déclarée dans le `provides` du processeur et nommée par le pipeline, et le rapport continue d'ignorer ce qu'est un objet périphérique.

### Ce que la décompilation écrit pour chaque pilote

L'étape `decompile` écrit dans le répertoire `decompiled/` de chaque échantillon :

| Fichier | Contenu |
|---------|---------|
| `dispatch_ioctl.c` | La routine de dispatch, enregistrée une seule fois |
| `ioctls/0xXXXXXXXX.c` | Un fichier par code IOCTL : ce à quoi le code se décode, pointant vers la routine ci-dessus |
| `ghidra_result.json` | Métadonnées : nom du périphérique, lien symbolique, nom du dispatch, et une entrée par code IOCTL |

Tous les codes d'un pilote sont traités par la même routine : elle est donc stockée une fois et référencée, jamais copiée pour chaque code. Une entrée de `ioctl_handlers` ne contient que le code et ses champs décodés (`hex`, `device_type`, `function`, `method`, `access`).

La taille mérite d'être surveillée, car le mode de défaillance est ici silencieux : la sortie continue de paraître correcte, simplement énorme. À titre de référence, un pack de 1 388 pilotes décompilés produit au total environ **28 Mo** de `ghidra_result.json`. Stocker la routine pour chaque code produisait **734 Mo** pour le même corpus, un seul pilote atteignant 52 Mo. Une exécution d'étape dont la sortie dépasse cet ordre de grandeur a régressé vers la répétition de la routine, et l'étape d'évaluation analysera alors ce document pour chaque pilote lors de la construction de son prompt.

`tests/test_extract_dispatch.py` protège directement la forme des entrées.

### Prérequis

- Ghidra, avec `GHIDRA_INSTALL_DIR` défini. `JAVA_HOME` est lu s'il est présent.
- `semgrep` dans le PATH : `pip install semgrep`.

---

## Pipeline d'Audit de Code Source

Un audit de code source sur des dépôts git, dans `pipelines/source_audit/`. Chaque dépôt est pris à une révision donnée, analysé avec semgrep, puis lu par un modèle dont le travail consiste à distinguer une véritable vulnérabilité d'une règle qui a simplement reconnu une forme dans le code.

| Étape | Processeur | Ce qu'elle fait |
|-------|------------|-----------------|
| `discover` | `git_ingest/git_ingest.py` | Clone chaque dépôt à une profondeur de 1, ou lit une copie de travail déjà présente sur le disque, et enregistre la révision que tout l'aval est en train de juger |
| `size_filter` | `metadata_filter` | Écarte les copies de travail sans code source et les arbres trop volumineux pour mériter une analyse ; un commit atteint sous deux noms n'est analysé qu'une fois |
| `scan` | `semgrep_scanner/semgrep_scanner.py` | Exécute `rules/` sur chaque copie de travail. Un dépôt dont rien n'est signalé s'arrête ici |
| `rank` | `top_k` | Ordonne chaque dépôt survivant par nombre de détections, du pire au meilleur, sans en écarter aucun |
| `assess` | `generic_llm` | Effectue le rendu de `assessment.j2` pour chaque dépôt et enregistre le verdict |

Les deux moitiés comptent, dans cet ordre. Semgrep coûte peu et trouve tous les endroits qui méritent un regard ; presque tous ces endroits sont sains. L'étape d'évaluation est celle où une détection soit gagne un chemin depuis l'entrée d'un attaquant jusqu'au point sensible, soit est écartée, nommément, comme inatteignable.

### Vers quoi le pointer

`deepzero run` prend une seule cible, et l'étape d'ingestion lit l'une ou l'autre forme :

- **Un répertoire**, dont chaque sous-répertoire immédiat est une copie de travail. Rien n'est récupéré sur le réseau : du code privé n'a donc jamais à quitter la machine où il se trouve déjà. Un répertoire qui est lui-même une copie de travail est lu comme un dépôt unique, et un simple dépôt de sources sans `.git` est tout de même lu ; il n'a simplement ni révision ni origine à rapporter.
- **Un fichier**, lu comme un manifeste de dépôts à cloner. Du texte brut, un par ligne, avec des commentaires `#`, ou du YAML sous forme de liste ou de mapping avec une clé `repos:` dont les entrées peuvent épingler une référence.

```bash
# auditer les dépôts listés dans un manifeste
deepzero run repos.txt -p pipelines/source_audit/pipeline.yaml

# ou un répertoire de copies de travail déjà présentes sur le disque
deepzero run C:\code\vendor -p pipelines/source_audit/pipeline.yaml
```

Les clones résident dans le répertoire de cache propre à l'étape d'ingestion plutôt que dans le répertoire de travail : une nouvelle exécution ne coûte donc aucun accès réseau, et `--clean` ne les jette pas.

### Règles et langages

`rules/` contient 136 règles semgrep couvrant Python, JavaScript, TypeScript, Go, Java, Ruby, PHP et C#, regroupées par ce qu'elles recherchent : injection, traversée de chemin et SSRF, authentification et autorisation, cryptographie et secrets, désérialisation, et XSS et en-têtes de réponse.

Trois endroits doivent s'accorder : les règles, la liste `extensions` de `discover`, et la liste identique sur `scan`. Ils échouent dans des directions opposées. Une extension que les listes oublient n'est ni comptée ni analysée : le dépôt paraît donc plus petit et plus sain qu'il ne l'est. Une extension que les listes portent mais qu'aucune règle ne couvre est parcourue, comptée et préparée pour une analyse qui ne pourra jamais la faire correspondre. Ajouter un langage implique les trois, et `tests/test_source_audit_pipeline.py` échoue s'ils divergent.

Un dépôt écrit dans un langage que `rules/` ne couvre pas compte donc zéro fichier source et est écarté par `size_filter`. Cela se lit comme « pas de code source » alors que cela signifie « rien ici que ce pipeline puisse auditer », et c'est tout de même l'issue qu'il vaut mieux avoir : l'arbre est écarté une étape après le clonage, plutôt que préparé pour une analyse dont les règles n'auraient jamais pu se déclencher.

### Lire son rapport

Le pipeline déclare son propre vocabulaire, parce qu'un dépôt n'est pas un fichier sur un disque :

```yaml
report:
  title: Source repository audit
  entity: repository
  entity_plural: repositories
  target_label: organisation
  classification_key: classification
  vulnerable_when: [vulnerable]
  safe_when: [not exploitable]
  lexicon:
    negative: Not exploitable
```

`vulnerable_when` est restreint pour une raison qu'il vaut la peine de connaître. L'évaluation répond `[VULNERABLE]` ou `[NOT EXPLOITABLE]`, et la liste des positifs par défaut inclut `exploitab`, que contient le verdict négatif. Consultez [Comment un verdict est mis en correspondance]({{ '/fr/reference/pipeline-yaml.html' | relative_url }}). `vulnerable_when` et `safe_when` sont les anciennes graphies de `positive_when` et `negative_when` et signifient toujours la même chose.

L'unique redéfinition du lexique est là parce qu'un dépôt n'atteint l'évaluation que si l'analyse a signalé quelque chose. Rien dans la catégorie négative n'est du code intouché : c'est un dépôt dont les détections ont été lues et dont aucune n'a abouti. « Clear », le mot par défaut pour cette catégorie, dit le contraire.

Ses `columns` placent le nombre de détections, les fichiers analysés, le nombre de fichiers source, le langage principal et la révision en regard de chaque dépôt. Les fichiers analysés méritent leur place : un dépôt sans détection et un dépôt dont semgrep n'a jamais ouvert les fichiers affichent tous deux zéro détection, et un seul des deux constitue un résultat.

### Prérequis

- `git` dans le PATH, pour l'étape `discover`.
- `semgrep` dans le PATH : `pip install semgrep`.

Vérifiez tout cela, pour l'un ou l'autre pipeline, avant de vous engager dans une longue exécution :

```bash
deepzero validate pipelines/source_audit/pipeline.yaml
```

Elle sort avec le code 1 si elle signale une erreur : elle peut donc conditionner un commit, et pas seulement être lue.
