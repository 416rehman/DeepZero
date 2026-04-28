---
layout: default
title: Arquitectura Básica
order: 2
---

## Arquitectura del Motor

El motor de orquestación de DeepZero opera en un estricto gráfico de procesamiento dirigido (DAG) definido por las [canalizaciones]({{ '/es/reference/pipeline-yaml.html' | relative_url }}). El motor de ejecución garantiza una [gestión del estado]({{ '/es/system/state-persistence.html' | relative_url }}) resistente a fallos y reanudable.

### Ciclos de Vida de los Componentes

El modelo de datos pasa a través de las siguientes abstracciones:

1. **`Sample`**: La estructura base emitida por un `IngestProcessor`. Asigna una ruta física a un `sample_id` único.
2. **`SampleState`**: Un registro persistente mantenido por el `StateStore`. Rastrea el veredicto (`PENDING`, `ACTIVE`, `FILTERED`, `FAILED`, `COMPLETED`).
3. **`ProcessorEntry`**: Una fachada que se pasa a los procesadores Map/Reduce, utilizando una inicialización de memoria diferida (lazy-loading).
