---
layout: default
title: Structure du Dépôt
order: 2
---

## Structure du Dépôt

```text
src/deepzero/
├── __init__.py          # Définitions SemVer
├── __main__.py          # Point d'entrée du module
├── cli.py               # Interface de l'application Click
├── api/                 # Points de terminaison REST Starlette
├── engine/              # Logique principale d'exécution et d'orchestration
│   ├── pipeline.py      # Charge et valide un pipeline.yaml, dérive la clé de corpus
│   ├── runner.py        # Conduit les étapes sur le corpus, en largeur d'abord
│   ├── stage.py         # Classes de base des processeurs, StageSpec, empreinte des entrées d'étape
│   ├── state.py         # StateStore, RunState, SampleState
│   ├── registry.py      # Résout une référence de processeur vers une classe
│   ├── report.py        # Construit le rapport consultable à partir de l'état de l'exécution
│   ├── ui.py            # Tableau de bord terminal en direct pour un pipeline en cours
│   ├── context.py       # Écrit le context.md de chaque échantillon à destination du LLM
│   └── backends/        # Backends LLM enfichables, résolus par schéma de modèle
└── stages/              # Processeurs de la bibliothèque standard

processors/              # Processeurs de référence et contribués
├── ghidra_decompile/    # Décompilateur headless Ghidra (Map)
├── git_ingest/          # Découverte et clonage de dépôts git (Ingest)
├── loldrivers_filter/   # Filtre d'exclusion de hachage loldrivers.io (Map)
├── pe_ingest/           # Parseur d'en-tête PE et extracteur de métadonnées (Ingest)
└── semgrep_scanner/     # Scanneur de lots Semgrep (BulkMap)

pipelines/               # Déclarations et logique des pipelines
├── loldrivers/          # Recherche sur les pilotes noyau BYOVD
└── source_audit/        # Audit de code source sur des dépôts git

docs/                    # Documentation GitHub Pages basée sur Jekyll
tests/                   # Suite de validation Pytest
```

Le listing d'`engine/` nomme les modules dont traitent les autres pages, afin qu'un renvoi puisse être suivi jusqu'à un fichier. Le paquet en contient quelques autres.

Chaque répertoire de pipeline contient son `pipeline.yaml`, les modèles de prompts Jinja que ses étapes LLM rendent, et les règles semgrep que son étape d'analyse charge. Rien en dehors de ce répertoire n'a besoin d'être modifié pour en ajouter un, et c'est précisément l'intention : `pipelines/` et `processors/` sont lus par chemin, et non enregistrés dans le code.
