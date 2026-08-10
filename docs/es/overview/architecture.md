---
layout: default
title: Arquitectura Básica
order: 2
---

## Arquitectura del Motor

El motor de orquestación de DeepZero opera en un estricto gráfico de procesamiento dirigido (DAG) definido por las [canalizaciones]({{ '/es/reference/pipeline-yaml.html' | relative_url }}). El motor de ejecución garantiza una [gestión del estado]({{ '/es/system/state-persistence.html' | relative_url }}) resistente a fallos y reanudable, mientras reparte operaciones en paralelo sobre un grupo de hilos acotado ([`ThreadPoolExecutor`](https://docs.python.org/3/library/concurrent.futures.html#threadpoolexecutor)).

<div class="architecture-diagram" style="margin: 3rem 0;">
    <svg viewBox="0 0 800 400" style="width: 100%; height: auto; max-width: 800px;" xmlns="http://www.w3.org/2000/svg">
        <defs>
            <linearGradient id="flowGrad" x1="0%" y1="0%" x2="100%" y2="0%">
                <stop offset="0%" stop-color="var(--border)" />
                <stop offset="50%" stop-color="var(--text-tertiary)" />
                <stop offset="100%" stop-color="var(--border)" />
            </linearGradient>
            <pattern id="isoGridSmall" width="40" height="23.094" patternUnits="userSpaceOnUse" patternTransform="scale(1)">
                <path d="M 40 0 L 0 23.094 M 0 0 L 40 23.094 M 20 23.094 L 20 0" fill="none" stroke="var(--border)" stroke-width="0.5"/>
            </pattern>
        </defs>
        
        <rect width="100%" height="100%" fill="url(#isoGridSmall)" opacity="0.3"/>

        <!-- Ingest Node -->
        <g transform="translate(150, 200)">
            <path d="M 0 0 L 60 -30 L 120 0 L 60 30 Z" fill="var(--bg-primary)" stroke="var(--text-primary)" stroke-width="1.5" stroke-linejoin="round"/>
            <path d="M 0 0 L 0 40 L 60 70 L 120 40 L 120 0 L 60 30 Z" fill="var(--bg-secondary)" stroke="var(--text-primary)" stroke-width="1.5" stroke-linejoin="round"/>
            <path d="M 60 30 L 60 70" stroke="var(--text-primary)" stroke-width="1.5"/>
            <text x="60" y="-5" font-family="JetBrains Mono, monospace" font-size="12" font-weight="bold" text-anchor="middle" fill="var(--text-secondary)" transform="skewX(30) rotate(-30)">INGEST</text>
            <text x="60" y="30" font-family="Inter, sans-serif" font-size="10" text-anchor="middle" fill="var(--text-tertiary)" transform="skewX(30) rotate(-30)">1 → N</text>
        </g>

        <!-- Connecting Lines to Map -->
        <path d="M 210 170 L 250 150 L 300 150 L 350 125" fill="none" stroke="url(#flowGrad)" stroke-width="2" stroke-dasharray="6 6">
            <animate attributeName="stroke-dashoffset" from="100" to="0" dur="2s" repeatCount="indefinite" />
        </path>
        <path d="M 210 170 L 350 170" fill="none" stroke="url(#flowGrad)" stroke-width="2" stroke-dasharray="6 6">
            <animate attributeName="stroke-dashoffset" from="100" to="0" dur="2s" repeatCount="indefinite" />
        </path>
        <path d="M 210 170 L 250 190 L 300 190 L 350 215" fill="none" stroke="url(#flowGrad)" stroke-width="2" stroke-dasharray="6 6">
            <animate attributeName="stroke-dashoffset" from="100" to="0" dur="2s" repeatCount="indefinite" />
        </path>

        <!-- Map Nodes -->
        <g transform="translate(350, 90)">
            <path d="M 0 0 L 40 -20 L 80 0 L 40 20 Z" fill="var(--bg-primary)" stroke="var(--text-primary)" stroke-width="1.5" stroke-linejoin="round"/>
            <path d="M 0 0 L 0 20 L 40 40 L 80 20 L 80 0 L 40 20 Z" fill="var(--bg-secondary)" stroke="var(--text-primary)" stroke-width="1.5" stroke-linejoin="round"/>
            <path d="M 40 20 L 40 40" stroke="var(--text-primary)" stroke-width="1.5"/>
            <circle cx="40" cy="0" r="3" fill="var(--text-primary)"/>
            <text x="40" y="-10" font-family="JetBrains Mono, monospace" font-size="10" text-anchor="middle" fill="var(--text-secondary)" transform="skewX(30) rotate(-30)">MAP</text>
        </g>
        <g transform="translate(350, 160)">
            <path d="M 0 0 L 40 -20 L 80 0 L 40 20 Z" fill="var(--bg-primary)" stroke="var(--text-primary)" stroke-width="1.5" stroke-linejoin="round"/>
            <path d="M 0 0 L 0 20 L 40 40 L 80 20 L 80 0 L 40 20 Z" fill="var(--bg-secondary)" stroke="var(--text-primary)" stroke-width="1.5" stroke-linejoin="round"/>
            <path d="M 40 20 L 40 40" stroke="var(--text-primary)" stroke-width="1.5"/>
            <circle cx="40" cy="0" r="3" fill="var(--text-primary)"/>
            <text x="40" y="-10" font-family="JetBrains Mono, monospace" font-size="10" text-anchor="middle" fill="var(--text-secondary)" transform="skewX(30) rotate(-30)">MAP</text>
        </g>
        <g transform="translate(350, 230)">
            <path d="M 0 0 L 40 -20 L 80 0 L 40 20 Z" fill="var(--bg-primary)" stroke="var(--text-primary)" stroke-width="1.5" stroke-linejoin="round"/>
            <path d="M 0 0 L 0 20 L 40 40 L 80 20 L 80 0 L 40 20 Z" fill="var(--bg-secondary)" stroke="var(--text-primary)" stroke-width="1.5" stroke-linejoin="round"/>
            <path d="M 40 20 L 40 40" stroke="var(--text-primary)" stroke-width="1.5"/>
            <circle cx="40" cy="0" r="3" fill="var(--text-primary)"/>
            <text x="40" y="-10" font-family="JetBrains Mono, monospace" font-size="10" text-anchor="middle" fill="var(--text-secondary)" transform="skewX(30) rotate(-30)">MAP</text>
        </g>

        <!-- Connecting Lines to Reduce -->
        <path d="M 430 90 L 480 115 L 520 115 L 560 170" fill="none" stroke="url(#flowGrad)" stroke-width="2" stroke-dasharray="6 6">
            <animate attributeName="stroke-dashoffset" from="100" to="0" dur="2s" repeatCount="indefinite" />
        </path>
        <path d="M 430 160 L 560 170" fill="none" stroke="url(#flowGrad)" stroke-width="2" stroke-dasharray="6 6">
            <animate attributeName="stroke-dashoffset" from="100" to="0" dur="2s" repeatCount="indefinite" />
        </path>
        <path d="M 430 230 L 480 205 L 520 205 L 560 170" fill="none" stroke="url(#flowGrad)" stroke-width="2" stroke-dasharray="6 6">
            <animate attributeName="stroke-dashoffset" from="100" to="0" dur="2s" repeatCount="indefinite" />
        </path>

        <!-- Reduce Node -->
        <g transform="translate(560, 180)">
            <path d="M 0 0 L 60 -30 L 120 0 L 60 30 Z" fill="var(--accent)" stroke="var(--bg-primary)" stroke-width="1.5" stroke-linejoin="round"/>
            <path d="M 0 0 L 0 40 L 60 70 L 120 40 L 120 0 L 60 30 Z" fill="var(--text-secondary)" stroke="var(--bg-primary)" stroke-width="1.5" stroke-linejoin="round"/>
            <path d="M 60 30 L 60 70" stroke="var(--bg-primary)" stroke-width="1.5"/>
            <text x="60" y="-5" font-family="JetBrains Mono, monospace" font-size="12" font-weight="bold" text-anchor="middle" fill="var(--bg-primary)" transform="skewX(30) rotate(-30)">REDUCE</text>
            <text x="60" y="30" font-family="Inter, sans-serif" font-size="10" text-anchor="middle" fill="var(--text-tertiary)" transform="skewX(30) rotate(-30)">N → M</text>
            
            <!-- Output stream -->
            <path d="M 60 10 L 90 -5" fill="none" stroke="var(--bg-primary)" stroke-width="2" stroke-dasharray="2 2"/>
            <path d="M 70 20 L 100 5" fill="none" stroke="var(--bg-primary)" stroke-width="2" stroke-dasharray="2 2"/>
        </g>
    </svg>
</div>

### Ciclos de Vida de los Componentes

El modelo de datos pasa por estas abstracciones a medida que una muestra avanza:

1. **`Sample`**: La estructura base emitida por un `IngestProcessor`. Vincula una ruta física (`source_path`) a un `sample_id` único (normalmente un hash SHA-256 o un UUID determinista) e inicializa el diccionario `data` de la muestra.
2. **`SampleState`**: El registro persistente que mantiene el `StateStore`. Rastrea el veredicto (`verdict`) de la muestra (`PENDING`, `ACTIVE`, `FILTERED`, `FAILED`, `TIMED_OUT`, `COMPLETED`) y mantiene un `history` que asocia cada procesador con su `StageOutput`. `TIMED_OUT` se mantiene aparte de `FAILED` porque no dice nada sobre la muestra, y es el único desenlace que un presupuesto mayor puede cambiar.
3. **`ProcessorEntry`**: La fachada generada dinámicamente, eficiente en memoria, que se pasa a los procesadores Map/BulkMap/Reduce. Incorpora un mecanismo de carga diferida (`_store`) que solo recupera del disco los datos históricos de ejecución cuando se accede a `.history` o a `.upstream_data()`.

### Paradigmas de Procesamiento

Los procesadores determinan la topología de ejecución y el modelo de concurrencia. Todos heredan de la clase base `Processor` y exponen los enlaces del ciclo de vida `validate()`, `setup()`, `process()` y `teardown()`. Para escribir los suyos, consulte [Construcción de Procesadores Personalizados]({{ '/es/extensibility/building-custom.html' | relative_url }}).

#### `IngestProcessor` (1 → N)
- **Firma:** `process(ctx: ProcessorContext, target: Path) -> list[Sample]`
- **Concurrencia:** Síncrona. Se ejecuta exactamente una vez por ejecución de la canalización.
- **Función:** Genera el corpus inicial. Antes de la ingestión no existen datos anteriores.

#### `MapProcessor` (1 → 1)
- **Firma:** `process(ctx: ProcessorContext, entry: ProcessorEntry) -> ProcessorResult`
- **Concurrencia:** Reparto entre hilos. Se configura con el campo `parallel:` del YAML de la canalización. `parallel: 0` se ajusta automáticamente, acotado por `max_workers` y por lo que el procesador devuelva en `max_parallelism()`.
- **Restricciones:** Debe ser estrictamente seguro para hilos. Evite el estado mutable compartido.
- **Presupuesto:** `timeout:` acota cuánto espera la etapa por una muestra, no cuánto dura el trabajo. El hilo de trabajo se abandona, nunca se mata, así que un procesador que lance un proceso externo debería acotar ese proceso por su cuenta.

#### `BulkMapProcessor` (N → N)
- **Firma:** `process(ctx: ProcessorContext, entries: list[ProcessorEntry]) -> list[ProcessorResult]`
- **Concurrencia:** Ejecución síncrona sobre una parte o la totalidad de las muestras activas.
- **Función:** Optimiza las invocaciones de procesos externos (por ejemplo, lanzar una herramienta JVM monolítica o un análisis semgrep por lotes) para repartir un arranque costoso entre varias muestras. Las salidas deben indexarse exactamente igual que la lista `entries` de entrada.

#### `ReduceProcessor` (N → M)
- **Firma:** `process(ctx: ProcessorContext, entries: list[ProcessorEntry]) -> list[str]`
- **Concurrencia:** Barrera de sincronización global. Detiene la ejecución en hilos hasta que todas las muestras activas alcanzan esta etapa.
- **Función:** Devuelve una lista ordenada de cadenas `sample_id` que define qué muestras sobreviven. Cualquier identificador ausente de esa lista queda marcado permanentemente como `SampleStatus.FILTERED`.

### El Contrato de Salida

Haga lo que haga un procesador, registra siempre las mismas tres cosas: `data`, un diccionario arbitrario con espacio de nombres propio; `artifacts`, una asociación de etiqueta a ruta de archivo relativa; y un estado. Ese contrato es deliberadamente ajeno a cualquier dominio, y es sobre lo que se construye todo lo que hay aguas abajo del motor.

El [informe]({{ '/es/reference/cli.html' | relative_url }}) es la consecuencia más clara. Es una proyección del estado persistido, no una etapa de la canalización: lee los mismos `data` y `artifacts` que podría haber leído cualquier procesador, y por eso una caza de controladores, una auditoría de código fuente o cualquier otra cosa se renderizan sin que el código del informe sepa qué es ninguna de ellas. La canalización aporta únicamente el vocabulario, y eso es un [bloque de YAML]({{ '/es/reference/pipeline-yaml.html' | relative_url }}), no código.

Como el informe no contiene nada que no esté en el directorio de la ejecución, puede generarse mientras la ejecución avanza, reconstruirse después de borrarlo y volver a construirse para una ejecución que terminó hace semanas. Esa misma propiedad es la que hace intercambiable la capa de LLM: el backend se selecciona a partir de la cadena `model` de la canalización, y ningún procesador, etapa ni archivo de estado sabe cuál de ellos respondió.
