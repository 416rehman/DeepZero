---
layout: default
title: Procesadores integrados
order: 1
---

## Procesadores integrados

Se referencian por su nombre simple. Ejecute `deepzero list-processors` para verlos junto
con las clases que los implementan.

| Identificador | Tipo | Funcionalidad |
| ------------- | ---- | ------------- |
| `file_discovery` | Ingest | Recorrido recursivo del sistema de archivos y hash criptográfico. |
| `metadata_filter` | Map | Igualdad de campos mediante `require:`, umbrales numéricos mediante cualquier clave `min_<field>` / `max_<field>`, y deduplicación mediante `dedup_field`. Los campos se leen de los datos combinados de todas las etapas anteriores. |
| `hash_exclude` | Map | Exclusiones criptográficas mediante listas integradas o archivos planos, deduplicación dentro de la propia ejecución mediante `dedup`, y el campo del que se lee el hash mediante `hash_field` (`sha256` si no se indica). |
| `generic_llm` | Map | Renderizado de plantillas Jinja2, invocación de LLM y análisis de respuestas. |
| `generic_command` | Map | Ejecución arbitraria de comandos shell con sustitución de variables. |
| `top_k` | Reduce | Trunca el conjunto de muestras en función de valores escalares numéricos. |
| `sort` | Reduce | Reordenación determinista de muestras sin reducción del conjunto de datos. |

Un umbral `min_<field>` lee como cero un campo que ninguna etapa anterior registró, y
filtra la muestra. Esa es la respuesta correcta para un campo genuinamente ausente y la
equivocada para un campo al que le cambiaron el nombre, así que una etapa que de pronto
filtra un corpus entero en segundos merece contrastarse con los nombres que sus etapas
anteriores proporcionan realmente.

## Procesadores externos incluidos

Viven en `processors/` y se referencian por ruta, así que se leen como procesadores
externos corrientes y no como integrados privilegiados. Son los que utilizan las
[canalizaciones incluidas]({{ '/es/reference/included-pipeline.html' | relative_url }}).
`ghidra_decompile`, `git_ingest` y `loldrivers_filter` declaran las claves que aceptan como
una dataclass `Config`, así que la lista de esas claves es el propio código fuente y una clave
mal escrita en una canalización se señala en vez de ignorarse. `pe_ingest` y `semgrep_scanner`
leen el diccionario de configuración en bruto, donde una clave mal escrita ni se lee ni se
señala. Cada uno lleva un README a su lado que describe lo que emite y los comportamientos que
sorprenderían a quien lo lea.

| Ruta | Tipo | Funcionalidad |
| ---- | ---- | ------------- |
| `pe_ingest/pe_ingest.py` | Ingest | Descubre archivos PE, analiza sus encabezados y extrae los metadatos del controlador. |
| `git_ingest/git_ingest.py` | Ingest | Convierte repositorios git en muestras, a partir de un directorio de copias locales o de un manifiesto de URL. |
| `loldrivers_filter/loldrivers_filter.py` | Map | Excluye las muestras cuyo SHA-256 coincide con una entrada conocida de la base de datos de loldrivers.io. |
| `ghidra_decompile/ghidra_decompile.py` | Map | Descompilación de Ghidra sin interfaz gráfica, con un post-script configurable. |
| `semgrep_scanner/semgrep_scanner.py` | BulkMap | Análisis semgrep por lotes sobre las muestras activas. |

### `git_ingest`

Una muestra es un repositorio, y su `source_path` es la raíz de la copia local, que es
adonde quiere apuntar un escáner de código fuente. El destino de la CLI es siempre una
ruta real, así que ambas formas de entrada mantienen funcionando la reanudación y el
aislamiento por corpus: un directorio se lee como contenedor de copias locales y no se
descarga nada, mientras que un archivo se lee como manifiesto y cada entrada se clona.

`sample_id` se deriva de la identidad del repositorio y no de una ruta, así que el mismo
repositorio alcanzado a través de un manifiesto y a través de un directorio es la misma
muestra, y al volver a ejecutar conserva sus resultados.

### `semgrep_scanner`

| Campo | Predeterminado | Significado |
|-------|----------------|-------------|
| `rules_dir` | ninguno, obligatorio | Directorio de reglas de semgrep que cargar. |
| `target_dir` | `decompiled` | Subdirectorio del propio directorio de trabajo de la muestra que se va a analizar. Póngalo en `""` y se analizará la ruta de la muestra misma. |
| `extensions` | `.c`, `.h`, `.cpp`, `.py` | Qué archivos se entregan a semgrep. Se añade el punto inicial si falta, y se acepta una sola cadena para una lista de un elemento. |
| `batch_size` | `200` | Muestras por invocación de semgrep. `0` o menos pone toda la etapa en una única pasada. |
| `timeout` | `300` | Segundos concedidos al proceso de semgrep de un lote. |
| `min_findings` | `0` | Filtra una muestra con menos hallazgos que este número. Con `0` no se filtra nada. |

`target_dir` y `extensions` son los que permiten que un único escáner sirva a las dos
canalizaciones incluidas. Los valores predeterminados encajan con una canalización que
descompila primero y escribe C junto a cada muestra. Una canalización cuyas muestras ya son
código fuente, por ejemplo una copia local de un repositorio, pone `target_dir: ""` y amplía
`extensions` a lo que realmente haya ingerido.

`rules_dir` se resuelve primero respecto al directorio de trabajo y después respecto al
directorio de la canalización, y tanto `validate()` como el propio análisis lo resuelven de
la misma manera, porque resolverlos de forma distinta permitió una vez que la validación
pasara mientras el análisis se ejecutaba sin ninguna regla cargada. Un `rules_dir` que no
existe cuando la etapa se ejecuta hace fallar todas sus muestras en lugar de analizar sin
nada cargado e informar de un corpus limpio.

#### Un findings.json ya presente en disco se adopta, no se vuelve a analizar

Este es el comportamiento que más sorprende. Antes de analizar nada, el procesador busca `findings.json` en el
directorio propio de cada muestra. Si está, si el motor informa de que el resultado en caché
sigue siendo válido y si el archivo se puede analizar, esos hallazgos se toman como
resultado, la muestra se registra con `findings_cached: true` y a semgrep no se le pregunta
por ella. La validez no le toca juzgarla al procesador: el motor compara la huella actual de
esta etapa con aquella bajo la que se registró el resultado anterior, así que es lo único que
sabe si el archivo sigue describiendo las reglas y la configuración vigentes. Si el archivo es
ilegible, la muestra se vuelve a analizar.

Eso es lo que impide que una ejecución interrumpida repita los lotes que ya había terminado.
Editar las reglas invalida la caché por sí solo: `rules_dir` es un valor de configuración que
nombra un directorio, así que los propios archivos de reglas entran en la huella, y un
resultado registrado bajo una huella distinta queda obsoleto en lugar de adoptarse.
`deepzero run --redo <etapa>` sigue siendo la forma de forzar un nuevo análisis para lo que la
huella no alcanza a ver, y funciona porque `findings.json` se registra como artefacto en todos
los caminos que lo escriben, incluido el camino filtrado, de modo que `--redo` puede encontrar
el archivo y borrarlo. Un resultado
registrado antes de que existieran las huellas lleva un resumen vacío, y esos se dan por
buenos tal cual: descartar un corpus porque es anterior a la funcionalidad sería la peor
apuesta.

Un resultado adoptado lleva únicamente `finding_count` y `findings_cached`. `files_submitted`
y `files_scanned` salen de la propia ejecución de semgrep, así que una muestra que esta vez
no se analizó no tiene ninguno de los dos.

#### Los lotes, y los fallos que conviene conocer

Las muestras se analizan por lotes en lugar de en una sola pasada, de modo que un lote que
agota el tiempo o vuelve ilegible cuesta solo sus propias muestras en vez de descartar un
corpus entero cuando el trabajo ya está hecho. Un lote que supera `timeout` registra como
fallidas todas las muestras que contiene.

`extensions` y las reglas tienen que estar de acuerdo. Un archivo cuya extensión no figure en
la lista nunca se entrega a semgrep, por muchas reglas que hubieran coincidido con él, y ese
fallo es silencioso: el análisis informa de cero hallazgos, algo indistinguible de un árbol
limpio. Por eso la canalización de auditoría de código fuente registra `files_scanned` junto
a `finding_count`.

Otros dos resultados se rechazan en lugar de informarse como limpios, porque los dos se ven
por fuera exactamente igual que un corpus limpio: que semgrep vuelva con errores de carga y
ningún resultado, y que semgrep no enumere ninguno de los archivos que se le entregaron. Los
dos hacen fallar el lote y lo dicen.

Una muestra cuyo `target_dir` no está en disco falla por su cuenta, antes de que se construya
ningún lote, y el mensaje pregunta si la etapa que produce ese directorio se ejecuta antes que
esta, que suele ser la respuesta.

`min_findings` filtra una muestra en esta etapa en lugar de hacerla fallar, así que sale de la
ejecución con un motivo registrado y con su `findings.json` todavía adjunto. Las dos
canalizaciones incluidas ponen `min_findings: 1`, que es lo que impide que una muestra en la
que no se señaló nada cueste una llamada al modelo más adelante.
