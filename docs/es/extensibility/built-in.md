---
layout: default
title: Procesadores integrados
order: 1
---

## Procesadores integrados

| Identificador | Tipo | Funcionalidad |
| ------------- | ---- | ------------- |
| `file_discovery` | Ingest | Recorrido recursivo del sistema de archivos y hash criptográfico. |
| `metadata_filter` | Map | Comprobación de restricciones booleanas y deduplicación de campos. |
| `hash_exclude` | Map | Exclusiones criptográficas mediante listas integradas o archivos planos. |
| `generic_llm` | Map | Renderizado de plantillas Jinja2, invocación de LLM y análisis de respuestas. |
| `generic_command` | Map | Ejecución arbitraria de comandos shell con sustitución de variables. |
| `top_k` | Reduce | Trunca el conjunto de muestras en función de valores escalares numéricos. |
| `sort` | Reduce | Reordenación determinista de muestras sin reducción del conjunto de datos. |
