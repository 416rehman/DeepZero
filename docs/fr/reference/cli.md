---
layout: default
title: Référence de la CLI
order: 1
---

## Interface en Ligne de Commande

La CLI `deepzero` est le point d'interaction principal pour l'exécution et la gestion des pipelines.

```bash
# Exécution standard
deepzero run ./targets -p pipelines/loldrivers/pipeline.yaml

# Exécuter avec nettoyage de l'état (nouvelle exécution)
deepzero run ./targets -p pipelines/loldrivers/pipeline.yaml --clean

# Vérifier l'état de l'exécution
deepzero status -p loldrivers

# Lancer la REPL d'analyse interactive
deepzero interactive -w work/loldrivers

# Démarrer l'API REST Starlette
deepzero serve -w work/loldrivers --port 8420

# Échafauder un nouveau pipeline personnalisé
deepzero init my_custom_pipeline

# Valider le schéma sans exécution
deepzero validate loldrivers

# Inspecter le registre système
deepzero list-processors
```

### Commandes Principales

| Commande | Description |
| --------- | ----------- |
| `run` | Exécute un pipeline sur une cible. Reprend automatiquement si un état existe. |
| `status` | Affiche l'état actuel de l'exécution du pipeline, les verdicts et les métriques des étapes. |
| `interactive` | REPL d'analyse interactive avec conversation assistée par LLM sur les résultats du pipeline. |
| `serve` | Démarre le serveur API REST pour exposer l'état du pipeline en externe. |
| `init` | Échafaude un nouveau répertoire de pipeline avec un `pipeline.yaml` standard. |
| `validate` | Effectue une validation à blanc (dry-run) du schéma d'un pipeline et des importations de processeurs. |
| `list-processors` | Liste tous les types de processeurs intégrés et enregistrés dynamiquement. |

### Drapeaux d'Exécution (`run`)
| Drapeau | Description |
| --------- | ----------- |
| `TARGET` | Argument positionnel. Chemin vers le corpus d'analyse (fichier ou répertoire). |
| `-p, --pipeline` | Identifiant, nom du répertoire ou chemin de fichier YAML discret. |
| `--clean` | Purger le répertoire d'état existant avant l'exécution. |

### API REST (`serve`)

> [!WARNING]
> **Fonctionnalité Expérimentale / En cours de développement**
> Le serveur API REST est actuellement incomplet, très instable, et **ne doit pas être utilisé**. Il est fourni strictement pour le développement expérimental en local.

Démarre une API REST FastAPI/Starlette en lecture seule pour interroger l'état d'exécution et les données des échantillons.

| Point d'accès | Méthode | Description |
|----------|--------|-------------|
| `/api/health` | GET | Vérification de l'état de santé |
| `/api/runs` | GET | Lister les exécutions de pipeline disponibles dans le répertoire de travail |
| `/api/run` | GET | Récupérer l'état global et les métriques de l'exécution actuelle |
| `/api/samples` | GET | Lister les échantillons (filtrables via `?verdict=`, `?stage=`, `?status=`) |
| `/api/samples/{sample_id}` | GET | État complet de l'échantillon avec l'historique des données du pipeline |
| `/api/samples/{sample_id}/artifacts/{name}` | GET | Lire un artefact de fichier spécifique généré par un processeur |
