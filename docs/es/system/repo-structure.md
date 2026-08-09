---
layout: default
title: Estructura del repositorio
order: 2
---

## Estructura del repositorio

```text
src/deepzero/
├── __init__.py          # Definiciones de SemVer
├── __main__.py          # Punto de entrada del módulo
├── cli.py               # Interfaz de la aplicación Click
├── api/                 # Endpoints REST de Starlette
├── engine/              # Lógica principal de ejecución y orquestación
│   ├── backends/        # Backends de LLM intercambiables, resueltos por el prefijo del modelo
│   └── report.py        # Genera el informe navegable a partir del estado de la ejecución
└── stages/              # Procesadores de la biblioteca estándar

processors/              # Procesadores de referencia y contribuidos
├── ghidra_decompile/    # Descompilador Ghidra sin interfaz gráfica (Map)
├── git_ingest/          # Descubrimiento y clonado de repositorios git (Ingest)
├── loldrivers_filter/   # Filtro de exclusión por hash de loldrivers.io (Map)
├── pe_ingest/           # Analizador de encabezados PE y extractor de metadatos de controladores (Ingest)
└── semgrep_scanner/     # Escáner semgrep por lotes (BulkMap)

pipelines/               # Declaraciones de canalización y lógica
├── loldrivers/          # Investigación BYOVD de controladores del kernel
└── source_audit/        # Auditoría de código fuente sobre repositorios git

docs/                    # Documentación de GitHub Pages basada en Jekyll
tests/                   # Conjunto de validación de Pytest
```

Cada directorio de canalización contiene su `pipeline.yaml`, las plantillas de prompt Jinja
que renderizan sus etapas de LLM y las reglas de semgrep que carga su etapa de análisis. Para
añadir una no hay que cambiar nada fuera de ese directorio, y ese es justamente el objetivo:
`pipelines/` y `processors/` se leen por ruta, no se registran en el código.
