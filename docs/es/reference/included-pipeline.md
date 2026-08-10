---
layout: default
title: Canalizaciones incluidas
order: 3
---

## Canalizaciones incluidas

DeepZero incluye dos canalizaciones completas. Existen para ejecutarse, y para leerse como
ejemplos trabajados de qué aspecto tiene la definición de una canalización cuando hace algo
real.

| Canalización | Corpus | Qué busca |
|----------|--------|-------------------|
| `pipelines/loldrivers` | Controladores del kernel de Windows en disco | Candidatos BYOVD: superficies IOCTL alcanzables sin el hardware |
| `pipelines/source_audit` | Repositorios git | Vulnerabilidades a nivel de código fuente alcanzables desde entrada no confiable |

Ambas declaran `model: claude-code/claude-opus-5`, así que se ejecutan contra una suscripción
de Claude Code sin ninguna clave API. Sustitúyalo con `-m` por cualquier modelo de LiteLLM.
Consulte [Elección del Modelo]({{ '/es/reference/pipeline-yaml.html' | relative_url }}).

---

## Canalización LOLDrivers

En `pipelines/loldrivers/` se mantiene una canalización de referencia BYOVD (Bring Your Own
Vulnerable Driver).

| Etapa | Procesador | Qué hace |
|-------|-----------|--------------|
| `discover` | `pe_ingest/pe_ingest.py` | Ingestión de PE y análisis de encabezados con LIEF |
| `kernel_filter` | `metadata_filter` | Restringe a controladores en modo kernel que exponen superficies IOCTL, y deduplica por hash |
| `loldrivers_filter` | `loldrivers_filter/loldrivers_filter.py` | Excluye entidades conocidas catalogadas en loldrivers.io |
| `decompile` | `ghidra_decompile/ghidra_decompile.py` | Ejecuta la descompilación de Ghidra sin interfaz gráfica |
| `semgrep_scanner` | `semgrep_scanner/semgrep_scanner.py` | Análisis estático en masa sobre el código fuente en C exportado. Un controlador en el que no se señala nada se detiene aquí (`min_findings: 1`) |
| `rank_by_findings` | `top_k` | Ordena todos los controladores supervivientes por número de hallazgos, los peores primero |
| `assess` | `generic_llm` | Renderiza `assessment.j2` para cada controlador y registra el veredicto |

La etapa de ordenación lo conserva todo (`keep_top: 0`) y solo cambia el orden. Es
deliberado: quedarse únicamente con una primera franja ahorra llamadas de evaluación, pero
decide qué controladores merece la pena leer a partir de un número de hallazgos, que es
exactamente el juicio para el que existe la etapa de evaluación. Ordenar de peor a mejor
consigue que se miren primero esos mismos controladores sin tirar el resto, y una ejecución
detenida antes de tiempo ha gastado igualmente su tiempo en los controladores más ruidosos.

Las exclusiones se ejecutan antes de la descompilación por la razón inversa: Ghidra es con
diferencia la etapa más cara, así que cada controlador que retira una comprobación barata de
encabezados o una búsqueda de hash son minutos que no se gastan.

### Si un hallazgo puede ejercitarse sin el hardware

Muchos controladores crean su objeto de dispositivo solo una vez que su hardware ha sido
enumerado. En una máquina o una VM sin ese dispositivo, `\.\<name>` nunca se abre, así que no
se puede alcanzar nada de lo que el controlador expone, y desde el informe eso resulta
indistinguible de que el controlador no sea vulnerable.

La etapa `decompile` registra dónde se crea el objeto de dispositivo:

| Valor | Significado |
|-------|---------|
| `device_created_in` | la función que llama a `IoCreateDevice` |
| `device_on_load_path` | si esa función es `DriverEntry`, o algo a lo que esta llama |

`device_on_load_path: true` significa que el dispositivo aparece en cualquier máquina que
vaya a cargar el controlador, así que un hallazgo contra él puede confirmarse hoy mismo.
`false` significa que se crea en otro sitio, normalmente una devolución de llamada PnP de tipo
add-device o start-device, y confirmar cualquier cosa exige el dispositivo físico. No se
registra ninguno de los dos cuando `IoCreateDevice` no aparece en absoluto, en lugar de
adivinar.

La canalización incluida lista `decompile.device_on_load_path` bajo `report.columns`, así que
se muestra junto a cada controlador. Eso es todo lo que hace falta: el valor está declarado en
el `provides` del procesador y nombrado por la canalización, y el informe sigue sin saber qué
es un objeto de dispositivo.

### Qué escribe la descompilación por controlador

La etapa `decompile` escribe en el directorio `decompiled/` de cada muestra:

| Archivo | Contenido |
|------|----------|
| `dispatch_ioctl.c` | La rutina de despacho, registrada una sola vez |
| `ioctls/0xXXXXXXXX.c` | Uno por código IOCTL: en qué se descompone el código, apuntando a la rutina anterior |
| `ghidra_result.json` | Metadatos: nombre del dispositivo, enlace simbólico, nombre del despacho y una entrada por código IOCTL |

Todos los códigos de un controlador los atiende la misma rutina, así que se almacena una vez y
se referencia, nunca se copia por código. Una entrada de `ioctl_handlers` guarda solo el código
y sus campos decodificados (`hex`, `device_type`, `function`, `method`, `access`).

Conviene vigilar el tamaño, porque aquí el modo de fallo es silencioso: la salida sigue
pareciendo correcta, solo que enorme. Como referencia, un paquete de 1.388 controladores
descompilados produce en total unos **28 MB** de `ghidra_result.json`. Almacenar la rutina por
cada código producía **734 MB** para el mismo corpus, y un único controlador llegaba a 52 MB.
Una ejecución de la etapa cuya salida esté órdenes de magnitud por encima de esto ha
retrocedido a repetir la rutina, y la etapa de evaluación pasará entonces a analizar ese
documento para cada controlador al construir su prompt.

`tests/test_extract_dispatch.py` protege directamente la forma de la entrada.

### Requisitos previos

- Ghidra, con `GHIDRA_INSTALL_DIR` definido. `JAVA_HOME` se lee si está presente.
- `semgrep` en el PATH: `pip install semgrep`.

---

## Canalización de auditoría de código fuente

Una auditoría de código fuente sobre repositorios git, en `pipelines/source_audit/`. Cada
repositorio se toma en una revisión, se analiza con semgrep y después lo lee un modelo cuyo
trabajo es separar una vulnerabilidad real de una regla que coincide con una forma del código.

| Etapa | Procesador | Qué hace |
|-------|-----------|--------------|
| `discover` | `git_ingest/git_ingest.py` | Clona cada repositorio a profundidad 1, o lee una copia local ya presente en disco, y registra la revisión que juzga todo lo que viene después |
| `size_filter` | `metadata_filter` | Descarta las copias sin código fuente dentro y los árboles demasiado grandes para que merezca la pena analizarlos; un commit alcanzado bajo dos nombres se analiza una sola vez |
| `scan` | `semgrep_scanner/semgrep_scanner.py` | Ejecuta `rules/` sobre cada copia local. Un repositorio sin nada señalado se detiene aquí |
| `rank` | `top_k` | Ordena todos los repositorios supervivientes por número de hallazgos, los peores primero, sin descartar ninguno |
| `assess` | `generic_llm` | Renderiza `assessment.j2` para cada repositorio y registra el veredicto |

Las dos mitades importan en ese orden. Semgrep es barato y encuentra todos los sitios que
merece mirar; casi todos esos sitios están bien. La etapa de evaluación es donde un hallazgo o
bien gana un camino desde la entrada del atacante hasta el sumidero, o bien se descarta, con
nombre y apellidos, por inalcanzable.

### A qué apuntarla

`deepzero run` toma un único destino, y la etapa de ingestión lee cualquiera de las dos formas:

- **Un directorio**, donde cada subdirectorio inmediato es una copia local. No se descarga
  nada, así que el código privado nunca tiene que salir de la máquina en la que ya está. Un
  directorio que es en sí mismo una copia local se lee como un solo repositorio, y un volcado
  de código sin `.git` también se lee; simplemente no tiene revisión ni origen que informar.
- **Un archivo**, leído como manifiesto de repositorios que clonar. Texto plano, uno por línea,
  con comentarios `#`, o YAML como lista o como mapa con una clave `repos:` cuyas entradas
  pueden fijar una referencia.

```bash
# auditar los repositorios listados en un manifiesto
deepzero run repos.txt -p pipelines/source_audit/pipeline.yaml

# o un directorio de copias locales ya presentes en disco
deepzero run C:\code\vendor -p pipelines/source_audit/pipeline.yaml
```

Los clones viven en el directorio de caché propio de la etapa de ingestión y no en el
directorio de trabajo, así que repetir la ejecución no cuesta red y `--clean` no los tira.

### Reglas y lenguajes

`rules/` contiene 136 reglas de semgrep que cubren Python, JavaScript, TypeScript, Go, Java,
Ruby, PHP y C#, agrupadas por lo que buscan: inyección, salto de directorios y SSRF,
autenticación y autorización, criptografía y secretos, deserialización, y XSS y encabezados de
respuesta.

Tres sitios tienen que estar de acuerdo: las reglas, la lista `extensions` de `discover` y la
lista idéntica de `scan`. Fallan en direcciones opuestas. Una extensión que las listas se dejan
fuera no se cuenta ni se analiza, así que el repositorio acaba pareciendo más pequeño y más
limpio de lo que es. Una extensión que las listas incluyen y ninguna regla cubre se recorre, se
cuenta y se prepara para un análisis que nunca podrá coincidir con ella. Añadir un lenguaje
significa los tres sitios, y `tests/test_source_audit_pipeline.py` falla si se desincronizan.

Por tanto, un repositorio escrito en un lenguaje que `rules/` no cubre cuenta cero archivos de
código y lo descarta `size_filter`. Eso se lee como "sin código fuente" cuando significa "aquí
no hay nada que esta canalización pueda auditar", y sigue siendo el desenlace que conviene: el
árbol se descarta una etapa después del clonado, en lugar de prepararse para un análisis cuyas
reglas nunca podrían dispararse.

### Cómo leer su informe

La canalización declara su propio vocabulario, porque un repositorio no es un archivo en disco:

```yaml
report:
  title: Source repository audit
  entity: repository
  entity_plural: repositories
  target_label: repository list
  classification_key: classification
  vulnerable_when: [vulnerable]
  safe_when: [not exploitable]
  lexicon:
    negative: Not exploitable
```

`target_label` nombra el destino de la ejecución, y el valor que el informe coloca a su lado
es el manifiesto o el directorio de copias locales al que se apuntó la ejecución, así que
llamarlo organización sería nombrar algo que la cabecera no muestra: un mismo manifiesto puede
enumerar repositorios de varios propietarios.

`vulnerable_when` se restringe por una razón que conviene conocer. La evaluación responde
`[VULNERABLE]` o `[NOT EXPLOITABLE]`, y la lista de positivos predeterminada incluye
`exploitab`, que el veredicto negativo contiene. Consulte
[Cómo se Compara un Veredicto]({{ '/es/reference/pipeline-yaml.html' | relative_url }}).
`vulnerable_when` y `safe_when` son la forma antigua de escribir `positive_when` y
`negative_when`, y siguen significando lo mismo.

La única sustitución del léxico está ahí porque un repositorio solo llega a la evaluación
cuando el análisis señaló algo. Nada de lo que hay en el grupo negativo es código sin tocar:
es un repositorio cuyos hallazgos se leyeron y ninguno llegaba a ninguna parte. "Clear", la
palabra predeterminada para ese grupo, dice lo contrario.

Sus `columns` colocan junto a cada repositorio el número de hallazgos, los archivos analizados,
el número de archivos de código, el lenguaje principal y la revisión. Los archivos analizados
se ganan su sitio: un repositorio sin hallazgos y un repositorio cuyos archivos semgrep nunca
abrió muestran ambos cero hallazgos, y solo uno de los dos es un resultado.

### Requisitos previos

- `git` en el PATH, para la etapa `discover`.
- `semgrep` en el PATH: `pip install semgrep`.

Compruébelo todo, para cualquiera de las dos canalizaciones, antes de comprometerse con una
ejecución larga:

```bash
deepzero validate pipelines/source_audit/pipeline.yaml
```

Sale con código 1 si informa de un error, así que puede usarse como control previo a un
commit y no solo como algo que leer.
