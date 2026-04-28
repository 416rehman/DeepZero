---
layout: default
title: Creación de Procesadores
order: 2
---

## Construcción de Procesadores Personalizados

La lógica del usuario se integra en DeepZero extendiendo las abstracciones tipificadas en `deepzero.engine.stage`.

### Contexto del Procesador (`ProcessorContext`)

El objeto `ctx` inyectado en cada enlace del ciclo de vida proporciona un contexto en todo el sistema:
- `ctx.pipeline_dir`: El directorio raíz de la canalización en ejecución.
- `ctx.global_config`: Un TypedDict que contiene `settings`, `knowledge` y `model`.
- `ctx.llm`: La instancia del proveedor de API LiteLLM.
- `ctx.log`: Un objeto registrador configurado (logger).

### Definiciones de Configuración

Utilice `@dataclass` llamado `Config` para definir sus configuraciones YAML aceptadas. El motor analizará el [YAML de la Canalización]({{ '/es/reference/pipeline-yaml.html' | relative_url }}) y creará una instancia de su objeto `Config`.
