---
layout: default
title: Processeurs Intégrés
order: 1
---

## Processeurs Intégrés

| Identifiant | Type | Fonctionnalité |
| ----------- | ---- | -------------- |
| `file_discovery` | Ingest | Parcours récursif du système de fichiers et hachage cryptographique. |
| `metadata_filter` | Map | Vérification de contraintes booléennes et déduplication de champs. |
| `hash_exclude` | Map | Exclusions cryptographiques via des listes intégrées ou des fichiers plats. |
| `generic_llm` | Map | Rendu de modèles Jinja2, appel de LLM, et analyse des réponses. |
| `generic_command` | Map | Exécution arbitraire de commandes shell avec substitution de variables contextuelles. |
| `top_k` | Reduce | Tronque l'ensemble des échantillons en fonction de valeurs scalaires numériques. |
| `sort` | Reduce | Réorganisation déterministe des échantillons sans réduction de l'ensemble de données. |
