---
layout: default
title: YAML de Canalización
order: 2
---

## Configuración de Canalizaciones

Una **Canalización (Pipeline)** en DeepZero es el gráfico de ejecución declarativa que define un flujo de transformación de datos continuo y resistente a fallos. Convierte un conjunto de datos físico y en bruto en un conjunto analítico con señal alta.

El esquema está estrictamente definido en YAML. DeepZero resuelve la configuración de forma dinámica y admite la expansión de variables propia del shell (por ejemplo, `${VAR:-default}`).

### Esquema de Configuración

```yaml
name: my_pipeline
description: A standard vulnerability hunting pipeline
version: "1.0"
model: openai/gpt-4o  # el prefijo selecciona el backend, ver más abajo

settings:
  work_dir: work
  max_workers: 8  # Límite global de hilos del ThreadPoolExecutor

stages:
  # Etapa 1: DEBE ser un IngestProcessor
  - name: discover
    processor: file_discovery
    config:
      extensions: ["*"]

  # Etapa 2: Filtro síncrono
  - name: filter
    processor: metadata_filter
    config:
      require:
        is_executable: true

  # Etapa 3: Procesamiento Map de alta latencia
  - name: decompile
    processor: ghidra_decompile/ghidra_decompile.py
    parallel: 4           # Limita la concurrencia a 4 JVM de Ghidra simultáneas
    timeout: 300          # Presupuesto por muestra: la etapa deja de esperar a los 300 segundos
    on_failure: skip      # Trata las excepciones en silencio en lugar de abortar (skip, retry, abort)
    max_retries: 2        # Número de reintentos permitidos
    config:
      ghidra_install_dir: ${GHIDRA_INSTALL_DIR}
```

### Argumentos de Etapa

Cada etapa definida bajo la lista `stages:` acepta los siguientes atributos:

| Campo | Tipo | Predeterminado | Descripción |
|-------|------|----------------|-------------|
| `name` | string | `stage_N` | Nombre único para la etapa dentro de la canalización |
| `processor` | string | requerido | El registro de referencia al procesador (ver más abajo) |
| `config` | dict | `{}` | Configuración inyectada al procesador |
| `parallel` | int | `4` | Concurrencia para procesadores Map. `0` se ajusta automáticamente, dentro de los topes de más abajo |
| `timeout` | int | `0` | Presupuesto por muestra, en segundos, para etapas Map (0 = sin presupuesto) |
| `on_failure` | string | `skip` | Define el comportamiento ante fallos: `skip`, `retry` o `abort` |
| `max_retries` | int | `0` | Número de reintentos cuando `on_failure: retry` |
| `limit` | int | `0` | Va dentro de `config` y lo lee el motor: recorta el corpus superviviente después de esta etapa (0 = conservarlo todo) |

#### `parallel`

`parallel: 0` significa automático, no ilimitado. El ejecutor parte de `os.cpu_count()` y lo
baja dos veces: hasta el techo que el procesador declara en `max_parallelism()` y hasta el
ajuste `max_workers` de la canalización, el que sea menor de los dos. Un procesador que lanza
una JVM o una herramienta externa por muestra declara ese techo precisamente para que un
`parallel: 0` predeterminado no pueda agotar la máquina, y la ejecución deja constancia de qué
tope aplicó. Un `parallel: N` explícito se respeta tal como está escrito y no lo acota ninguno
de los dos.

#### `timeout`

`timeout` es el presupuesto que recibe una muestra en una etapa Map. Cuando se agota, la etapa
deja de esperar, registra esa muestra como que agotó el tiempo y pasa a la siguiente.

Lo que no hace es matar nada. Nada en Python puede detener un hilo que ya está en marcha, así
que el hilo de trabajo del procesador se abandona en lugar de terminarse: un proceso externo
que hubiera lanzado sigue corriendo hasta que acaba por su cuenta, y la memoria que retenga
ese hilo sigue retenida hasta que regrese. El presupuesto acota cuánto espera la *etapa*, no
cuánto dura el trabajo. Un procesador que invoque una herramienta externa debería pasarle
también un límite a esa herramienta, que es lo que hace `semgrep_scanner` con su propia clave
de configuración `timeout`.

Solo cubre las etapas Map. Las etapas reduce y bulk_map son una única invocación para todo el
corpus en lugar de una por muestra, y ninguna de las dos se ejecuta bajo este presupuesto.

Agotar el tiempo no es un fallo, así que `on_failure: retry` no lo reintenta, y una ejecución
reanudada lo deja estar porque el presupuesto que se quedó corto lo sigue estando. Pedir otro
intento es para lo que sirve [`--retry-timeouts`]({{ '/es/reference/cli.html' | relative_url }}).

#### `limit`

`limit` va dentro del bloque `config` de una etapa, pero quien lo lee es el motor y no el
procesador, así que puede ponerse en cualquier etapa con independencia de lo que ese
procesador acepte, y un procesador que declare un `Config` tipado no avisará de que la clave
le resulta desconocida.

Una vez terminada la etapa, toda muestra que siga activa más allá de las primeras `limit`
queda marcada como filtrada en esa etapa y no participa en el resto de la ejecución. El
recuento es sobre el corpus superviviente entero, no sobre las muestras que tocó esa única
etapa.

El orden es aquel en el que la ejecución lleva el corpus en ese momento, y eso es lo que hace
que `limit` merezca la pena en una etapa reduce, o en la siguiente. Una etapa reduce devuelve
a sus supervivientes ordenados, el ejecutor adopta esa ordenación antes de que ocurra el
recorte, y `limit` conserva entonces los mejor situados en lugar de un trozo arbitrario. En
una etapa sin ninguna ordenación detrás, conserva las muestras que casualmente vayan primero.

### Campos de Nivel Superior

| Campo | Tipo | Predeterminado | Descripción |
|-------|------|----------------|-------------|
| `name` | string | el nombre del directorio de la canalización | Nombra la canalización, y nombra su directorio de trabajo |
| `description` | string | `""` | Texto libre |
| `version` | string | ninguno | Metadatos de formato libre que el motor nunca lee. Ambas canalizaciones incluidas declaran uno por convención, para quien las mantenga |
| `model` | string | `""` | Modelo para cada etapa de LLM. Una canalización sin etapas de LLM no necesita ninguno; `deepzero validate` avisa cuando falta |
| `settings` | dict | `{}` | `work_dir` (predeterminado `work`) y `max_workers` (predeterminado `min(4, cpu_count)`) |
| `knowledge` | dict | `{}` | Valores arbitrarios a nivel de canalización, legibles por cualquier procesador mediante `ctx.get_knowledge(key)` |
| `report` | dict | `{}` | Cómo presenta `deepzero report` los resultados de esta canalización, ver más abajo |
| `stages` | list | requerido | Al menos una, y la primera debe ser un procesador de ingestión |

`work_dir` es la raíz, no el directorio de la ejecución. Una ejecución aterriza en `<work_dir>/<nombre de la canalización>/<clave de corpus>/`, donde la clave de corpus se deriva de la ruta de destino, así que dos corpus a través de una misma canalización nunca colisionan y cada uno se reanuda por su cuenta. Consulte la [Referencia de CLI]({{ '/es/reference/cli.html' | relative_url }}).

### Elección del Modelo

La parte de `model` anterior a la primera `/` es un prefijo, y selecciona el backend:

| Cadena de modelo | Backend |
|--------------|---------|
| `claude-code`, `claude-code/<model-id>` | La CLI de Claude Code instalada localmente, con la sesión ya iniciada |
| cualquier otra, p. ej. `openai/gpt-4o`, `gemini/...`, `gpt-4o` | LiteLLM, que cubre todos los endpoints con clave API que admite |

`claude-code` ejecuta una canalización contra una suscripción de Claude Code sin ninguna clave API. DeepZero nunca maneja credenciales para ello: invoca la CLI en la que usted ya inició sesión y hereda la autenticación que tenga ese binario. La parte posterior a la barra se pasa tal cual como modelo, así que `claude-code/claude-opus-5` elige un modelo concreto y `claude-code` a secas deja la CLI en el suyo predeterminado. Ambas canalizaciones incluidas declaran un modelo `claude-code`, y `-m` lo sustituye para una ejecución.

Como estas llamadas transportan contenido no confiable, salida del descompilador y código fuente traído de repositorios ajenos, la CLI se invoca con sus herramientas y sus servidores MCP denegados. Una compleción no necesita ninguno, y dejarlos habilitados permitiría que un prompt inyectado alcanzara un shell.

El registro está abierto: `register_backend()` añade un prefijo sin parchear DeepZero, y no hay que cambiar nada en el proveedor, la canalización ni las etapas para incorporar uno. Cualquier prefijo que ningún backend reclame recae en LiteLLM.

Sea cual sea el backend seleccionado, se le pregunta si puede funcionar antes de que una etapa lo necesite: `deepzero validate` comprueba la clave API para un modelo de LiteLLM y la presencia del binario para la CLI de un agente, y [`deepzero run --preflight`]({{ '/es/reference/cli.html' | relative_url }}) va más allá y confirma que la sesión de la CLI está iniciada.

### Lógica de Resolución (`engine/registry.py`)

La forma del valor de `processor:` decide cómo se resuelve, de modo que una referencia nunca resulta ambigua entre un archivo externo y un nombre integrado:

| Referencia | Se resuelve como |
|-----------|-------------|
| Contiene `/` o `\`, p. ej. `ghidra_decompile/ghidra_decompile.py` | Un archivo bajo una de las raíces de procesadores que se enumeran más abajo. Se usa la primera subclase de Processor que contenga, ignorando las propias clases base |
| Lo mismo, con `:NombreDeClase` añadido | Esa clase concreta en ese archivo, que es lo que necesita un archivo que define más de un procesador |
| Un nombre simple, p. ej. `metadata_filter` | El registro interno, poblado en `stages/__init__.py` |
| Un nombre simple que contiene `:`, p. ej. `my.python.module:MyClass` | Un módulo importable en `sys.path`, y una clase dentro de él |

Cualquier otra cosa es un error que enumera los integrados, en lugar de un fallo más adelante durante la ejecución.

Una referencia que lleva un separador se busca bajo cinco raíces, en este orden, y gana la
primera que exista:

1. cada ruta de `$DEEPZERO_PROCESSORS`, separadas como esta plataforma separe las entradas de
   `PATH`: con `;` en Windows y con `:` en el resto
2. `processors/` en el directorio de trabajo
3. `processors/` junto al propio YAML de la canalización
4. `processors/` en el directorio padre del de la canalización
5. el propio directorio de la canalización, para una canalización que mantenga un procesador
   junto a su YAML en lugar de en un subdirectorio

El directorio de trabajo se busca antes que el de la canalización, y por eso las canalizaciones
incluidas se resuelven desde la raíz del repositorio. No es la única raíz, sin embargo: una
canalización guardada en cualquier sitio puede llevar sus propios procesadores al lado y
ejecutarse desde cualquier directorio, sin que el motor dicte desde dónde toque lanzar el
comando.

`$DEEPZERO_PROCESSORS` se busca antes que cualquier otra raíz, y eso es lo que la convierte en
una biblioteca compartida de procesadores: un nombre encontrado ahí eclipsa ese mismo nombre
bajo el `processors/` del directorio de trabajo o junto a la canalización. Una referencia que no
coincide con ninguna raíz falla enumerando todas las rutas que intentó, así que una errata se
lee como una errata y no como un archivo ausente.

### Expansión Dinámica

Antes de que la validación del esquema vincule los procesadores, DeepZero recorre todo el árbol DOM del YAML evaluando coincidencias de la expresión regular `\$\{([^}]+)\}`. Las variables de entorno dictan la configuración de ejecución resuelta. Esto evita explícitamente incrustar claves API o directorios de instalación en los archivos `.yaml` que se versionan.

### Valores del Prompt

Una etapa cuyo `config` lleva un `prompt` renderiza ese archivo como plantilla Jinja. El valor puede ser una ruta o un nombre de archivo situado junto a la canalización; en ambos casos el archivo se carga, nunca se usa como el texto del prompt en sí.

Todo prompt puede usar estos valores:

| Valor | Tipo | Descripción |
|-------|------|-------------|
| `sample_name` | string | El nombre de archivo de la muestra tal como lo registró la etapa de ingestión |
| `sample_path` | string | Ruta absoluta a la muestra en disco |
| `history` | dict | `{stage_name: data}` para cada etapa que ya se haya ejecutado |
| `config` | dict | El propio bloque `config` de esta etapa |

Más allá de esos, un prompt puede usar lo que registraron las etapas **anteriores a él**. Cada procesador declara esos nombres en su atributo `provides`, y son de dos clases:

- **Claves de datos**: cualquier cosa que el procesador ponga en `data`, como `device_name` o `finding_count`. Disponible directamente bajo ese nombre, y también dentro de `history`.
- **Artefactos**: un archivo que el procesador escribió, alcanzable por su ruta con los separadores y la extensión incorporados al nombre. `decompiled/dispatch_ioctl.c` pasa a ser `decompiled_dispatch_ioctl_c`. El JSON se analiza como objeto, y una larga lista de sufijos de código, marcado y texto plano llega como texto; una etapa que necesite otro conjunto lo declara en `text_extensions`, dentro de su propio `config`, que sustituye esa lista en lugar de ampliarla. Nada más se expone. El texto que excede el presupuesto de contexto, `max_context_tokens` por cuatro caracteres, se trunca y lo indica, y un archivo JSON mayor que ese presupuesto se omite con una advertencia en lugar de analizarse.

Un valor solo está disponible para las etapas *posteriores* a la que lo registra, así que un prompt no puede alcanzar la salida de su propia etapa.

Para ver qué ofrece una canalización concreta, ejecute:

```bash
deepzero validate <pipeline>
```

Un prompt que nombre algo que ninguna etapa anterior produce se informa como error, enumerando lo que sí estaba disponible. El renderizado en tiempo de ejecución es igual de estricto en esto, así que una etapa que llegue ahí de todos modos falla en esa muestra en lugar de dejar pasar el prompt. Esto importa porque, de lo contrario, un nombre desconocido se renderizaría como nada: se le pediría al modelo que juzgara un contenido vacío, y el veredicto volvería seguro de sí mismo y sin significado.

### El Bloque report

`deepzero report` se construye sobre lo que el motor garantiza, que es lo mismo para toda canalización: cada etapa registra `data`, `artifacts` y un estado. Lo que cambia es el vocabulario. Una canalización de controladores de kernel, una auditoría de código fuente y una revisión de licencias producen las mismas formas de desenlace y las llaman cosas completamente distintas.

Así que las formas son fijas y las palabras se declaran:

```yaml
report:
  title: Source repository audit
  entity: repository
  entity_plural: repositories
  target_label: repository list
  classification_key: classification
  positive_when: [vulnerable]
  negative_when: [not exploitable]
  columns:
    - scan.finding_count
    - discover.primary_language
  findings_files: [findings.json]
```

Todos los campos son opcionales, y cada valor predeterminado reproduce el comportamiento que tenía una canalización antes de que el bloque existiera. Una canalización que no declara nada sigue obteniendo un informe utilizable.

| Campo | Tipo | Predeterminado | Descripción |
|-------|------|----------------|-------------|
| `title` | string | `<nombre de la canalización> results` | Encabezado de `index.html` |
| `entity` | string | `sample` | Cómo se llama un resultado en la interfaz |
| `entity_plural` | string | `entity` + `s` | Solo hace falta cuando añadir una s es incorrecto, p. ej. repository |
| `target_label` | string | `corpus` | Aquello contra lo que se apuntó la ejecución |
| `classification_key` | string | `classification` | La clave de `data` de la etapa que contiene la conclusión |
| `positive_when` | list | `vulnerab`, `exploitab`, `confirmed` | Valores que cuentan como lo que se está buscando |
| `negative_when` | list | `safe`, `not vulnerab`, `benign`, `clean` | Valores que cuentan como que no se encontró nada |
| `columns` | list | se eligen automáticamente | Valores `etapa.clave` que mostrar junto a cada resultado |
| `findings_files` | list | `findings.json` | Nombres de archivo dentro del directorio de una muestra de los que leer hallazgos |
| `lexicon` | dict | ver más abajo | Las palabras para los desenlaces |

`vulnerable_when` y `safe_when` se aceptan como los nombres antiguos de `positive_when` y `negative_when`, y significan exactamente lo mismo. `positive_when` gana si se indican ambos.

`target_label` se gana su sitio porque el valor predeterminado, "corpus", da por hecho un montón de archivos en disco. Una ejecución contra una aplicación en vivo tiene un alcance, y una ejecución sobre un conjunto de repositorios tiene la lista o el directorio de copias locales al que se apuntó. Llamar corpus a cualquiera de las dos se lee como un error en un informe que va a abrir otra persona.

Nombre lo que muestra la cabecera, que es el destino de la ejecución, y no aquello de lo que trata la ejecución. "Organización" es lo tentador y equivocado: se lee bien, y luego resulta que etiqueta la ruta de un manifiesto que puede enumerar repositorios pertenecientes a varias organizaciones.

#### Cómo se Compara un Veredicto

El valor registrado bajo `classification_key` se pasa a minúsculas y se contrasta primero con las subcadenas de `positive_when` y después con las de `negative_when`. Subcadenas, no valores exactos, de modo que `vulnerab` cubre "vulnerable" y "vulnerability".

Comprobar primero los positivos es lo que hace que merezca la pena sustituir los valores predeterminados. Una canalización cuyo veredicto negativo sea `[NOT EXPLOITABLE]` contiene `exploitab`, que es un positivo predeterminado, así que se contaría como acierto. Restringir `positive_when` a `[vulnerable]` es lo que hace la auditoría de código fuente incluida, y es lo primero que hay que revisar cuando los veredictos de una ejecución y los recuentos del informe no cuadran.

Un veredicto que no coincide con ninguna de las dos listas no se descarta en silencio. Aterriza en "Unclear verdict", que es una afirmación distinta de haber sido juzgado seguro.

#### Columnas

`columns` nombra valores `etapa.clave`, usando el nombre que tiene la etapa en esta canalización, y los coloca junto a cada resultado. Declare los que deciden qué leer a continuación: si un hallazgo puede llegar a ejercitarse, cuánto código se analizó realmente, qué revisión se juzgó. Cuando no se declara ninguno, el informe toma hasta seis claves numéricas o con nombre prometedor de entre lo que registró la ejecución.

No hace falta añadir nada al informe para esto. Una clave está disponible en cuanto un procesador la registra en `data` y la canalización la nombra aquí.

#### Hallazgos

`findings_files` nombra archivos dentro del directorio de cada muestra de los que leer hallazgos. También se recoge cualquier artefacto JSON cuyo contenido parezca una lista de hallazgos, así que un procesador que escriba bajo otro nombre aparece igualmente sin configuración alguna.

Un hallazgo puede además nombrar aquello de lo que es una instancia. El informe lee ese nombre de `finding_id`, y recae en `key` y después en `fingerprint`, y agrupa todos los hallazgos que llevan el mismo como una sola cosa vista en varios sitios. El informe gana entonces una sección "Distinct findings" que enumera cada nombre, qué es y en cuántas entidades apareció. La sección no está en un informe en el que ningún hallazgo lleve nombre.

El motor nunca se lo inventa. Cualquier cosa que pudiera derivar incorporaría la ubicación y por tanto nunca coincidiría entre muestras, que es justamente el caso para el que existe el nombre. Un mismo aviso en cuarenta repositorios es un hallazgo en lugar de cuarenta solo si el procesador lo dice, y lo mismo vale para una única causa raíz detrás de tres mil caídas, o para un único camino de contaminación alcanzado desde dos puntos de entrada.

#### El Léxico

El informe tiene un grupo para aquello que se busca, otro para los hallazgos sobre los que nada se ha pronunciado, y otro para un resultado analizado hasta el final sin nada señalado. Eso es estructural. Solo los nombres son suyos:

| Campo | Predeterminado | Dónde aparece |
|-------|----------------|------------------|
| `discipline` | `vulnerability research` | Junto al nombre del producto en la cabecera |
| `positive` | `Vulnerable` | La etiqueta del grupo, y su filtro |
| `positive_help` | `an assessment stage concluded these are vulnerable` | La explicación que se muestra junto a esa etiqueta |
| `positive_phrase` | `assessed as vulnerable` | Completa "12 repositories ..." en la línea de resumen |
| `nothing_positive` | `Nothing was confirmed vulnerable` | El titular cuando la ejecución no encontró nada sobre lo que actuar |
| `unconfirmed` | `Needs assessment` | Hay hallazgos, pero ninguna evaluación se ha pronunciado sobre ellos |
| `negative` | `Clear` | Analizado hasta el final, sin nada señalado |

Los desenlaces restantes los nombra el motor y no son configurables, porque describen lo que hizo el motor y no lo que buscaba la canalización: "Errored", "Ran out of time", "Unclear verdict" y "Filtered out".

Esto es lo que lleva la herramienta más allá de la investigación de vulnerabilidades. Una canalización que audita licencias de dependencias tiene los mismos tres desenlaces y ni una sola de las palabras predeterminadas para ellos, así que dice cuáles son:

```yaml
report:
  entity: package
  target_label: dependency tree
  classification_key: licence_status
  positive_when: [incompatible]
  negative_when: [compatible]
  lexicon:
    discipline: licence compliance
    positive: Incompatible
    positive_help: the declared licence conflicts with this project's
    positive_phrase: carry an incompatible licence
    nothing_positive: No incompatible licences were found
    unconfirmed: Needs a decision
    negative: Compatible
```

Nada más cambia. El informe sigue ordenando, filtrando, agrupando y exportando exactamente igual que para una caza de controladores, porque nada de eso dependió nunca de qué trataba la ejecución.

### Marcas de Revisión

Una canalización registra lo que concluyó. Que una persona haya comprobado de verdad esa conclusión es una afirmación aparte, y solo puede hacerla quien lee, así que el informe lleva las marcas que va añadiendo durante la lectura.

En la página de cualquier resultado hay dos, porque una revisión o bien llegó a una respuesta o bien no. Los rótulos de la interfaz del informe están en inglés:

| Marca | Significa |
|------|-----------|
| **Confirmed** | comprobado, y se sostiene |
| **Refuted** | comprobado, y no se sostuvo |

Cualquiera de las dos abre una nota para anotar qué ejecutó, sobre qué, y qué ocurrió, de modo que otra persona pueda repetir el intento. La nota pertenece a la marca: un resultado sin marca no tiene dónde ponerla, así que una revisión que no resolvió nada se registra dejando el resultado en paz y no anotando hasta dónde llegó.

Todo lo que no lleva ninguna de las dos cuenta como **Unreviewed**, tanto si nadie lo abrió como si alguien lo abrió y no pudo resolverlo. Antes eran dos controles distintos, y uno junto al otro se leían como lo mismo.

Refuted no se funde deliberadamente con Unreviewed. Es trabajo terminado, con una respuesta definitiva, y un resultado que no se sostuvo nunca debería parecerse a uno que nadie ha examinado.

Las marcas aparecen junto a cada fila del índice y se puede filtrar por ellas, incluida Unreviewed, que da la lista de resultados sobre los que nadie se ha pronunciado todavía. El resumen cuenta los tres estados, de modo que una ejecución puede leerse como lo que realmente se sabe y no solo como lo que se afirmó.

El informe es un archivo, así que las marcas viven en el navegador. **export marks** las escribe en `marks.json`; guarde ese archivo junto a `index.html` y pasan a formar parte del informe: se renderizan para cualquiera que lo abra y se incluyen en `inventory.csv` como `review` y `review_note`. Las marcas se indexan por canalización y destino, no por ruta de archivo, así que volver a ejecutar sobre el mismo corpus las conserva.
