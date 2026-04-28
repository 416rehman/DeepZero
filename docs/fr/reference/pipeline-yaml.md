---
layout: default
title: YAML du Pipeline
order: 2
---

## Configuration du Pipeline

Un **Pipeline** dans DeepZero est un graphe d'exécution déclaratif définissant un processus de transformation de données continu et résilient. Il traduit un ensemble de données physiques brutes en un ensemble de données analytiques à fort signal.

Le schéma du pipeline est rigoureusement défini en YAML. DeepZero résout la configuration dynamiquement, prenant en charge l'expansion de variables shell native (par exemple, `${VAR:-default}`).

### Schéma de Configuration

```yaml
name: my_pipeline
description: Pipeline standard de recherche de vulnérabilités
version: "1.0"
model: openai/gpt-4o  # Cible d'intégration LiteLLM par défaut

settings:
  work_dir: work
  max_workers: 8  # Plafond global des limites de threads du ThreadPoolExecutor

stages:
  # Étape 1 : DOIT être un IngestProcessor
  - name: discover
    processor: file_discovery
    config:
      extensions: ["*"]

  # Étape 2 : Filtre Synchrone
  - name: filter
    processor: metadata_filter
    config:
      require:
        is_executable: true

  # Étape 3 : Traitement Map à latence élevée
  - name: decompile
    processor: ghidra_decompile/ghidra_decompile.py
    parallel: 4           # Restreint la concurrence de mapping à 4 JVMs Ghidra simultanées
    timeout: 300          # Impose une horloge de destruction stricte de 300 secondes par échantillon via process.py
    on_failure: skip      # Gère les exceptions de manière silencieuse plutôt que d'avorter (skip, retry, abort)
    max_retries: 2        # Contrainte d'exécution de la logique de réessai
    config:
      ghidra_install_dir: ${GHIDRA_INSTALL_DIR}
```

### Options des Étapes

Chaque étape définie sous le tableau `stages:` accepte les attributs suivants :

| Champ | Type | Défaut | Description |
|-------|------|---------|-------------|
| `name` | string | `stage_N` | Nom unique de l'étape au sein du pipeline |
| `processor` | string | requis | Référence du processeur (voir ci-dessous) |
| `config` | dict | `{}` | Configuration spécifique au processeur |
| `parallel` | int | `4` | Concurrence pour les processeurs Map. `0` s'adapte automatiquement à `os.cpu_count()` |
| `timeout` | int | `0` | Délai d'attente par échantillon en secondes (0 = pas de délai) |
| `on_failure` | string | `skip` | Définit le comportement de tolérance aux pannes : `skip`, `retry`, ou `abort` |
| `max_retries` | int | `0` | Nombre de réessais lorsque `on_failure: retry` |

### Logique de Résolution (`engine/pipeline.py`)

Lorsqu'il est appelé via la CLI, l'analyseur tente de résoudre les processeurs selon un ordre hiérarchique strict :
1. **Résolveurs de Chemins :** Chemins de fichiers directs se terminant par `.py` (par exemple, `processors/ghidra/ghidra.py:Decompiler`).
2. **Recherche dans un Répertoire :** `pipeline/my_pipeline/processors/`.
3. **Registre Interne :** Composants intégrés au système explicitement enregistrés dans `stages/__init__.py`.
4. **Importation Python Pointée :** Modules évalués dynamiquement (par exemple, `my.python.module:MyClass`).

### Expansion Dynamique

Avant que la validation du schéma ne lie les processeurs, DeepZero parcourt l'ensemble de l'arbre DOM YAML, en évaluant les correspondances Regex pour `\$\{([^}]+)\}`. Les variables d'environnement dictent la configuration d'exécution résolue. Cela empêche explicitement de coder en dur des clés d'API ou des répertoires d'installation au sein des pipelines `.yaml` validés.
