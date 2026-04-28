---
layout: default
title: Architecture Fondamentale
order: 2
---

## Architecture du Moteur

Le moteur d'orchestration de DeepZero fonctionne sur un graphe de traitement strictement directionnel défini par des [pipelines]({{ '/fr/reference/pipeline-yaml.html' | relative_url }}). Le moteur d'exécution garantit une [gestion de l'état]({{ '/fr/system/state-persistence.html' | relative_url }}) tolérante aux pannes et capable de reprendre l'exécution, tout en répartissant les opérations parallèles sur un pool de threads délimité ([`ThreadPoolExecutor`](https://docs.python.org/3/library/concurrent.futures.html#threadpoolexecutor)).

<div class="architecture-diagram" style="margin: 3rem 0;">
    <svg viewBox="0 0 800 400" style="width: 100%; height: auto; max-width: 800px;" xmlns="http://www.w3.org/2000/svg">
        <defs>
            <linearGradient id="flowGrad" x1="0%" y1="0%" x2="100%" y2="0%">
                <stop offset="0%" stop-color="var(--border)" />
                <stop offset="50%" stop-color="var(--text-tertiary)" />
                <stop offset="100%" stop-color="var(--border)" />
            </linearGradient>
            <pattern id="isoGridSmall" width="40" height="23.094" patternUnits="userSpaceOnUse" patternTransform="scale(1)">
                <path d="M 40 0 L 0 23.094 M 0 0 L 40 23.094 M 20 23.094 L 20 0" fill="none" stroke="var(--border)" stroke-width="0.5"/>
            </pattern>
        </defs>
        
        <rect width="100%" height="100%" fill="url(#isoGridSmall)" opacity="0.3"/>

        <!-- Ingest Node -->
        <g transform="translate(150, 200)">
            <path d="M 0 0 L 60 -30 L 120 0 L 60 30 Z" fill="var(--bg-primary)" stroke="var(--text-primary)" stroke-width="1.5" stroke-linejoin="round"/>
            <path d="M 0 0 L 0 40 L 60 70 L 120 40 L 120 0 L 60 30 Z" fill="var(--bg-secondary)" stroke="var(--text-primary)" stroke-width="1.5" stroke-linejoin="round"/>
            <path d="M 60 30 L 60 70" stroke="var(--text-primary)" stroke-width="1.5"/>
            <text x="60" y="-5" font-family="JetBrains Mono, monospace" font-size="12" font-weight="bold" text-anchor="middle" fill="var(--text-secondary)" transform="skewX(30) rotate(-30)">INGEST</text>
            <text x="60" y="30" font-family="Inter, sans-serif" font-size="10" text-anchor="middle" fill="var(--text-tertiary)" transform="skewX(30) rotate(-30)">1 → N</text>
        </g>

        <!-- Connecting Lines to Map -->
        <path d="M 210 170 L 250 150 L 300 150 L 350 125" fill="none" stroke="url(#flowGrad)" stroke-width="2" stroke-dasharray="6 6">
            <animate attributeName="stroke-dashoffset" from="100" to="0" dur="2s" repeatCount="indefinite" />
        </path>
        <path d="M 210 170 L 350 170" fill="none" stroke="url(#flowGrad)" stroke-width="2" stroke-dasharray="6 6">
            <animate attributeName="stroke-dashoffset" from="100" to="0" dur="2s" repeatCount="indefinite" />
        </path>
        <path d="M 210 170 L 250 190 L 300 190 L 350 215" fill="none" stroke="url(#flowGrad)" stroke-width="2" stroke-dasharray="6 6">
            <animate attributeName="stroke-dashoffset" from="100" to="0" dur="2s" repeatCount="indefinite" />
        </path>

        <!-- Map Nodes -->
        <g transform="translate(350, 90)">
            <path d="M 0 0 L 40 -20 L 80 0 L 40 20 Z" fill="var(--bg-primary)" stroke="var(--text-primary)" stroke-width="1.5" stroke-linejoin="round"/>
            <path d="M 0 0 L 0 20 L 40 40 L 80 20 L 80 0 L 40 20 Z" fill="var(--bg-secondary)" stroke="var(--text-primary)" stroke-width="1.5" stroke-linejoin="round"/>
            <path d="M 40 20 L 40 40" stroke="var(--text-primary)" stroke-width="1.5"/>
            <circle cx="40" cy="0" r="3" fill="var(--text-primary)"/>
            <text x="40" y="-10" font-family="JetBrains Mono, monospace" font-size="10" text-anchor="middle" fill="var(--text-secondary)" transform="skewX(30) rotate(-30)">MAP</text>
        </g>
        <g transform="translate(350, 160)">
            <path d="M 0 0 L 40 -20 L 80 0 L 40 20 Z" fill="var(--bg-primary)" stroke="var(--text-primary)" stroke-width="1.5" stroke-linejoin="round"/>
            <path d="M 0 0 L 0 20 L 40 40 L 80 20 L 80 0 L 40 20 Z" fill="var(--bg-secondary)" stroke="var(--text-primary)" stroke-width="1.5" stroke-linejoin="round"/>
            <path d="M 40 20 L 40 40" stroke="var(--text-primary)" stroke-width="1.5"/>
            <circle cx="40" cy="0" r="3" fill="var(--text-primary)"/>
            <text x="40" y="-10" font-family="JetBrains Mono, monospace" font-size="10" text-anchor="middle" fill="var(--text-secondary)" transform="skewX(30) rotate(-30)">MAP</text>
        </g>
        <g transform="translate(350, 230)">
            <path d="M 0 0 L 40 -20 L 80 0 L 40 20 Z" fill="var(--bg-primary)" stroke="var(--text-primary)" stroke-width="1.5" stroke-linejoin="round"/>
            <path d="M 0 0 L 0 20 L 40 40 L 80 20 L 80 0 L 40 20 Z" fill="var(--bg-secondary)" stroke="var(--text-primary)" stroke-width="1.5" stroke-linejoin="round"/>
            <path d="M 40 20 L 40 40" stroke="var(--text-primary)" stroke-width="1.5"/>
            <circle cx="40" cy="0" r="3" fill="var(--text-primary)"/>
            <text x="40" y="-10" font-family="JetBrains Mono, monospace" font-size="10" text-anchor="middle" fill="var(--text-secondary)" transform="skewX(30) rotate(-30)">MAP</text>
        </g>

        <!-- Connecting Lines to Reduce -->
        <path d="M 430 90 L 480 115 L 520 115 L 560 170" fill="none" stroke="url(#flowGrad)" stroke-width="2" stroke-dasharray="6 6">
            <animate attributeName="stroke-dashoffset" from="100" to="0" dur="2s" repeatCount="indefinite" />
        </path>
        <path d="M 430 160 L 560 170" fill="none" stroke="url(#flowGrad)" stroke-width="2" stroke-dasharray="6 6">
            <animate attributeName="stroke-dashoffset" from="100" to="0" dur="2s" repeatCount="indefinite" />
        </path>
        <path d="M 430 230 L 480 205 L 520 205 L 560 170" fill="none" stroke="url(#flowGrad)" stroke-width="2" stroke-dasharray="6 6">
            <animate attributeName="stroke-dashoffset" from="100" to="0" dur="2s" repeatCount="indefinite" />
        </path>

        <!-- Reduce Node -->
        <g transform="translate(560, 180)">
            <path d="M 0 0 L 60 -30 L 120 0 L 60 30 Z" fill="var(--accent)" stroke="var(--bg-primary)" stroke-width="1.5" stroke-linejoin="round"/>
            <path d="M 0 0 L 0 40 L 60 70 L 120 40 L 120 0 L 60 30 Z" fill="var(--text-secondary)" stroke="var(--bg-primary)" stroke-width="1.5" stroke-linejoin="round"/>
            <path d="M 60 30 L 60 70" stroke="var(--bg-primary)" stroke-width="1.5"/>
            <text x="60" y="-5" font-family="JetBrains Mono, monospace" font-size="12" font-weight="bold" text-anchor="middle" fill="var(--bg-primary)" transform="skewX(30) rotate(-30)">REDUCE</text>
            <text x="60" y="30" font-family="Inter, sans-serif" font-size="10" text-anchor="middle" fill="var(--text-tertiary)" transform="skewX(30) rotate(-30)">N → M</text>
            
            <!-- Output stream -->
            <path d="M 60 10 L 90 -5" fill="none" stroke="var(--bg-primary)" stroke-width="2" stroke-dasharray="2 2"/>
            <path d="M 70 20 L 100 5" fill="none" stroke="var(--bg-primary)" stroke-width="2" stroke-dasharray="2 2"/>
        </g>
    </svg>
</div>

### Cycles de Vie des Composants

Le modèle de données transite à travers ces abstractions à mesure qu'un échantillon progresse :

1. **`Sample`** : La structure de base produite par un `IngestProcessor`. Elle relie un `source_path` physique à un `sample_id` unique (généralement un hachage SHA-256 ou un UUID déterministe) et initialise le dictionnaire `data` de l'échantillon.
2. **`SampleState`** : L'enregistrement persistant maintenu par le `StateStore`. Il suit le `verdict` de l'échantillon (`PENDING`, `ACTIVE`, `FILTERED`, `FAILED`, `COMPLETED`) et maintient un historique (`history`) qui associe les instances de `StageOutput` à chaque processeur.
3. **`ProcessorEntry`** : L'interface générée dynamiquement, économe en mémoire, transmise aux processeurs Map/BulkMap/Reduce. Elle injecte un mécanisme de chargement différé (lazy-load via `_store`) qui ne récupère les données d'exécution historiques du disque que lorsque `.history` ou `.upstream_data()` est accédé.

### Paradigmes de Traitement

Les processeurs dictent la topologie d'exécution et les modèles de concurrence. Tous héritent de la classe de base `Processor`, exposant les hooks de cycle de vie : `validate()`, `setup()`, `process()`, et `teardown()`. Pour des instructions sur la façon d'écrire les vôtres, consultez [Construire des Processeurs Personnalisés]({{ '/fr/extensibility/building-custom.html' | relative_url }}).

#### `IngestProcessor` (1 → N)
- **Signature de Type :** `process(ctx: ProcessorContext, target: Path) -> list[Sample]`
- **Concurrence :** Synchrone. S'exécute précisément une fois par exécution de pipeline.
- **Rôle :** Génère le corpus initial. Aucune donnée en amont n'existe avant Ingest.

#### `MapProcessor` (1 → 1)
- **Signature de Type :** `process(ctx: ProcessorContext, entry: ProcessorEntry) -> ProcessorResult`
- **Concurrence :** Déploiement via des threads (Threaded fan-out). Configuré via le champ `parallel:` dans le YAML du pipeline.
- **Contraintes :** Doit être strictement thread-safe (sécurisé pour les threads). Évitez les états mutables partagés.

#### `BulkMapProcessor` (N → N)
- **Signature de Type :** `process(ctx: ProcessorContext, entries: list[ProcessorEntry]) -> list[ProcessorResult]`
- **Concurrence :** Exécution synchrone sur un sous-ensemble ou la totalité des échantillons actifs.
- **Rôle :** Optimise les appels de processus externes (par exemple, le lancement d'un outil JVM monolithique ou un scan en lot Semgrep) pour amortir les coûts de démarrage importants sur de multiples échantillons. Les sorties doivent être strictement indexées pour correspondre à la liste d'entrée `entries`.

#### `ReduceProcessor` (N → M)
- **Signature de Type :** `process(ctx: ProcessorContext, entries: list[ProcessorEntry]) -> list[str]`
- **Concurrence :** Barrière de synchronisation globale. Suspend l'exécution des threads jusqu'à ce que tous les échantillons actifs atteignent cette étape.
- **Rôle :** Renvoie une liste ordonnée de chaînes `sample_id` définissant quels échantillons survivent. Tout ID d'échantillon absent de la liste renvoyée est définitivement marqué avec `SampleStatus.FILTERED`.
