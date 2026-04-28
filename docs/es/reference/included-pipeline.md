---
layout: default
title: Canalización LOLDrivers
order: 3
---

## Referencia de la Canalización LOLDrivers

En `pipelines/loldrivers/` se mantiene una canalización de referencia BYOVD (Bring Your Own Vulnerable Driver).

1. **discover:** Ingestión de PE y análisis de encabezados LIEF.
2. **kernel_filter:** Procesamiento de restricciones para controladores en modo kernel que exponen superficies IOCTL.
3. **loldrivers_filter:** Excluye entidades conocidas catalogadas en loldrivers.io.
4. **decompile:** Ejecuta la descompilación de Ghidra sin interfaz gráfica.
5. **semgrep_scanner:** Análisis estático en masa sobre el código fuente en C exportado.
6. **pick_top_10:** Reducción heurística a los mejores candidatos.
7. **assess:** Inyección de promts en LLM y evaluación lógica.
