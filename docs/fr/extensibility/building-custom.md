---
layout: default
title: Construire des Processeurs
order: 2
---

## Construire des Processeurs Personnalisés

La logique personnalisée est injectée dans DeepZero en créant des sous-classes des abstractions typées fournies dans `deepzero.engine.stage`. Consultez l'[Architecture Fondamentale]({{ '/fr/overview/architecture.html' | relative_url }}) pour comprendre comment ces étapes correspondent aux phases d'exécution.

### Contexte du Processeur (`ProcessorContext`)

L'objet `ctx` injecté dans chaque hook de cycle de vie fournit un contexte systémique et des utilitaires :
- `ctx.pipeline_dir` : Répertoire racine du pipeline appelé, utile pour résoudre les modèles ou ensembles de règles locaux.
- `ctx.global_config` : `TypedDict` contenant les `settings` au niveau du pipeline, les `knowledge` (connaissances) et le `model` configuré.
- `ctx.llm` : Une instance de proxy générique (implémentant `LLMProtocol`) liée à [LiteLLM](https://github.com/BerriAI/litellm), abstraiant les API des fournisseurs avec une fonction native de temporisation et de réessai (backoff/retry).
- `ctx.log` : Instance `logging.Logger` préconfigurée et partitionnée.

### Hooks d'Exécution

Les processeurs implémentent des hooks de cycle de vie spécifiques appelés par le moteur :

1. **`validate(ctx: ProcessorContext) -> list[str]`** : Invoqué lors de la validation initiale du schéma (via `deepzero validate` ou avant l'exécution). Retourne une liste de chaînes d'erreur en cas d'échec de dépendances (ex. binaires manquants, YAMLs non analysables).
2. **`setup(global_config: dict) -> None`** : Exécuté exactement une fois avant l'activation du pool de threads.
3. **`process(...)`** : L'opération principale. La signature varie selon le `ProcessorType`.
4. **`teardown() -> None`** : Exécuté à la fin du pipeline ou en cas d'interruption fatale.

### Définir la Configuration du Processeur

Utilisez une `@dataclass` embarquée nommée `Config` pour définir strictement et valider les configurations YAML acceptées. Le moteur analyse le dictionnaire du [YAML du Pipeline]({{ '/fr/reference/pipeline-yaml.html' | relative_url }}) et instancie votre objet `Config`, en développant complètement les `${ENV_VARS}` automatiquement à l'aide des [`dataclasses`](https://docs.python.org/3/library/dataclasses.html) Python standards.

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
        # Récupérer les données émises par un IngestProcessor en amont
        sha = entry.upstream_data("discover", "sha256", default="UNKNOWN")
        
        # ProcessorEntry se lie à une sandbox isolée par échantillon
        out_file = entry.sample_dir / "heuristics.json"
        out_file.write_text('{"entropy": 7.1}')
        
        # ProcessorResult détermine le routage
        if self.config.target_arch != "x86_64":
            return ProcessorResult.filter(reason="unsupported_arch")
            
        return ProcessorResult.ok(
            artifacts={"heuristics": "heuristics.json"},
            data={"analyzed": True, "entropy_ok": True}
        )
```

### Résultats de l'Exécution (`ProcessorResult`)

Les processeurs Map/BulkMap doivent renvoyer un `ProcessorResult` strictement formaté :
- **`.ok(data={...}, artifacts={...})`** : Signale que l'exécution est `COMPLETED` (Terminée). Le dictionnaire `data` est placé dans l'espace de noms du bloc historique du processeur. `artifacts` associe des clés à des chemins de fichiers relatifs.
- **`.filter(reason="...", data={...})`** : Interrompt silencieusement le traitement de l'échantillon. `SampleState.verdict` mute en `FILTERED`.
- **`.fail(error="...")`** : Interrompt le traitement en raison d'une erreur fatale et inattendue. `SampleState.verdict` mute en `FAILED`.

### Accéder aux Données en Amont

Les processeurs s'appuient intrinsèquement sur les artefacts et les données générés par leurs prédécesseurs. L'interface `ProcessorEntry` expose des méthodes d'aide à chargement différé (lazy-loaded) pour récupérer ces données de manière transparente :

```python
# Extraction raccourcie d'un champ spécifique (avec repli)
sha = entry.upstream_data("discover", "sha256", default="")

# Extraction complète de l'objet StageOutput d'une étape précédente
output = entry.upstream("scan")
findings = output.data.get("finding_count", 0)
json_file = output.artifacts.get("findings_file")
```

### Classes de Base

En fonction des exigences de topologie de votre pipeline, étendez la classe de base appropriée :

| Classe de Base | Type de Processeur | Signature de `process()` |
|-----------|---------------|----------------------|
| `IngestProcessor` | `ingest` | `(ctx, target: Path) → list[Sample]` |
| `MapProcessor` | `map` | `(ctx, entry: ProcessorEntry) → ProcessorResult` |
| `BulkMapProcessor` | `bulk_map` | `(ctx, entries: list[ProcessorEntry]) → list[ProcessorResult]` |
| `ReduceProcessor` | `reduce` | `(ctx, entries: list[ProcessorEntry]) → list[str]` |
