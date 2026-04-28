---
layout: default
title: YAML de Canalización
order: 2
---

## Configuración de Canalizaciones

Una **Canalización (Pipeline)** en DeepZero es el gráfico de ejecución declarativa que define un flujo de trabajo de mutación de datos. El esquema está estrictamente definido en YAML.

### Esquema de Configuración

```yaml
name: my_pipeline
description: A standard vulnerability hunting pipeline
version: "1.0"
model: openai/gpt-4o

settings:
  work_dir: work
  max_workers: 8

stages:
  - name: discover
    processor: file_discovery
    config:
      extensions: ["*"]
```

### Argumentos de Etapa

| Campo | Tipo | Predeterminado | Descripción |
|-------|------|----------------|-------------|
| `name` | string | `stage_N` | Nombre único para la etapa |
| `processor` | string | requerido | El registro de referencia al procesador |
| `config` | dict | `{}` | Configuración inyectada al procesador |
| `parallel` | int | `4` | Concurrencia máxima para procesadores Map |
