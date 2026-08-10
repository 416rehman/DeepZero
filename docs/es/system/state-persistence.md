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
            <text x="70" y="-5" font-family="JetBrains Mono, monospace" font-size="14" font-weight="bold" text-anchor="middle" fill="var(--text-secondary)">state.tmp</text>
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

En lugar de escribir directamente sobre los artefactos esperados (por ejemplo, `state.json`), la capa de persistencia dirige las serializaciones a búferes `.tmp` intermedios. El búfer toma el nombre del destino con su extensión sustituida en lugar de ampliada, así que `state.json` se prepara como `state.tmp`. Una vez completada la serialización, una operación `os.replace` sobrescribe de forma atómica el inodo de destino. Un mecanismo de reintento con espera progresiva intercepta activamente los bloqueos `PermissionError` que provocan las heurísticas del EDR o el antivirus del host al analizar binarios recién creados.

### Versionado del Esquema

El estado de las muestras es la parte que está a la vez etiquetada y controlada. `state.json` se
escribe con un campo `_version` que lleva el `STATE_VERSION` interno, y al cargar se rechaza
todo lo que sea anterior: leer un JSON v1 bajo un tiempo de ejecución v2 no devuelve nada en
absoluto, en lugar de provocar errores de mutación impredecibles al interpretar un registro
bajo un esquema que ya no lo describe.

Los otros dos archivos no están controlados. `run_manifest.json` lleva ese mismo campo
`_version`, pero nadie lo vuelve a leer, porque el manifiesto es un compendio derivado que se
reescribe a partir de las muestras cada vez que estas se guardan. `run.json` no está ni
etiquetado ni comprobado: se carga filtrando el JSON por los nombres de campo del propio
`RunState` y descartando cualquier cosa que no se reconozca, así que un registro escrito por una
versión anterior se carga con los campos que tenga y el resto en sus valores predeterminados.

### Jerarquía del Espacio de Trabajo

```text
work/<pipeline_name>/<corpus_key>/
├── run.json             # `RunState` serializado: métricas de ejecución, metadatos de la
│                        #   canalización, la conclusión sobre el corpus y el registro de
│                        #   si la ejecución sigue viva
├── pipeline.yaml        # Copia inmutable de la configuración YAML en el momento de la inicialización
├── run_manifest.json    # Panorámica agregada de todas las muestras, que leen `status` e `interactive`
├── report/              # Informe HTML navegable, reconstruido a medida que llegan resultados
└── samples/
    └── <sample_id>/     # Espacio aislado
        ├── state.json   # `SampleState` serializado: registro completo de los mapas `StageOutput`
        ├── context.md   # Contexto de LLM sintetizado, generado por `engine/context.py`
        └── ...          # Artefactos específicos del procesador
```

Dos partes de `RunState` merecen nombrarse más allá de las métricas. `conclusion` guarda un
hallazgo sobre el corpus en lugar de sobre una muestra concreta: qué modelo hay detrás de un
endpoint, cuántos fallos distintos representa un montón de caídas, si un alcance está bien
configurado. Lo escribe `ctx.conclude(...)` desde una etapa que ve todas las muestras, y queda
vacío para las muchas canalizaciones cuyas respuestas son todas por muestra. Junto a él,
`host`, `pid`, `pid_token` y `heartbeat_at` registran quién está escribiendo la ejecución: un
estado `running` no es más que una afirmación hasta que se puede comprobar el proceso que hay
detrás, y una ejecución que muere de golpe nunca llega a retirar esa afirmación por su cuenta,
así que esos cuatro campos son los que permiten a otro proceso distinguir una ejecución viva de
una abandonada.

### Aislamiento por Corpus

El segmento `<corpus_key>` es lo que mantiene separados dos destinos que pasan por una misma canalización. Se deriva del destino de la ejecución: su nombre base, más un resumen corto de la ruta absoluta resuelta, así que resulta a la vez legible e inequívoco. En Windows la ruta se normaliza antes a minúsculas, porque `C:\Drivers` y `c:\drivers` son el mismo corpus.

Sin ese segmento, apuntar la misma canalización a un segundo corpus se reanudaría sobre el almacén de muestras del primero: las muestras que ya no se correspondieran con nada en disco se tratarían como analizadas, y la ejecución informaría de resultados para un corpus que nunca recibió. Con él, cada corpus tiene su propio estado, su propio manifiesto y su propio informe, y cada uno se reanuda por su cuenta.

La misma ruta resuelta se corresponde siempre con la misma clave, así que al repetir una ejecución esta vuelve al punto donde lo dejó. Casi todo lo que hay bajo este directorio es derivado, y borrar `report/` normalmente cuesta una reconstrucción, no una ejecución.

Hay una excepción, y no se puede recuperar. `report/marks.json` guarda las marcas de revisión:
para cada muestra, si alguien la revisó y la dio por buena o no, más una nota. Eso es lo que ha
comprobado quien lee, algo que ninguna etapa puede saber, así que no existe en ninguna parte del
estado de la ejecución. Se guarda junto al informe precisamente para que se renderice para
cualquiera que lo abra, en lugar de quedarse varado en el navegador de una sola persona, y se
vuelve a leer en cada reconstrucción. Borrar `report/` lo destruye, y también lo hace
`run --clean`, que elimina el directorio del corpus entero antes de empezar.

### El Registro `history`

El diccionario `SampleState.history` asocia estrictamente los nombres de las etapas de procesamiento con instancias de `StageOutput`. Las estructuras de datos de salida quedan estrictamente aisladas y con espacio de nombres propio. Un procesador posterior que extraiga métricas de un map anterior consultará: `history["upstream_processor"].data.get("metric")` (consulte [Construcción de Procesadores Personalizados]({{ '/es/extensibility/building-custom.html' | relative_url }})).

Este espacio de nombres impide de forma permanente que colisionen campos entre técnicas de análisis heurístico divergentes.

### Huellas de las Entradas de una Etapa

Cada `StageOutput` lleva además un `input_digest`: una huella de todo lo que decide qué produce
esa etapa, es decir, su procesador, su configuración y cualquier archivo al que esa
configuración apunte, como un prompt, un conjunto de reglas o un script de análisis. Se registra
cuando la etapa termina y se compara cuando una ejecución reanudada pregunta si esa etapa ya
está hecha.

Cuando ambos resúmenes están presentes y no coinciden, el resultado guardado describe unas
entradas que la canalización ya no tiene, así que cuenta como obsoleto en lugar de como hecho y
la etapa se vuelve a ejecutar. Eso es lo que permite a una ejecución reanudada averiguar por su
cuenta qué resultados siguen siendo válidos, en lugar de que quien lee tenga que acordarse de
qué editó. Cuando cualquiera de los dos resúmenes está vacío, la pregunta no se puede hacer, y
una pregunta sin respuesta posible no es motivo para descartar un trabajo que puede haber
costado horas, así que los resultados escritos antes de que se registrara el resumen se dan por
buenos en lugar de rehacerse.

El corpus en sí no forma parte de la huella. Ya está indexado por el directorio de trabajo, y
leer todas las muestras para decidir si hay que leer todas las muestras costaría más que la
propia etapa que la comprobación protege.
