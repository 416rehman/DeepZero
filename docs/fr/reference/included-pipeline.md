---
layout: default
title: Pipeline LOLDrivers
order: 3
---

## Référence du Pipeline LOLDrivers

Un pipeline de référence BYOVD (Bring Your Own Vulnerable Driver) est maintenu dans `pipelines/loldrivers/`.

1. **discover:** Ingestion de PE et analyse des en-têtes LIEF.
2. **kernel_filter:** Traitement des contraintes sur les pilotes en mode noyau exposant des surfaces IOCTL.
3. **loldrivers_filter:** Exclut les entités connues répertoriées via loldrivers.io.
4. **decompile:** Exécute la décompilation Ghidra sans interface graphique (headless).
5. **semgrep_scanner:** Analyse statique en masse sur le code source C exporté.
6. **pick_top_10:** Réduction heuristique au niveau des meilleurs candidats.
7. **assess:** Injection de prompt LLM et évaluation logique.
