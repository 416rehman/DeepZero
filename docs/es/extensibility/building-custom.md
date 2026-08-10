---
layout: default
title: Creación de Procesadores
order: 2
---

## Construcción de Procesadores Personalizados

La lógica del usuario se integra en DeepZero extendiendo las abstracciones tipificadas en `deepzero.engine.stage`. Consulte la [Arquitectura Básica]({{ '/es/overview/architecture.html' | relative_url }}) para entender cómo se corresponden estas etapas con las fases de ejecución.

### Contexto del Procesador (`ProcessorContext`)

El objeto `ctx` inyectado en cada enlace del ciclo de vida proporciona un contexto en todo el sistema y utilidades:
- `ctx.pipeline_dir`: El directorio raíz de la canalización en ejecución, útil para resolver plantillas o conjuntos de reglas locales.
- `ctx.global_config`: Un TypedDict que contiene los `settings`, `knowledge` y `model` de la canalización, además de `pipeline_dir`, el directorio desde el que se cargó la canalización, en forma de cadena. Esa última clave existe porque `setup()` recibe esta configuración y ningún contexto, así que sin ella un valor de configuración que nombre un archivo distribuido con la canalización se resolvería contra el directorio de trabajo. `ctx.get_setting(key)` y `ctx.get_knowledge(key)` son atajos hacia él.
- `ctx.llm`: Una instancia proxy genérica (que implementa `LLMProtocol`), con reintentos y espera progresiva nativos, o `None` cuando la canalización no configura ningún modelo. El backend que maneja se resuelve a partir de la cadena `model` de la canalización, así que un procesador que llame a `ctx.llm.complete()` funciona igual contra una clave API que contra la CLI de un agente local. Consulte [Elección del Modelo]({{ '/es/reference/pipeline-yaml.html' | relative_url }}).
- `ctx.log`: Un objeto registrador (`logging.Logger`) configurado y con espacio de nombres propio.
- `ctx.progress`: Enlace para informar del progreso, `update(amount=, total=, description=)`, de modo que una ingestión o una etapa masiva de larga duración muestre movimiento en el panel en lugar de parecer colgada.
- `ctx.shutdown_event`: Un `threading.Event` que se activa cuando se interrumpe la ejecución. Un procesador que haga trabajo largo debería consultarlo y salir antes, en lugar de morir a mitad de una escritura.
- `ctx.conclude(**fields)`: Registra un hallazgo sobre el corpus en lugar de sobre una muestra concreta. Hay preguntas que solo tienen respuesta en conjunto: qué modelo hay detrás de un endpoint, cuántos fallos distintos representa un montón de caídas. Los campos se fusionan en la `conclusion` de la ejecución y esta se guarda de inmediato, así que una ejecución interrumpida conserva igualmente lo que ya había averiguado.

El motor conecta `conclude` con un escritor real únicamente en una etapa `reduce` o `bulk_map`, que son las que ven todas las muestras en una sola llamada:

```python
class ModelFingerprint(ReduceProcessor):
    def process(self, ctx: ProcessorContext, entries: list[ProcessorEntry]) -> list[str]:
        ctx.conclude(headline="every probe answers as the same model family", probes=len(entries))
        return [e.sample_id for e in entries]
```

En una etapa map o ingest la llamada registra que `ctx.conclude()` solo está disponible para una etapa reduce o bulk_map y que la llamada se ignoró, y después no hace nada. Un carril por muestra repartido entre un grupo de hilos no puede hablar por el corpus sin competir consigo mismo: ganaría la muestra que terminara la última, y la perdedora nunca sabría que la habían sobrescrito.

### Enlaces del Ciclo de Vida

Los procesadores implementan enlaces concretos que el motor invoca:

1. **`validate(ctx: ProcessorContext) -> list[str]`**: Se invoca durante la validación inicial del esquema (mediante `deepzero validate` o antes de la ejecución). Devuelve una lista de cadenas de error si fallan las dependencias (por ejemplo, binarios ausentes o archivos YAML ilegibles). Aquí el contexto es reducido: `ctx.global_config` lleva únicamente `settings`, `knowledge` y `model`, sin clave `pipeline_dir`, y `ctx.llm` es `None` porque todavía no se ha construido ningún proveedor. Una comprobación que necesite cualquiera de los dos malinterpretará la canalización. `ctx.pipeline_dir` en sí sí está poblado, así que resuelva por ahí los archivos que acompañan a la canalización.
2. **`setup(global_config: dict) -> None`**: Se ejecuta exactamente una vez antes de que se active el grupo de hilos.
3. **`process(...)`**: La operación principal. La firma varía según el tipo de procesador.
4. **`teardown() -> None`**: Se ejecuta al completarse la canalización o ante una interrupción fatal.

Hay uno más que merece la pena redefinir en un procesador Map que resulte caro por muestra:

5. **`max_parallelism() -> int | None`**: Un techo para la concurrencia automática. Solo se aplica cuando el YAML de la etapa declara `parallel: 0`; cualquier `parallel: N` mayor que cero se respeta tal como está escrito, antes de consultar el techo o el ajuste `max_workers`. Devuelva un entero cuando cada muestra cueste una JVM, un contenedor o unos cuantos gigabytes de memoria, de modo que una etapa que pidió escalar sola no pueda tomar un trabajador por núcleo. `None`, el valor predeterminado, significa que no hay techo. Omitir `parallel:` no es lo mismo que escribir `parallel: 0`: una etapa que no lo nombra se carga con 4, lo que cuenta como una cifra explícita, así que el techo nunca le llega.

### Lo que Lleva la Instancia del Procesador

`ctx` describe la ejecución. El objeto procesador en sí lleva lo que pertenece a la etapa:
- `self.config`: la clase de datos `Config` ya analizada, o el diccionario YAML sin procesar cuando el procesador no declara ninguna `Config`.
- `self.spec`: el `StageSpec` a partir del cual se construyó esta instancia: su nombre, su bloque de configuración, `parallel`, `on_failure`, `max_retries` y `timeout`.
- `self.log`: un registrador con espacio de nombres propio del nombre de la etapa.
- `self.global_config`: el mismo `GlobalConfig` que lleva `ctx`, que el motor asigna antes de que se ejecute `setup()`.
- `self.processor_dir`: el directorio que contiene el archivo `.py` de este mismo procesador, para los scripts, plantillas y archivos de reglas que se distribuyen junto a él. No es `ctx.pipeline_dir`: una canalización puede nombrar un procesador que viva en otro sitio por completo, y entonces los dos apuntan a lugares distintos.
- `self.cache_dir`: un directorio persistente en `./.cache/<nombre de la etapa>`, creado en el primer acceso. Nada en el motor lo vacía, así que sobrevive de una ejecución a otra y es el sitio para las descargas y demás trabajo demasiado caro de repetir.

### Definiciones de Configuración

Declare la configuración YAML que acepta un procesador con una `@dataclass` incrustada llamada `Config`. El motor expande `${VAR}` y `${VAR:-default}` en el [YAML de la Canalización]({{ '/es/reference/pipeline-yaml.html' | relative_url }}) y crea una instancia de su `Config` a partir del bloque `config` de la etapa, mediante las [`dataclasses`](https://docs.python.org/3/library/dataclasses.html) estándar de Python.

Declarar los campos no es lo mismo que imponerlos. Una clave que la clase de datos no declara se registra como no leída por este procesador, se enumera junto a los nombres que sí acepta y luego se descarta, y la ejecución continúa; `limit` lo lee el propio motor y queda exento de ese aviso. Nada comprueba los tipos. Un `${VAR}` sin definir se expande a la cadena vacía en lugar de quedarse literal, así que una variable de entorno que falta llega como un campo presente y en blanco, no como un error. Dele un valor predeterminado a cada campo y haga la comprobación de verdad en `validate()`, que se ejecuta antes de tocar ninguna muestra.

```python
import json
import math
from collections import Counter
from dataclasses import dataclass
from deepzero.engine.stage import MapProcessor, ProcessorContext, ProcessorEntry, ProcessorResult

class BinaryAnalyzer(MapProcessor):
    description = "Static heuristics extraction"

    @dataclass
    class Config:
        target_arch: str = "x86_64"
        max_entropy: float = 7.5

    def process(self, ctx: ProcessorContext, entry: ProcessorEntry) -> ProcessorResult:
        # Recuperar los datos emitidos por un IngestProcessor anterior
        sha = entry.upstream_data("discover", "sha256", default="UNKNOWN")

        # entry.source_path es aquello que se analiza: lo que la etapa de
        # ingestión registró para esta muestra, y el único asidero que hay sobre ello
        entropy = self._shannon_entropy(entry.source_path.read_bytes())

        # ProcessorEntry se vincula a un espacio aislado por muestra
        out_file = entry.sample_dir / "heuristics.json"
        out_file.write_text(json.dumps({"sha256": sha, "entropy": entropy}))

        # ProcessorResult determina el enrutamiento
        if self.config.target_arch != "x86_64":
            return ProcessorResult.filter(reason="unsupported_arch")

        return ProcessorResult.ok(
            artifacts={"heuristics": "heuristics.json"},
            data={"analyzed": True, "entropy_ok": entropy <= self.config.max_entropy}
        )

    @staticmethod
    def _shannon_entropy(blob: bytes) -> float:
        counts = Counter(blob)
        return -sum(
            (n / len(blob)) * math.log2(n / len(blob)) for n in counts.values()
        ) if blob else 0.0
```

### Resultados de la Ejecución (`ProcessorResult`)

Los procesadores Map/BulkMap deben devolver un `ProcessorResult` estrictamente formateado:
- **`.ok(data={...}, artifacts={...})`**: Marca la ejecución como `COMPLETED`. El diccionario `data` queda en el espacio de nombres del bloque de historial del procesador. `artifacts` asocia claves a rutas de archivo relativas.
- **`.filter(reason="...", data={...})`**: Interrumpe en silencio el procesamiento de la muestra. `SampleState.verdict` pasa a `FILTERED`.
- **`.fail(error="...")`**: Interrumpe el procesamiento por un error fatal e inesperado. `SampleState.verdict` pasa a `FAILED`.
- **`.timed_out(budget)`**: El trabajo agotó el tiempo, en lugar de salir mal. `SampleState.verdict` pasa a `TIMED_OUT`, y el presupuesto viaja con él para que el informe pueda decir cuánto habría que concederle en su lugar. Devuélvalo desde un procesador que imponga su propio presupuesto; el `timeout:` de la etapa lo produce por su cuenta.

Un procesador Map puede además redefinir **`should_skip(ctx, entry) -> str | None`**, devolviendo un motivo para declarar que el trabajo ya está hecho, normalmente porque su propio archivo de salida ya está en disco. Una muestra omitida cuenta como aprobada y sigue hacia las etapas posteriores. Registre esa salida como artefacto cuando haga esto: `deepzero run --redo` borra los artefactos registrados precisamente para que un archivo en caché no pueda readoptarse, y un archivo que la ejecución nunca registró sobrevive al estado que lo describe.

Compruebe `entry.cache_is_valid` además de la ruta, nunca la ruta sola:

```python
def should_skip(self, ctx: ProcessorContext, entry: ProcessorEntry) -> str | None:
    if entry.cache_is_valid and (entry.sample_dir / "out.json").exists():
        return "cached"
    return None
```

`cache_is_valid` vale `False` cuando el archivo que hay en disco salió de un prompt, un
conjunto de reglas o una configuración que han cambiado desde entonces: el motor compara el
resumen de las entradas registrado en la ejecución anterior con el que producen ahora las
entradas de esta etapa. Un `should_skip` que solo comprueba `.exists()` readopta una salida
que responde a una pregunta que la canalización ya no hace. Tanto la etapa LLM integrada como
el escáner Semgrep incluido adoptan esta salvaguarda allí donde readoptan un archivo
existente.

### Declarar lo que Podrán Usar las Etapas Posteriores

Las claves de `data` y los artefactos de un procesador quedan disponibles para los prompts de las etapas que se ejecutan después de él. Declare esos nombres en `provides` para que `deepzero validate` pueda revisar un prompt antes de una ejecución, en lugar de dejar que un nombre desconocido se renderice como nada:

```python
class Decompiler(MapProcessor):
    description = "Static heuristics extraction"
    provides = (
        "device_name",                    # una clave que este procesador pone en data
        "decompiled_dispatch_ioctl_c",    # el artefacto decompiled/dispatch_ioctl.c
    )
```

Un artefacto se nombra por su ruta, con los separadores y la extensión incorporados al nombre; `template_key_for_artifact`, en `engine/stage.py`, es la única regla que usan tanto el renderizado como la validación. Incluya en la lista los nombres que solo se registran a veces: se espera que un prompt tolere su ausencia. Consulte [Valores del Prompt]({{ '/es/reference/pipeline-yaml.html' | relative_url }}) para saber qué recibe un prompt.

### Lo que Lleva una Entrada (`ProcessorEntry`)

A todo procesador map, bulk_map y reduce se le entregan entradas en lugar de muestras sin procesar:
- `entry.sample_id`: el identificador único de la muestra, y la clave bajo la que se guarda su estado.
- `entry.source_path`: un `Path` hacia aquello que se analiza, sea lo que sea lo que la etapa de ingestión registró para esta muestra. Es el único asidero que tiene un procesador map sobre su entrada.
- `entry.filename`: el nombre visible, que se usa en los registros y en los informes.
- `entry.sample_dir`: el directorio de trabajo aislado de esta muestra, donde corresponde dejar la salida.
- `entry.cache_is_valid`: si la salida que ya está en `sample_dir` se produjo con las entradas actuales de esta etapa, tal como se describe más arriba en `should_skip`.

### Acceso a los Datos de Etapas Anteriores

Los procesadores dependen por naturaleza de los artefactos y los datos que generaron sus predecesores. La fachada `ProcessorEntry` expone métodos auxiliares de carga diferida para recuperar esos datos sin fricción:

```python
# Extracción abreviada de un campo concreto (con valor de reserva)
sha = entry.upstream_data("discover", "sha256", default="")

# Extracción completa del objeto StageOutput de una etapa anterior
output = entry.upstream("scan")
findings = output.data.get("finding_count", 0)
json_file = output.artifacts.get("findings_file")
```

### Clases Base

Según la topología que necesite su canalización, extienda la clase base correspondiente:

| Clase base | Tipo de procesador | Firma de `process()` |
|-----------|---------------|----------------------|
| `IngestProcessor` | `ingest` | `(ctx, target: Path) → list[Sample]` |
| `MapProcessor` | `map` | `(ctx, entry: ProcessorEntry) → ProcessorResult` |
| `BulkMapProcessor` | `bulk_map` | `(ctx, entries: list[ProcessorEntry]) → list[ProcessorResult]` |
| `ReduceProcessor` | `reduce` | `(ctx, entries: list[ProcessorEntry]) → list[str]` |
