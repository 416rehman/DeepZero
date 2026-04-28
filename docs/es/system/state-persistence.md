---
layout: default
title: Persistencia de Estado
order: 1
---

## Subsistema de Persistencia

La integridad de los datos de la canalización está respaldada por un módulo abstracto `StateStore`. Las implementaciones respaldadas por el sistema de archivos están protegidas contra daños, incluso durante las interrupciones del kernel a nivel del sistema operativo, mediante reemplazos atómicos de archivos de volcado.

### Archivos de Reemplazo Atómico (`atomic_replace`)

En lugar de escribir en artefactos en vivo de manera destructiva, la capa de persistencia dirige las serializaciones a búferes `.tmp` intermedios. Tras una serialización exitosa completa, se realiza una sobrescritura posix que evita bloqueos a través de `os.replace`.

### Jerarquía del Espacio de Trabajo

```text
work/<pipeline_name>/
├── run.json             # Estado serializado a nivel de instancia
├── pipeline.yaml        # Copia de la configuración YAML original
└── samples/
    └── <sample_id>/     # Carpeta de espacio aislado y persistencia aislada
        └── state.json   # Estado persistente del archivo
```
