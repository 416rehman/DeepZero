---
layout: default
title: Persistencia de Estado
order: 1
---

## Subsistema de Persistencia

La integridad de los datos la gestiona el `StateStore` (definido en `engine/state.py`). Las operaciones que se ejecutan contra el sistema de archivos están fuertemente protegidas contra daños, incluso frente a SIGKILL o a una interrupción a nivel del sistema operativo, mediante reemplazos atómicos estrictos.

<div class="architecture-diagram" style="margin: 3rem 0;">
    <svg viewBox="0 0 800 250" style="width: 100%; height: auto; max-width: 800px;" xmlns="http://www.w3.org/2000/svg">
        <defs>
            <pattern id="isoGridState" width="40" height="23.094" patternUnits="userSpaceOnUse" patternTransform="scale(1)">
                <path d="M 40 0 L 0 23.094 M 0 0 L 40 23.094 M 20 23.094 L 20 0" fill="none" stroke="var(--border)" stroke-width="0.5"/>
            </pattern>
        </defs>

        <rect width="100%" height="100%" fill="url(#isoGridState)" opacity="0.3"/>
        
        <!-- Memory Node -->
        <g transform="translate(100, 120)">
            <rect x="0" y="-40" width="120" height="80" fill="var(--bg-primary)" stroke="var(--text-primary)" stroke-width="2" rx="8"/>
            <text x="60" y="-5" font-family="JetBrains Mono, monospace" font-size="14" font-weight="bold" text-anchor="middle" fill="var(--text-primary)">Memoria</text>
            <text x="60" y="15" font-family="Inter, sans-serif" font-size="12" text-anchor="middle" fill="var(--text-tertiary)">SampleState</text>
        </g>

        <!-- Path to Temp -->
        <path d="M 220 120 L 320 120" fill="none" stroke="var(--text-tertiary)" stroke-width="2" stroke-dasharray="6 6"/>
        <text x="270" y="110" font-family="Inter, sans-serif" font-size="12" text-anchor="middle" fill="var(--text-secondary)">Serializar</text>
        
        <!-- Temp Node -->
        <g transform="translate(320, 120)">
            <rect x="0" y="-40" width="140" height="80" fill="var(--bg-secondary)" stroke="var(--border)" stroke-width="2" stroke-dasharray="4 4" rx="8"/>
            <text x="70" y="-5" font-family="JetBrains Mono, monospace" font-size="14" font-weight="bold" text-anchor="middle" fill="var(--text-secondary)">state.json.tmp</text>
            <text x="70" y="15" font-family="Inter, sans-serif" font-size="12" text-anchor="middle" fill="var(--text-tertiary)">Búfer</text>
        </g>
        
        <!-- Path to Final -->
        <path d="M 460 120 L 580 120" fill="none" stroke="var(--accent)" stroke-width="3"/>
        <circle cx="0" cy="0" r="5" fill="var(--accent)">
            <animateMotion path="M 460 120 L 580 120" dur="1.5s" repeatCount="indefinite" />
        </circle>
        <text x="520" y="110" font-family="Inter, sans-serif" font-size="12" font-weight="bold" text-anchor="middle" fill="var(--accent)">os.replace</text>
        <text x="520" y="140" font-family="Inter, sans-serif" font-size="10" text-anchor="middle" fill="var(--text-tertiary)">Reemplazo Atómico</text>
        
        <!-- Final Node -->
        <g transform="translate(580, 120)">
            <rect x="-10" y="-30" width="120" height="80" fill="var(--bg-primary)" stroke="var(--border)" stroke-width="1" rx="4"/>
            <rect x="-5" y="-35" width="120" height="80" fill="var(--bg-primary)" stroke="var(--border)" stroke-width="1" rx="4"/>
            <rect x="0" y="-40" width="120" height="80" fill="var(--bg-primary)" stroke="var(--text-primary)" stroke-width="2" rx="4"/>
            <text x="60" y="-5" font-family="JetBrains Mono, monospace" font-size="14" font-weight="bold" text-anchor="middle" fill="var(--text-primary)">state.json</text>
            <text x="60" y="15" font-family="Inter, sans-serif" font-size="12" text-anchor="middle" fill="var(--text-tertiary)">Persistente</text>
        </g>
    </svg>
</div>

### Archivos de Reemplazo Atómico (`atomic_replace`)

En lugar de escribir directamente sobre los artefactos esperados (por ejemplo, `state.json`), la capa de persistencia dirige las serializaciones a búferes `.tmp` intermedios. Una vez completada la serialización, una operación `os.replace` sobrescribe de forma atómica el inodo de destino. Un mecanismo de reintento con espera progresiva intercepta activamente los bloqueos `PermissionError` que provocan las heurísticas del EDR o el antivirus del host al analizar binarios recién creados.

### Versionado del Esquema

Todos los objetos de estado llevan una etiqueta interna `STATE_VERSION`. Si el motor detecta una desviación de esquema al deserializar (por ejemplo, leer un JSON v1 bajo un tiempo de ejecución v2), marca explícitamente el objeto de estado como obsoleto en lugar de provocar errores de mutación impredecibles.

### Jerarquía del Espacio de Trabajo

```text
work/<pipeline_name>/<corpus_key>/
├── run.json             # `RunState` serializado: métricas de ejecución y metadatos de la canalización
├── pipeline.yaml        # Copia inmutable de la configuración YAML en el momento de la inicialización
├── run_manifest.json    # Panorámica agregada de todas las muestras (la usa la API de Starlette)
├── report/              # Informe HTML navegable, reconstruido a medida que llegan resultados
└── samples/
    └── <sample_id>/     # Espacio aislado
        ├── state.json   # `SampleState` serializado: registro completo de los mapas `StageOutput`
        ├── context.md   # Contexto de LLM sintetizado, generado por `engine/context.py`
        └── ...          # Artefactos específicos del procesador
```

### Aislamiento por Corpus

El segmento `<corpus_key>` es lo que mantiene separados dos destinos que pasan por una misma canalización. Se deriva del destino de la ejecución: su nombre base, más un resumen corto de la ruta absoluta resuelta, así que resulta a la vez legible e inequívoco. En Windows la ruta se normaliza antes a minúsculas, porque `C:\Drivers` y `c:\drivers` son el mismo corpus.

Sin ese segmento, apuntar la misma canalización a un segundo corpus se reanudaría sobre el almacén de muestras del primero: las muestras que ya no se correspondieran con nada en disco se tratarían como analizadas, y la ejecución informaría de resultados para un corpus que nunca recibió. Con él, cada corpus tiene su propio estado, su propio manifiesto y su propio informe, y cada uno se reanuda por su cuenta.

La misma ruta resuelta se corresponde siempre con la misma clave, así que al repetir una ejecución esta vuelve al punto donde lo dejó. Todo lo que hay bajo este directorio es derivado: `report/` en particular no contiene nada que no esté en el estado de la ejecución, y borrarlo cuesta una reconstrucción, no una ejecución.

### El Registro `history`

El diccionario `SampleState.history` asocia estrictamente los nombres de las etapas de procesamiento con instancias de `StageOutput`. Las estructuras de datos de salida quedan estrictamente aisladas y con espacio de nombres propio. Un procesador posterior que extraiga métricas de un map anterior consultará: `history["upstream_processor"].data.get("metric")` (consulte [Construcción de Procesadores Personalizados]({{ '/es/extensibility/building-custom.html' | relative_url }})).

Este espacio de nombres impide de forma permanente que colisionen campos entre técnicas de análisis heurístico divergentes.
