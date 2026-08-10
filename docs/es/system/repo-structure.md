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
│   ├── pipeline.py      # Carga y valida un pipeline.yaml, y deriva la clave de corpus
│   ├── runner.py        # Lleva las etapas sobre el corpus, en anchura
│   ├── stage.py         # Clases base de procesador, StageSpec, el resumen de entradas de la etapa
│   ├── state.py         # StateStore, RunState, SampleState
│   ├── registry.py      # Resuelve una referencia de procesador a una clase
│   ├── report.py        # Genera el informe navegable a partir del estado de la ejecución
│   ├── ui.py            # Panel de terminal en vivo para una canalización en marcha
│   ├── context.py       # Escribe el context.md de cada muestra para consumo del LLM
│   └── backends/        # Backends de LLM intercambiables, resueltos por el prefijo del modelo
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

El listado de `engine/` nombra los módulos de los que hablan el resto de estas páginas, para
que una referencia cruzada pueda seguirse hasta un archivo. El paquete contiene algunos más.

Cada directorio de canalización contiene su `pipeline.yaml`, las plantillas de prompt Jinja
que renderizan sus etapas de LLM y las reglas de semgrep que carga su etapa de análisis. Para
añadir una no hay que cambiar nada fuera de ese directorio, y ese es justamente el objetivo:
`pipelines/` y `processors/` se leen por ruta, no se registran en el código.
