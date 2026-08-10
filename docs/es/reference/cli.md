---
layout: default
title: Referencia de CLI
order: 1
---

## Interfaz de Línea de Comandos

La CLI `deepzero` es el punto principal de interacción para ejecutar y administrar canalizaciones.

```bash
# Ejecución estándar
deepzero run ./targets -p pipelines/loldrivers/pipeline.yaml

# Comprobar que la sesión del backend LLM está iniciada antes de lanzar una ejecución larga
deepzero run ./targets -p pipelines/source_audit/pipeline.yaml --preflight

# Ejecutar limpiando el estado (ejecución en limpio)
deepzero run ./targets -p pipelines/loldrivers/pipeline.yaml --clean

# Generar un informe HTML navegable y abrirlo
deepzero report -p loldrivers --open

# Comprobar el estado de ejecución
deepzero status -p loldrivers

# Iniciar la REPL de análisis interactivo
deepzero interactive -w work/loldrivers

# Iniciar la API REST de Starlette
deepzero serve -w work/loldrivers --port 8420

# Crear una nueva canalización personalizada
deepzero init my_custom_pipeline

# Validar el esquema sin ejecutar
deepzero validate loldrivers

# Inspeccionar el registro del sistema
deepzero list-processors
```

`deepzero --version` imprime la versión instalada, y `--help` funciona tanto en el grupo como en cada comando.

### Comandos principales

| Comando | Descripción |
| ------- | ----------- |
| `run` | Ejecuta una canalización en un objetivo. Se reanuda automáticamente si existe estado. |
| `report` | Genera un informe HTML navegable a partir de los resultados de una ejecución. Puede ejecutarse con la ejecución en marcha. |
| `status` | Muestra el estado actual de la ejecución, los veredictos y las métricas por etapa. |
| `validate` | Valida en seco el esquema de una canalización, la importación de sus procesadores y sus prompts. |
| `list-processors` | Enumera todos los tipos de procesadores integrados y registrados dinámicamente. |
| `init` | Crea un nuevo directorio de canalización con un `pipeline.yaml` de plantilla. |
| `interactive` | REPL de análisis interactivo, con conversación asistida por LLM sobre los resultados de la canalización. |
| `serve` | Inicia el servidor de API REST para exponer el estado de la canalización al exterior. |

### `run`

```bash
deepzero run <TARGET> -p <pipeline> [opciones]
```

| Opción | Predeterminado | Descripción |
|------|---------|-------------|
| `TARGET` | requerido | Argumento posicional. Ruta al corpus de análisis. Debe existir; un archivo o un directorio, según lo que acepte la etapa de ingestión de la canalización. |
| `-p, --pipeline` | requerido | Nombre de la canalización, directorio o ruta a un archivo YAML concreto. |
| `-m, --model` | el `model` de la canalización | Sustituye el modelo LLM para esta ejecución, por ejemplo `openai/gpt-4o`. |
| `-w, --work-dir` | el ajuste `work_dir` de la canalización | Sustituye la raíz bajo la que se construye el directorio de la ejecución. |
| `--clean` | desactivado | Borra permanentemente los datos de ejecuciones anteriores y empieza de cero. |
| `--preflight` | desactivado | Verifica que el backend LLM está autenticado antes de ejecutar. Hace una llamada mínima. |
| `--redo` | ninguna | Vuelve a ejecutar la etapa que se nombre y todas las posteriores, conservando el trabajo anterior y borrando la salida que esas etapas habían registrado. Se puede repetir. |
| `--retry-timeouts` | desactivado | Vuelve a intentar las muestras que agotaron el tiempo, conservando todos los demás resultados. |
| `--timeout-multiplier` | `2.0` | Cuánto más tiempo conceder al reintentar una etapa que agotó el suyo. |
| `-v, --verbose` | desactivado | Registro detallado, incluidas las trazas del propio código de DeepZero. |

Una ejecución sin estado detrás empieza de cero; una que sí lo tiene se reanuda, y la cabecera indica qué ejecución está retomando. Cambiar `--model` entre ejecuciones está permitido y queda registrado: el estado de la ejecución se actualiza para nombrar el modelo al que se va a llamar realmente, de modo que ni `status` ni el informe describan un modelo que ya no se usa.

`--clean` aparta el directorio anterior renombrándolo y lo borra en segundo plano, así que un corpus con cientos de miles de archivos no retiene el comando mientras se elimina.

#### Dónde vive el estado de una ejecución

Los directorios de trabajo están aislados por corpus:

```text
<ajuste work_dir>/<nombre de la canalización>/<clave de corpus>/
```

La clave de corpus se deriva de la ruta de destino: su nombre base, más un resumen corto de la ruta absoluta resuelta. Dos corpus a través de la misma canalización nunca comparten, por tanto, almacén de muestras, manifiesto ni informe, y cada uno se reanuda por su cuenta. La misma ruta produce siempre la misma clave, así que al repetir una ejecución esta vuelve al directorio que dejó.

La opción `-w, --work-dir` de `run` sustituye únicamente el primer segmento. Los segmentos de canalización y corpus se siguen añadiendo, porque son los que mantienen separadas dos ejecuciones.

#### El informe que una ejecución escribe sobre la marcha

Una ejecución escribe su informe HTML en `<directorio de trabajo>/report` e imprime la URL antes de que arranque la primera etapa. Se reconstruye cuando llegan resultados, no por temporizador, y nunca más a menudo que cada 15 segundos, para que una etapa rápida no gaste el tiempo de la ejecución escribiendo HTML. Se escribe una vez más cuando la ejecución se detiene, interrumpida o terminada, de modo que lo que hay en disco siempre es el estado final.

#### Comprobar el LLM antes de una ejecución larga

`--preflight` pregunta al backend si está listo y se niega a arrancar si no lo está. Existe porque la alternativa es enterarse varias horas después, en la primera etapa de evaluación, cuando las etapas costosas que la preceden ya se han ejecutado.

Qué comprueba exactamente depende del backend, porque estar autenticado significa cosas distintas en cada uno. Un backend de CLI de agente como `claude-code` envía un prompt mínimo, ya que DeepZero no puede leer del disco si ese binario tiene la sesión iniciada. Un backend con clave API responde a partir de la comprobación de la clave que ya se hizo en la validación y no gasta nada.

Un límite de peticiones o un error de red no se tratan como fallo de autenticación y no bloquean la ejecución. La comprobación es opcional en lugar de automática porque ese único prompt es consumo real, por pequeño que sea.

Solo se ejecuta cuando la canalización configura un modelo. Una canalización sin etapas de LLM no tiene nada que comprobar.

#### Reintentar lo que agotó el tiempo

Una etapa que alcanza su `timeout` registra la muestra como que agotó el tiempo, no como fallida. Eso es una afirmación sobre el presupuesto, no sobre la muestra: las que lo agotan son las más grandes, que en la mayoría de los corpus son justamente las que merece la pena mirar, y archivarlas junto a los errores reales sesga la ejecución en contra de ellas sin decirlo.

El presupuesto acota cuánto espera la etapa, no cuánto dura el trabajo. El hilo del procesador se abandona en lugar de matarse, así que un proceso externo que hubiera lanzado sigue corriendo después de que la etapa haya seguido adelante. Consulte [`timeout`]({{ '/es/reference/pipeline-yaml.html' | relative_url }}).

Una ejecución reanudada no las reintenta por su cuenta, porque el presupuesto que se quedó corto lo sigue estando. Pídalo:

```bash
deepzero run <target> -p <pipeline> --retry-timeouts
```

Esto olvida únicamente las etapas que agotaron el tiempo y les concede `--timeout-multiplier` (2x de forma predeterminada) más margen. Todos los demás resultados que produjo la ejecución se conservan, así que un reintento cuesta el tiempo que necesitan esas etapas y nada más. Las etapas que no declaran ningún tiempo límite quedan intactas. El informe las agrupa aparte y muestra el presupuesto que superó cada una.

#### Volver a ejecutar una sola etapa

Editar un prompt, un conjunto de reglas o la configuración de un escáner invalida los resultados de esa etapa y nada de lo anterior. Volver a descompilar un corpus entero para rehacerle una pregunta costaría horas sin motivo, así que nombre la etapa:

```bash
deepzero run <target> -p <pipeline> --redo assess
```

Cada muestra olvida esa etapa y todas las posteriores, y conserva todo lo anterior. Las etapas posteriores se van también porque consumieron una salida que está a punto de cambiar: una evaluación escrita a partir de hallazgos que ya no existen dejaría a una muestra describiendo dos ejecuciones distintas. Una muestra que una etapa obsoleta había filtrado vuelve a la ejecución, de modo que un conjunto de reglas más estrecho es libre de llegar a un veredicto distinto sobre ella.

La salida que esas etapas registraron se va con el estado. Varios procesadores tratan su propio archivo en disco como una caché y lo adoptan en lugar de rehacer el trabajo, así que olvidar solo el estado haría que la etapa readoptara el archivo viejo y lo registrara como recién hecho, que es peor que no volver a ejecutar nada. Por eso `--redo` borra cada artefacto que las etapas descartadas habían registrado, e indica cuántos archivos ha retirado. Un artefacto registrado fuera del propio directorio de la muestra se deja en paz, porque no le corresponde borrarlo a esta ejecución.

`--redo` se puede repetir y arranca desde la primera de las etapas nombradas. Un nombre de etapa que no existe se rechaza, enumerando los nombres reales de las etapas de la canalización, en lugar de tratarse como si no hubiera nada que hacer. Si ninguna muestra había llegado a ninguna de las etapas nombradas, lo dice y no cambia nada.

### `report`

```bash
deepzero report -p <pipeline> [--open]
deepzero report -w work/loldrivers/drivers-1a2b3c4d
```

| Opción | Predeterminado | Descripción |
|------|---------|-------------|
| `-p, --pipeline` | ninguno | Nombre o ruta de la canalización. Se resuelve al corpus más reciente de esa canalización. |
| `-w, --work-dir` | ninguno | Un directorio de ejecución, o la raíz de una canalización, en cuyo caso se lee el corpus más reciente y se dice cuál es. Tiene prioridad sobre `--pipeline`. |
| `-o, --out` | `<work_dir>/report` | Dónde escribir el informe. |
| `--open` | desactivado | Abre el informe en el navegador al terminar. |
| `-v, --verbose` | desactivado | Registro detallado. |

Es obligatorio indicar `--pipeline` o `--work-dir`.

El informe se deriva por completo del estado de la ejecución, así que no contiene ninguna información que no esté en el directorio de la ejecución. Borre el directorio del informe, vuelva a ejecutar el comando y lo recupera. También es seguro generarlo con la ejecución en marcha: lee los archivos de estado y no escribe nada de lo que dependa el ejecutor, así que describe la ejecución tal como estaba en el momento en que se generó.

Escribe:

| Archivo | Contenido |
|------|----------|
| `index.html` | Resumen y una lista ordenada, de tamaño acotado |
| `items/<id>.html` | Una página por cada muestra que merezca lectura, con enlaces a sus artefactos |
| `inventory.csv` | Cada muestra, una fila, para una hoja de cálculo |
| `findings.jsonl` | Cada hallazgo, un objeto JSON por línea |
| `report.json` | Los totales del resumen para consumo automático, más el vocabulario con el que se nombran |

Una muestra recibe página propia cuando hay algo que leer en ella: hallazgos, una evaluación, un error o una etapa que agotó el tiempo. Las demás siguen estando en el CSV, y el índice indica cuándo se ha recortado un listado y dónde está el resto.

Resolver por nombre de canalización elige el corpus más reciente, y lo advierte cuando la canalización ha visto más de uno, nombrando los otros. La ejecución más nueva no siempre es aquella por la que se pregunta, y responder en silencio sobre un corpus distinto es el fallo que conviene evitar. Pase `--work-dir` para nombrar uno con exactitud.

Cómo llama la canalización a sus muestras, a sus desenlaces y a aquello contra lo que se apuntó viene del bloque `report:`, que vive en la definición de la canalización y no en el directorio de la ejecución. `--work-dir` lo obtiene igualmente: la ejecución registra qué canalización la escribió, así que el bloque se recupera por ese nombre. Ahora bien, una ejecución puede sobrevivir a la canalización que la produjo, y cuando esa canalización ya no carga, el informe recae en el vocabulario predeterminado en lugar de negarse a generarse. Consulte [el bloque report]({{ '/es/reference/pipeline-yaml.html' | relative_url }}).

### `status`

```bash
deepzero status -p loldrivers
```

| Opción | Predeterminado | Descripción |
|------|---------|-------------|
| `-p, --pipeline` | ninguno | Nombre o ruta de la canalización. Se resuelve al corpus más reciente de esa canalización. |
| `-w, --work-dir` | ninguno | Un directorio de ejecución, o la raíz de una canalización, en cuyo caso se lee el corpus más reciente y se dice cuál es. Tiene prioridad sobre `--pipeline`. |
| `-v, --verbose` | desactivado | Registro detallado. |

Es obligatorio indicar uno de los dos. Imprime el identificador de la ejecución, el destino, el modelo, las marcas de tiempo, una tabla por etapa con los recuentos de completadas, filtradas, fallidas y fuera de tiempo, y los totales de veredictos de las muestras. Lo que agotó el tiempo tiene columna propia, para que una etapa en la que todo agotó el tiempo no se lea como una etapa a la que no llegó nada, que es justo lo contrario de lo que pasó.

### `validate`

```bash
deepzero validate <PIPELINE_REF>
```

Carga la canalización, resuelve cada procesador, ejecuta el `validate()` propio de cada uno y contrasta cada prompt con los valores que producen realmente las etapas anteriores. No admite opciones. Ejecútelo antes de una ejecución larga: es el sitio más barato para encontrar un binario ausente, un conjunto de reglas ilegible o un prompt que nombra algo que ninguna etapa registra.

Sale con código 1 cuando informa de un error y con 0 en caso contrario, así que puede usarse como control previo a un commit. Las advertencias, como una canalización que no configura ningún modelo, se imprimen pero no hacen fallar el comando: describen una canalización que va a arrancar, no una que no puede.

### `list-processors`

Imprime cada procesador registrado con su tipo y la clase que lo implementa. No admite opciones. Solo se enumeran los integrados; un procesador externo se resuelve por su ruta en el momento de la carga y no queda registrado bajo un nombre.

### `init`

```bash
deepzero init <NAME>
```

Crea `pipelines/<NAME>/pipeline.yaml` bajo el directorio de trabajo, con un esqueleto comentado. Se niega a continuar antes que sobrescribir un directorio existente.

### `interactive`

```bash
deepzero interactive -w work/loldrivers/drivers-1a2b3c4d
```

| Opción | Predeterminado | Descripción |
|------|---------|-------------|
| `-m, --model` | `claude-code/claude-opus-5` | Modelo para la conversación. Cualquier cadena de modelo que acepten los backends. |
| `-w, --work-dir` | `work` | Directorio de ejecución del que cargar el contexto. |
| `-v, --verbose` | desactivado | Registro detallado. |

Una REPL que carga el estado de una ejecución en el prompt de sistema para poder hacerle preguntas. `/status`, `/findings [filtro]`, `/clear`, `/help` y `/quit` se atienden localmente; todo lo demás va al modelo, y un `/palabra` que no se reconozca se señala en lugar de facturarse como un turno de conversación. `/findings` enumera todos los hallazgos que registró la ejecución, restringidos a las líneas que coinciden con su argumento, en el vocabulario que declaró la canalización que escribió la ejecución.

`-w` acepta un directorio de ejecución o la raíz de una canalización, y nombra el corpus que eligió cuando hay más de uno. El valor predeterminado es literalmente `work`, que es la raíz por encima de los directorios de canalización y no se resuelve a ninguna ejecución; la REPL lo dice y responde sin contexto de ejecución en lugar de fingir que ha cargado uno, así que apunte `-w` a la ejecución que quiera.

### `serve` y la API REST

| Opción | Predeterminado | Descripción |
|------|---------|-------------|
| `--host` | `127.0.0.1` | Host de escucha. Cualquier valor distinto del bucle local imprime una advertencia, porque el servidor queda entonces accesible desde la red. |
| `--port` | `8420` | Puerto de escucha. |
| `-w, --work-dir` | `work` | Directorio de trabajo que servir. Un directorio de ejecución, o la raíz de una canalización, en cuyo caso se sirve el corpus más reciente y se dice cuál es. |

Requiere el extra: `pip install deepzero[serve]`, que trae Starlette y uvicorn.

> [!WARNING]
> **Función experimental / en desarrollo**
> El servidor de API REST está incompleto, es muy inestable y **no debería usarse**. Se proporciona estrictamente para desarrollo local experimental.

Inicia una API REST de Starlette de solo lectura para consultar el estado de la ejecución y los datos de las muestras. Sirve exactamente una ejecución, y por eso el directorio de trabajo se resuelve a un único corpus antes de imprimir la URL, y no después de que una petición vuelva vacía.

| Endpoint | Método | Descripción |
|----------|--------|-------------|
| `/api/health` | GET | Comprobación de estado, y el directorio de trabajo que se está sirviendo |
| `/api/runs` | GET | La ejecución servida como lista de un elemento, o una lista vacía |
| `/api/run` | GET | Estado completo de esa ejecución, o 404 |
| `/api/samples` | GET | Enumera las muestras (filtrables por `?verdict=`, `?classification=`, `?stage=`, `?status=`) |
| `/api/samples/{sample_id}` | GET | Estado completo de la muestra con los datos históricos de la canalización |
| `/api/samples/{sample_id}/artifacts/{name}` | GET | Lee un artefacto de archivo concreto generado por un procesador |

`verdict` es por dónde salió una muestra de la canalización y `classification` es lo que una etapa concluyó sobre ella. Los dos viajan en la respuesta, así que cada uno filtra el campo del que toma el nombre. `stage` coincide con la etapa actual de la muestra; `status` conserva una muestra cuando cualquier etapa de su historial lleva ese estado. Un identificador de muestra que contenga un separador de rutas se rechaza, porque el identificador se convierte en una ruta del sistema de archivos y este servidor puede quedar escuchando en todas las interfaces.
