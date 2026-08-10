---
layout: default
title: Inicio rápido
order: 1
---

## Inicio rápido

DeepZero requiere un corpus de destino para analizar y una [configuración de canalización]({{ '/es/reference/pipeline-yaml.html' | relative_url }}) que detalla cómo procesarlo. Se incluyen dos [canalizaciones completas]({{ '/es/reference/included-pipeline.html' | relative_url }}): una que busca nuevos candidatos BYOVD (Bring Your Own Vulnerable Driver) en conjuntos de datos binarios sin procesar (por ejemplo, el corpus de Snappy Driver Installer) descartando de forma explícita los hashes ya conocidos mediante el [proyecto LOLDrivers](https://www.loldrivers.io/), y otra que audita código fuente en repositorios git.

### 1. Instalación

DeepZero requiere **Python 3.11+**.

```bash
git clone https://github.com/416rehman/DeepZero.git
cd DeepZero
pip install -e .
```

### 2. Configuración del entorno

Si integra etapas de análisis de IA, configure las claves API creando un archivo `.env`:

```bash
cp .env.example .env
```

Ambas canalizaciones incluidas declaran un modelo `claude-code`, que utiliza la CLI de Claude Code en la que ya ha iniciado sesión y no necesita ninguna clave API. En su lugar sirve cualquier [modelo de LiteLLM]({{ '/es/reference/pipeline-yaml.html' | relative_url }}), mediante el campo `model` de la canalización o la opción `-m` en la línea de comandos, y para eso son las claves anteriores.

### 3. Comprobación antes de lanzar una ejecución larga

Estas ejecuciones son largas. Esta comprobación es barata, responde en segundos en lugar de en horas y no arranca nada:

```bash
# resuelve cada procesador, comprueba sus requisitos previos y revisa cada prompt
deepzero validate pipelines/loldrivers/pipeline.yaml
```

Sale con código 1 cuando informa de un error, así que sirve como hook de commit o como paso de integración continua, y no solo como algo que leer.

### 4. Ejecución de la canalización

Ejecute la canalización LOLDrivers incluida contra una ruta de destino:

```bash
deepzero run C:\drivers -p .\pipelines\loldrivers\pipeline.yaml
```

O la auditoría de código fuente, contra un manifiesto de repositorios o un directorio de copias locales:

```bash
deepzero run repos.txt -p .\pipelines\source_audit\pipeline.yaml
```

Cualquiera de las dos admite `--preflight`, que hace una llamada mínima para confirmar que la sesión del backend LLM está realmente iniciada. Se detiene en segundos si el backend no está listo y, si lo está, la ejecución continúa con normalidad, así que es una opción sobre una ejecución que quería lanzar y no una comprobación para escribir por su cuenta. La alternativa es enterarse varias horas después, en la primera etapa de evaluación:

```bash
deepzero run C:\drivers -p .\pipelines\loldrivers\pipeline.yaml --preflight
```

<div class="callout">
    <p><strong>Nota:</strong> DeepZero <a href="{{ '/es/overview/architecture.html' | relative_url }}">paraleliza la ejecución</a> y almacena en caché las salidas intermedias de forma segura. Para detenerse correctamente, envíe SIGINT (<code>Ctrl+C</code>). Las ejecuciones posteriores con parámetros idénticos se reanudarán instantáneamente desde <a href="{{ '/es/system/state-persistence.html' | relative_url }}">el estado persistente en disco</a>.</p>
</div>

Cada corpus recibe su propio directorio de trabajo, así que apuntar la misma canalización a un segundo destino inicia una segunda ejecución en lugar de reanudarse sobre los resultados de la primera. Ambas siguen siendo reanudables.

### 5. Lectura de los resultados

Una ejecución imprime la URL de un informe antes de su primera etapa y lo mantiene al día a medida que llegan los resultados, así que puede abrirse y seguirse mientras la ejecución avanza. Para generarlo de nuevo en cualquier momento, incluso sobre una ejecución todavía en curso:

```bash
deepzero report -p loldrivers --open
```

Nombrar solo la canalización resuelve a su corpus más reciente, y dice qué otros corpus ha visto esa canalización, porque la ejecución más nueva no siempre es aquella por la que se pregunta. Para ver en cambio todas las ejecuciones que hay bajo `work`, las produjera la canalización o el corpus que fuera, y las más nuevas primero:

```bash
deepzero runs
```

Eso enumera para cada ejecución su canalización, su corpus, su estado y su número de muestras, e imprime la línea `deepzero report -w <dir>` con la que consultar una de ellas. `deepzero report` sin ninguna opción responde a la misma pregunta de forma directa: si hay una sola ejecución se toma esa, y si hay varias se convierten en una lista de la que elegir.

El informe se deriva por completo del estado de la ejecución, así que puede borrarse y reconstruirse, y el nombre que reciben las cosas que encuentra lo [declara la canalización]({{ '/es/reference/pipeline-yaml.html' | relative_url }}).
