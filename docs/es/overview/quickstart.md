---
layout: default
title: Inicio rápido
order: 1
---

## Inicio rápido

DeepZero requiere un corpus de archivos de destino para analizar y una [configuración de canalización]({{ '/es/reference/pipeline-yaml.html' | relative_url }}) que detalla cómo procesarlos. Proporcionamos una [canalización de ejemplo completa]({{ '/es/reference/included-pipeline.html' | relative_url }}) diseñada para buscar nuevos candidatos BYOVD en conjuntos de datos binarios sin procesar.

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

### 3. Ejecución de la canalización

Ejecute la canalización LOLDrivers incluida contra una ruta de destino:

```bash
deepzero run C:\drivers -p .\pipelines\loldrivers\pipeline.yaml
```

<div class="callout">
    <p><strong>Nota:</strong> DeepZero <a href="{{ '/es/overview/architecture.html' | relative_url }}">paraleliza la ejecución</a> y almacena en caché las salidas intermedias de forma segura. Para detenerse correctamente, envíe SIGINT (<code>Ctrl+C</code>). Las ejecuciones posteriores con parámetros idénticos se reanudarán instantáneamente desde <a href="{{ '/es/system/state-persistence.html' | relative_url }}">el estado persistente en disco</a>.</p>
</div>
