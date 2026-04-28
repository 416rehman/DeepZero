---
layout: default
title: Referencia de CLI
order: 1
---

## Interfaz de Línea de Comandos

La CLI `deepzero` es el punto principal de interacción para ejecutar y administrar canalizaciones.

```bash
# Ejecución estándar
deepzero run ./targets -p pipelines/loldrivers/pipeline.yaml

# Ejecutar limpiando el estado (ejecución en limpio)
deepzero run ./targets -p pipelines/loldrivers/pipeline.yaml --clean

# Comprobar el estado de ejecución
deepzero status -p loldrivers

# Iniciar la REPL de análisis interactivo
deepzero interactive -w work/loldrivers

# Iniciar la API REST de Starlette
deepzero serve -w work/loldrivers --port 8420

# Crear una nueva canalización personalizada
deepzero init my_custom_pipeline

# Validar el esquema sin ejecutar
deepzero validate loldrivers

# Inspeccionar el registro del sistema
deepzero list-processors
```

### Comandos principales

| Comando | Descripción |
| ------- | ----------- |
| `run` | Ejecuta una canalización en un objetivo. Se reanuda automáticamente si existe estado. |
| `status` | Muestra el estado actual de la ejecución de la canalización. |
| `interactive` | REPL interactivo impulsado por IA. |
| `serve` | Inicia el servidor de API REST. |
| `init` | Crea un nuevo directorio de canalización. |
| `validate` | Valida el esquema de una canalización. |
| `list-processors` | Enumera todos los tipos de procesadores integrados. |
