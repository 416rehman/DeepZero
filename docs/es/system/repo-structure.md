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
└── stages/              # Procesadores de la biblioteca estándar

processors/              # Procesadores de referencia y contribuidos
pipelines/               # Declaraciones de canalización y lógica
tests/                   # Conjunto de validación de Pytest
```
