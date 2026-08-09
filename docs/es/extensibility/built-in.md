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
| `hash_exclude` | Map | Exclusiones criptográficas mediante listas integradas o archivos planos. |
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
[canalizaciones incluidas]({{ '/es/reference/included-pipeline.html' | relative_url }}), y
cada uno lleva un README junto a su código fuente con su configuración completa.

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

Dos valores de configuración deciden qué se analiza, y son los que permiten que un único
escáner sirva a las dos canalizaciones incluidas:

| Campo | Predeterminado | Significado |
|-------|----------------|-------------|
| `target_dir` | `decompiled` | Subdirectorio del propio directorio de trabajo de la muestra que se va a analizar. Póngalo en `""` y se analizará la ruta de la muestra misma. |
| `extensions` | `.c`, `.h`, `.cpp`, `.py` | Qué archivos se entregan a semgrep. |

El valor predeterminado encaja con una canalización que descompila primero y escribe C
junto a cada muestra. Una canalización cuyas muestras ya son código fuente, por ejemplo
una copia local de un repositorio, pone `target_dir: ""` y amplía `extensions` a lo que
realmente haya ingerido.

`extensions` y las reglas tienen que estar de acuerdo. Un archivo cuya extensión no
figure en la lista nunca se entrega a semgrep, por muchas reglas que hubieran coincidido
con él, y ese fallo es silencioso: el análisis informa de cero hallazgos, algo
indistinguible de un árbol limpio. Por eso la canalización de auditoría de código fuente
registra `files_scanned` junto a `finding_count`.

Las muestras se analizan por lotes (`batch_size`, 200 de forma predeterminada) en lugar
de en una sola pasada, de modo que un lote que agota el tiempo o vuelve ilegible cuesta
solo sus propias muestras en vez de descartar un corpus entero cuando el trabajo ya está
hecho.
