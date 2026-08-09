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

Una ejecución reanudada no las reintenta por su cuenta, porque el presupuesto que se quedó corto lo sigue estando. Pídalo:

```bash
deepzero run <target> -p <pipeline> --retry-timeouts
```

Esto olvida únicamente las etapas que agotaron el tiempo y les concede `--timeout-multiplier` (2x de forma predeterminada) más margen. Todos los demás resultados que produjo la ejecución se conservan, así que un reintento cuesta el tiempo que necesitan esas etapas y nada más. Las etapas que no declaran ningún tiempo límite quedan intactas. El informe las agrupa aparte y muestra el presupuesto que superó cada una.

### `report`

```bash
deepzero report -p <pipeline> [--open]
deepzero report -w work/loldrivers/drivers-1a2b3c4d
```

| Opción | Predeterminado | Descripción |
|------|---------|-------------|
| `-p, --pipeline` | ninguno | Nombre o ruta de la canalización. Se resuelve al corpus más reciente de esa canalización. |
| `-w, --work-dir` | ninguno | Un directorio de ejecución que leer directamente. Tiene prioridad sobre `--pipeline`. |
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
| `report.json` | Solo los totales del resumen, para consumo automático |

Una muestra recibe página propia cuando hay algo que leer en ella: hallazgos, una evaluación, un error o una etapa que agotó el tiempo. Las demás siguen estando en el CSV, y el índice indica cuándo se ha recortado un listado y dónde está el resto.

Resolver por nombre de canalización elige el corpus más reciente, y lo advierte cuando la canalización ha visto más de uno, nombrando los otros. La ejecución más nueva no siempre es aquella por la que se pregunta, y responder en silencio sobre un corpus distinto es el fallo que conviene evitar. Pase `--work-dir` para nombrar uno con exactitud.

Cómo llama la canalización a sus muestras, a sus desenlaces y a aquello contra lo que se apuntó viene de su bloque `report:`, así que `--work-dir` por sí solo renderiza con los valores predeterminados: el bloque se lee de la definición de la canalización, no del directorio de la ejecución. Consulte [el bloque report]({{ '/es/reference/pipeline-yaml.html' | relative_url }}).

### `status`

```bash
deepzero status -p loldrivers
```

| Opción | Predeterminado | Descripción |
|------|---------|-------------|
| `-p, --pipeline` | ninguno | Nombre o ruta de la canalización. Se resuelve al corpus más reciente de esa canalización. |
| `-w, --work-dir` | ninguno | Un directorio de ejecución que leer directamente. Tiene prioridad sobre `--pipeline`. |
| `-v, --verbose` | desactivado | Registro detallado. |

Es obligatorio indicar uno de los dos. Imprime el identificador de la ejecución, el destino, el modelo, las marcas de tiempo, una tabla por etapa con los recuentos de completadas, filtradas y fallidas, y los totales de veredictos de las muestras.

### `validate`

```bash
deepzero validate <PIPELINE_REF>
```

Carga la canalización, resuelve cada procesador, ejecuta el `validate()` propio de cada uno y contrasta cada prompt con los valores que producen realmente las etapas anteriores. No admite opciones. Ejecútelo antes de una ejecución larga: es el sitio más barato para encontrar un binario ausente, un conjunto de reglas ilegible o un prompt que nombra algo que ninguna etapa registra.

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
| `-m, --model` | `openai/gpt-4o` | Modelo para la conversación. Cualquier cadena de modelo que acepten los backends. |
| `-w, --work-dir` | `work` | Directorio de ejecución del que cargar el contexto. |
| `-v, --verbose` | desactivado | Registro detallado. |

Una REPL que carga el estado de una ejecución en el prompt de sistema para poder hacerle preguntas. `/status`, `/clear`, `/help` y `/quit` se atienden localmente; todo lo demás va al modelo. Tenga en cuenta que el directorio de trabajo predeterminado es literalmente `work`, no un directorio de ejecución resuelto, así que apunte `-w` a la ejecución que quiera.

### `serve` y la API REST

| Opción | Predeterminado | Descripción |
|------|---------|-------------|
| `--host` | `127.0.0.1` | Host de escucha. Cualquier valor distinto del bucle local imprime una advertencia, porque el servidor queda entonces accesible desde la red. |
| `--port` | `8420` | Puerto de escucha. |
| `-w, --work-dir` | `work` | Directorio de trabajo que servir. |

Requiere el extra: `pip install deepzero[serve]`.

> [!WARNING]
> **Función experimental / en desarrollo**
> El servidor de API REST está incompleto, es muy inestable y **no debería usarse**. Se proporciona estrictamente para desarrollo local experimental.

Inicia una API REST de FastAPI/Starlette de solo lectura para consultar el estado de la ejecución y los datos de las muestras.

| Endpoint | Método | Descripción |
|----------|--------|-------------|
| `/api/health` | GET | Comprobación de estado |
| `/api/runs` | GET | Enumera las ejecuciones de canalización disponibles en el directorio de trabajo |
| `/api/run` | GET | Obtiene el estado global y las métricas de la ejecución actual |
| `/api/samples` | GET | Enumera las muestras (filtrables por `?verdict=`, `?stage=`, `?status=`) |
| `/api/samples/{sample_id}` | GET | Estado completo de la muestra con los datos históricos de la canalización |
| `/api/samples/{sample_id}/artifacts/{name}` | GET | Lee un artefacto de archivo concreto generado por un procesador |
