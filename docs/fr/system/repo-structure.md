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
└── stages/              # Processeurs de la bibliothèque standard

processors/              # Processeurs de référence et contribués
pipelines/               # Déclarations et logique des pipelines
tests/                   # Suite de validation Pytest
```
