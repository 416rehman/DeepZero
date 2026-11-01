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
- `ctx.global_config` : `TypedDict` contenant les `settings` au niveau du pipeline, les `knowledge` (connaissances), le `model` configuré et `pipeline_dir`, le répertoire depuis lequel le pipeline a été chargé, sous forme de chaîne. Cette dernière clé existe parce que `setup()` reçoit cette configuration et aucun contexte : sans elle, une valeur de configuration désignant un fichier livré avec le pipeline se résoudrait par rapport au répertoire de travail. `ctx.get_setting(key)` et `ctx.get_knowledge(key)` en sont des raccourcis.
- `ctx.llm` : Une instance de proxy générique (implémentant `LLMProtocol`) dotée d'une fonction native de temporisation et de réessai (backoff/retry), ou `None` lorsque le pipeline ne configure aucun modèle. Le backend qu'elle pilote est résolu à partir de la chaîne `model` du pipeline : un processeur appelant `ctx.llm.complete()` fonctionne donc de la même manière avec une clé d'API et avec une CLI d'agent locale. Consultez [Choisir un Modèle]({{ '/fr/reference/pipeline-yaml.html' | relative_url }}).
- `ctx.log` : Instance `logging.Logger` préconfigurée et partitionnée.
- `ctx.progress` : Hook de remontée de progression, `update(amount=, total=, description=)`, afin qu'une étape d'ingestion ou de traitement en masse de longue durée montre qu'elle avance sur le tableau de bord au lieu de paraître figée.
- `ctx.shutdown_event` : Un `threading.Event`, positionné lorsque l'exécution est interrompue. Un processeur effectuant un travail long doit le consulter et retourner par anticipation plutôt que d'être tué en pleine écriture.
- `ctx.conclude(**fields)` : Enregistre une détection portant sur le corpus plutôt que sur un échantillon en particulier. Certaines questions n'ont de réponse qu'à l'échelle de l'ensemble : quel modèle se trouve derrière un point d'accès, combien de bugs distincts représente un tas de plantages. Les champs sont fusionnés dans la `conclusion` de l'exécution et celle-ci est enregistrée dans la foulée : une exécution interrompue conserve donc ce qu'elle avait déjà établi.

Le moteur ne raccorde `conclude` à un véritable écrivain que pour une étape `reduce` ou `bulk_map`, celles qui voient tous les échantillons en un seul appel :

```python
class ModelFingerprint(ReduceProcessor):
    def process(self, ctx: ProcessorContext, entries: list[ProcessorEntry]) -> list[str]:
        ctx.conclude(headline="every probe answers as the same model family", probes=len(entries))
        return [e.sample_id for e in entries]
```

Dans une étape map ou ingest, l'appel journalise que `ctx.conclude()` n'est disponible que pour une étape reduce ou bulk_map et que l'appel a été ignoré, puis ne fait rien. Une voie par échantillon répartie sur un pool de threads ne peut pas parler au nom du corpus sans se concurrencer elle-même : le dernier échantillon terminé l'emporterait, et le perdant ne saurait jamais qu'il a été écrasé.

### Hooks d'Exécution

Les processeurs implémentent des hooks de cycle de vie spécifiques appelés par le moteur :

1. **`validate(ctx: ProcessorContext) -> list[str]`** : Invoqué lors de la validation initiale du schéma (via `deepzero validate` ou avant l'exécution). Retourne une liste de chaînes d'erreur en cas d'échec de dépendances (ex. binaires manquants, YAMLs non analysables). Le contexte fourni ici est réduit : `ctx.global_config` ne porte que `settings`, `knowledge` et `model`, sans clé `pipeline_dir`, et `ctx.llm` vaut `None` car aucun fournisseur n'a encore été construit. Une vérification ayant besoin de l'un ou de l'autre lira le pipeline de travers. `ctx.pipeline_dir` est en revanche renseigné : résolvez donc par ce biais les fichiers voisins du pipeline.
2. **`setup(global_config: dict) -> None`** : Exécuté exactement une fois avant l'activation du pool de threads.
3. **`process(...)`** : L'opération principale. La signature varie selon le `ProcessorType`.
4. **`teardown() -> None`** : Exécuté à la fin du pipeline ou en cas d'interruption fatale.

Un cinquième mérite d'être redéfini sur un processeur Map coûteux par échantillon :

5. **`max_parallelism() -> int | None`** : Un plafond sur la concurrence automatique. Il ne s'applique que lorsque le YAML de l'étape déclare `parallel: 0` ; tout `parallel: N` supérieur à zéro est honoré tel qu'il est écrit, avant même que le plafond ou le réglage `max_workers` ne soient consultés. Renvoyez un entier lorsque chaque échantillon coûte une JVM, un conteneur ou quelques gigaoctets de mémoire, afin qu'une étape ayant demandé à s'adapter automatiquement ne puisse pas prendre un travailleur par cœur. `None`, la valeur par défaut, signifie aucun plafond. Omettre `parallel:` n'équivaut pas à écrire `parallel: 0` : une étape qui ne le nomme pas est chargée avec 4, ce qui compte comme une valeur explicite, et le plafond ne l'atteint donc jamais.

### Ce que Porte l'Instance du Processeur

`ctx` décrit l'exécution. L'objet processeur, lui, porte ce qui appartient à l'étape :
- `self.config` : la dataclass `Config` analysée, ou le dictionnaire YAML brut lorsque le processeur ne déclare aucune `Config`.
- `self.spec` : la `StageSpec` à partir de laquelle cette instance a été construite : son nom, son bloc de configuration, `parallel`, `on_failure`, `max_retries` et `timeout`.
- `self.log` : un logger partitionné sous le nom de l'étape.
- `self.global_config` : le même `GlobalConfig` que porte `ctx`, positionné par le moteur avant l'exécution de `setup()`.
- `self.processor_dir` : le répertoire contenant le fichier `.py` propre à ce processeur, pour les scripts, modèles et fichiers de règles livrés à côté de lui. Ce n'est pas `ctx.pipeline_dir` : un pipeline peut nommer un processeur qui vit tout à fait ailleurs, et les deux désignent alors des endroits différents.
- `self.cache_dir` : un répertoire persistant situé en `./.cache/<nom de l'étape>`, créé au premier accès. Rien dans le moteur ne le vide : il survit donc d'une exécution à l'autre et c'est là que doivent aller les téléchargements et tout autre travail trop coûteux à refaire.

### Définir la Configuration du Processeur

Déclarez la configuration YAML qu'accepte un processeur au moyen d'une `@dataclass` embarquée nommée `Config`. Le moteur développe `${VAR}` et `${VAR:-default}` dans le [YAML du Pipeline]({{ '/fr/reference/pipeline-yaml.html' | relative_url }}) et instancie votre `Config` à partir du bloc `config` de l'étape, à l'aide des [`dataclasses`](https://docs.python.org/3/library/dataclasses.html) Python standards.

Déclarer les champs ne revient pas à les imposer. Une clé que la dataclass ne déclare pas est journalisée comme n'étant pas lue par ce processeur, mise en regard des noms qu'il accepte, puis abandonnée, et l'exécution se poursuit ; `limit` est lu par le moteur lui-même et échappe à cet avertissement. Rien ne vérifie les types. Un `${VAR}` non défini se développe en chaîne vide plutôt que de rester littéral : une variable d'environnement manquante arrive donc sous la forme d'un champ présent et vide plutôt que d'une erreur. Donnez une valeur par défaut à chaque champ et faites les vraies vérifications dans `validate()`, qui s'exécute avant que le moindre échantillon ne soit touché.

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
        # Récupérer les données émises par un IngestProcessor en amont
        sha = entry.upstream_data("discover", "sha256", default="UNKNOWN")

        # entry.source_path est la chose analysée : ce que l'étape d'ingestion
        # a enregistré pour cet échantillon, et la seule prise que vous ayez dessus
        entropy = self._shannon_entropy(entry.source_path.read_bytes())

        # ProcessorEntry se lie à une sandbox isolée par échantillon
        out_file = entry.sample_dir / "heuristics.json"
        out_file.write_text(json.dumps({"sha256": sha, "entropy": entropy}))

        # ProcessorResult détermine le routage
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

### Résultats de l'Exécution (`ProcessorResult`)

Les processeurs Map/BulkMap doivent renvoyer un `ProcessorResult` strictement formaté :
- **`.ok(data={...}, artifacts={...})`** : Signale que l'exécution est `COMPLETED` (Terminée). Le dictionnaire `data` est placé dans l'espace de noms du bloc historique du processeur. `artifacts` associe des clés à des chemins de fichiers relatifs.
- **`.filter(reason="...", data={...})`** : Interrompt silencieusement le traitement de l'échantillon. `SampleState.verdict` mute en `FILTERED`.
- **`.fail(error="...")`** : Interrompt le traitement en raison d'une erreur fatale et inattendue. `SampleState.verdict` mute en `FAILED`.
- **`.timed_out(budget)`** : Le travail a manqué de temps plutôt que mal tourné. `SampleState.verdict` mute en `TIMED_OUT`, et le budget voyage avec lui afin que le rapport puisse indiquer ce qu'il faudrait lui accorder à la place. Renvoyez ceci depuis un processeur qui applique son propre budget ; le `timeout:` au niveau de l'étape le produit de lui-même.

Un processeur Map peut également redéfinir **`should_skip(ctx, entry) -> str | None`** et renvoyer une raison pour déclarer le travail déjà fait, typiquement parce que son propre fichier de sortie est déjà sur le disque. Un échantillon ainsi ignoré compte comme réussi et poursuit vers l'aval. Enregistrez cette sortie comme artefact lorsque vous procédez ainsi : `deepzero run --redo` supprime les artefacts enregistrés précisément pour qu'un fichier mis en cache ne puisse pas être réadopté, et un fichier que l'exécution n'a jamais enregistré survit à l'état qui le décrit.

Testez `entry.cache_is_valid` autant que le chemin, jamais le chemin seul :

```python
def should_skip(self, ctx: ProcessorContext, entry: ProcessorEntry) -> str | None:
    if entry.cache_is_valid and (entry.sample_dir / "out.json").exists():
        return "cached"
    return None
```

`cache_is_valid` vaut `False` lorsque le fichier présent sur le disque provient d'un prompt, d'un ensemble de règles ou d'une configuration qui ont changé depuis : le moteur compare l'empreinte des entrées enregistrée lors de l'exécution précédente avec celle que produisent aujourd'hui les entrées de cette étape. Un `should_skip` qui ne teste que `.exists()` réadopte une sortie répondant à une question que le pipeline ne pose plus. L'étape LLM intégrée et le scanneur Semgrep fourni prennent tous deux cette précaution là où ils adoptent un fichier existant.

### Déclarer ce que les Étapes Suivantes Peuvent Utiliser

Les clés `data` et les artefacts d'un processeur deviennent disponibles pour les prompts des étapes qui s'exécutent après lui. Déclarez ces noms dans `provides` afin que `deepzero validate` puisse vérifier un prompt avant une exécution, au lieu de laisser un nom inconnu ne rien produire au rendu :

```python
class Decompiler(MapProcessor):
    description = "Static heuristics extraction"
    provides = (
        "device_name",                    # une clé que ce processeur place dans data
        "decompiled_dispatch_ioctl_c",    # l'artefact decompiled/dispatch_ioctl.c
    )
```

Un artefact est nommé d'après son chemin, séparateurs et extension incorporés au nom ; `template_key_for_artifact`, dans `engine/stage.py`, est l'unique règle utilisée à la fois pour le rendu et pour la validation. Listez également les noms qui ne sont enregistrés qu'occasionnellement : un prompt est censé tolérer leur absence. Consultez [Valeurs des Prompts]({{ '/fr/reference/pipeline-yaml.html' | relative_url }}) pour savoir ce que reçoit un prompt.

### Ce que Porte une Entrée (`ProcessorEntry`)

Tout processeur map, bulk_map et reduce reçoit des entrées plutôt que des échantillons bruts :
- `entry.sample_id` : l'identifiant unique de l'échantillon, et la clé sous laquelle son état est stocké.
- `entry.source_path` : un `Path` vers la chose analysée, quoi que l'étape d'ingestion ait enregistré pour cet échantillon. C'est la seule prise qu'un processeur map ait sur son entrée.
- `entry.filename` : le nom d'affichage, utilisé dans les journaux et les rapports.
- `entry.sample_dir` : le répertoire de travail isolé de cet échantillon, où doit aller la sortie.
- `entry.cache_is_valid` : indique si une sortie déjà présente dans `sample_dir` a été produite avec les entrées actuelles de cette étape, comme décrit plus haut à propos de `should_skip`.

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
