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
- `ctx.global_config`: Un TypedDict que contiene los `settings`, `knowledge` y `model` de la canalización. `ctx.get_setting(key)` y `ctx.get_knowledge(key)` son atajos hacia él.
- `ctx.llm`: Una instancia proxy genérica (que implementa `LLMProtocol`), con reintentos y espera progresiva nativos, o `None` cuando la canalización no configura ningún modelo. El backend que maneja se resuelve a partir de la cadena `model` de la canalización, así que un procesador que llame a `ctx.llm.complete()` funciona igual contra una clave API que contra la CLI de un agente local. Consulte [Elección del Modelo]({{ '/es/reference/pipeline-yaml.html' | relative_url }}).
- `ctx.log`: Un objeto registrador (`logging.Logger`) configurado y con espacio de nombres propio.
- `ctx.progress`: Enlace para informar del progreso, `update(amount=, total=, description=)`, de modo que una ingestión o una etapa masiva de larga duración muestre movimiento en el panel en lugar de parecer colgada.
- `ctx.shutdown_event`: Un `threading.Event` que se activa cuando se interrumpe la ejecución. Un procesador que haga trabajo largo debería consultarlo y salir antes, en lugar de morir a mitad de una escritura.

### Enlaces del Ciclo de Vida

Los procesadores implementan enlaces concretos que el motor invoca:

1. **`validate(ctx: ProcessorContext) -> list[str]`**: Se invoca durante la validación inicial del esquema (mediante `deepzero validate` o antes de la ejecución). Devuelve una lista de cadenas de error si fallan las dependencias (por ejemplo, binarios ausentes o archivos YAML ilegibles).
2. **`setup(global_config: dict) -> None`**: Se ejecuta exactamente una vez antes de que se active el grupo de hilos.
3. **`process(...)`**: La operación principal. La firma varía según el tipo de procesador.
4. **`teardown() -> None`**: Se ejecuta al completarse la canalización o ante una interrupción fatal.

Hay uno más que merece la pena redefinir en un procesador Map que resulte caro por muestra:

5. **`max_parallelism() -> int | None`**: Un techo para la concurrencia automática. Solo se aplica cuando la etapa declara `parallel: 0`; un `parallel: N` explícito se respeta siempre tal como está escrito. Devuelva un entero cuando cada muestra cueste una JVM, un contenedor o unos cuantos gigabytes de memoria, de modo que una canalización dejada en el valor predeterminado no pueda agotar la máquina. `None`, el valor predeterminado, significa que no hay techo.

### Definiciones de Configuración

Utilice una `@dataclass` incrustada llamada `Config` para definir y validar estrictamente las configuraciones YAML aceptadas. El motor analizará el [YAML de la Canalización]({{ '/es/reference/pipeline-yaml.html' | relative_url }}) y creará una instancia de su objeto `Config`, expandiendo por completo las `${ENV_VARS}` de forma automática mediante las [`dataclasses`](https://docs.python.org/3/library/dataclasses.html) estándar de Python.

```python
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

        # ProcessorEntry se vincula a un espacio aislado por muestra
        out_file = entry.sample_dir / "heuristics.json"
        out_file.write_text('{"entropy": 7.1}')

        # ProcessorResult determina el enrutamiento
        if self.config.target_arch != "x86_64":
            return ProcessorResult.filter(reason="unsupported_arch")

        return ProcessorResult.ok(
            artifacts={"heuristics": "heuristics.json"},
            data={"analyzed": True, "entropy_ok": True}
        )
```

### Resultados de la Ejecución (`ProcessorResult`)

Los procesadores Map/BulkMap deben devolver un `ProcessorResult` estrictamente formateado:
- **`.ok(data={...}, artifacts={...})`**: Marca la ejecución como `COMPLETED`. El diccionario `data` queda en el espacio de nombres del bloque de historial del procesador. `artifacts` asocia claves a rutas de archivo relativas.
- **`.filter(reason="...", data={...})`**: Interrumpe en silencio el procesamiento de la muestra. `SampleState.verdict` pasa a `FILTERED`.
- **`.fail(error="...")`**: Interrumpe el procesamiento por un error fatal e inesperado. `SampleState.verdict` pasa a `FAILED`.
- **`.timed_out(budget)`**: El trabajo agotó el tiempo, en lugar de salir mal. `SampleState.verdict` pasa a `TIMED_OUT`, y el presupuesto viaja con él para que el informe pueda decir cuánto habría que concederle en su lugar. Devuélvalo desde un procesador que imponga su propio presupuesto; el `timeout:` de la etapa lo produce por su cuenta.

Un procesador Map puede además redefinir **`should_skip(ctx, entry) -> str | None`**, devolviendo un motivo para declarar que el trabajo ya está hecho, normalmente porque su propio archivo de salida ya está en disco. Una muestra omitida cuenta como aprobada y sigue hacia las etapas posteriores. Registre esa salida como artefacto cuando haga esto: `deepzero run --redo` borra los artefactos registrados precisamente para que un archivo en caché no pueda readoptarse, y un archivo que la ejecución nunca registró sobrevive al estado que lo describe.

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
