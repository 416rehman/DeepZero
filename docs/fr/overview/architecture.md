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
2. **`SampleState`** : L'enregistrement persistant maintenu par le `StateStore`. Il suit le `verdict` de l'échantillon (`PENDING`, `ACTIVE`, `FILTERED`, `FAILED`, `TIMED_OUT`) et maintient un historique (`history`) qui associe les instances de `StageOutput` à chaque processeur. Un échantillon qui atteint la fin du pipeline reste `ACTIVE`. `FILTERED`, `FAILED` et `TIMED_OUT` sont les verdicts qui ont sorti un échantillon de l'exécution : arriver au bout, c'est donc n'en avoir jamais reçu aucun. `TIMED_OUT` est tenu à l'écart de `FAILED` parce qu'il ne dit rien de l'échantillon, et parce que c'est la seule issue qu'un budget plus long puisse changer.
3. **`ProcessorEntry`** : L'interface générée dynamiquement, économe en mémoire, transmise aux processeurs Map/BulkMap/Reduce. Elle injecte un mécanisme de chargement différé (lazy-load via `_store`) qui ne récupère les données d'exécution historiques du disque que lorsque `.history` ou `.upstream_data()` est accédé. Elle porte également `cache_is_valid`, que tout processeur réadoptant sa propre sortie antérieure au lieu de refaire le travail se doit de consulter : `False` signifie que cette sortie a été produite à partir d'un prompt, d'un ensemble de règles ou d'une configuration qui ont changé depuis, et l'adopter reviendrait donc à rapporter la réponse à une question que plus personne ne pose.

Chaque `StageOutput` enregistre aussi un `input_digest`, une empreinte du processeur, de sa
configuration et de tout fichier que cette configuration nomme : un prompt, un ensemble de
règles, un script d'analyse. Une exécution reprise recalcule l'empreinte une fois par étape
et la compare à celle enregistrée : une étape dont les entrées ont changé est donc relancée,
tandis que celles qui tiennent toujours sont restaurées depuis le disque. Les résultats
écrits avant que les empreintes ne soient enregistrées portent une empreinte vide et sont
retenus plutôt que refaits, car jeter un corpus dont la production a pu prendre des heures,
au nom d'une question qu'on ne peut pas lui poser, est la pire supposition.

### Paradigmes de Traitement

Les processeurs dictent la topologie d'exécution et les modèles de concurrence. Tous héritent de la classe de base `Processor`, exposant les hooks de cycle de vie : `validate()`, `setup()`, `process()`, et `teardown()`. Pour des instructions sur la façon d'écrire les vôtres, consultez [Construire des Processeurs Personnalisés]({{ '/fr/extensibility/building-custom.html' | relative_url }}).

#### `IngestProcessor` (1 → N)
- **Signature de Type :** `process(ctx: ProcessorContext, target: Path) -> list[Sample]`
- **Concurrence :** Synchrone. S'exécute une seule fois, et seulement lorsque le répertoire de l'exécution ne contient encore aucun échantillon. Une exécution reprise liste d'abord ce qui se trouve déjà sur le disque et, si elle y trouve quoi que ce soit, journalise qu'elle saute l'ingestion et n'appelle jamais le processeur.
- **Rôle :** Génère le corpus initial. Aucune donnée en amont n'existe avant Ingest.
- **Conséquence :** Parce qu'une reprise ne réingère jamais, tout ce qui est ajouté à la cible après la première exécution n'est pas repris en relançant le pipeline. `--clean` jette le corpus et le recommence, et une cible différente constitue un corpus différent doté de son propre répertoire d'exécution ; l'un comme l'autre ingèrent à neuf. `--redo` sur l'étape d'ingestion, non : il oublie ce que cette étape a enregistré, mais l'état d'échantillon sur lequel il l'a oublié est toujours sur le disque, et c'est précisément la présence d'un état d'échantillon qui fait d'une exécution une reprise.

#### `MapProcessor` (1 → 1)
- **Signature de Type :** `process(ctx: ProcessorContext, entry: ProcessorEntry) -> ProcessorResult`
- **Concurrence :** Déploiement via des threads (Threaded fan-out). Configuré via le champ `parallel:` dans le YAML du pipeline. `parallel: 0` s'adapte automatiquement, borné par `max_workers` et par ce que le processeur renvoie depuis `max_parallelism()`.
- **Contraintes :** Doit être strictement thread-safe (sécurisé pour les threads). Évitez les états mutables partagés.
- **Budget :** `timeout:` borne le temps que l'étape passe à attendre un échantillon, pas la durée du travail. Le thread de travail est abandonné, jamais tué : un processeur qui démarre un processus externe devrait donc borner ce processus lui-même.

#### `BulkMapProcessor` (N → N)
- **Signature de Type :** `process(ctx: ProcessorContext, entries: list[ProcessorEntry]) -> list[ProcessorResult]`
- **Concurrence :** Exécution synchrone sur un sous-ensemble ou la totalité des échantillons actifs.
- **Rôle :** Optimise les appels de processus externes (par exemple, le lancement d'un outil JVM monolithique ou un scan en lot Semgrep) pour amortir les coûts de démarrage importants sur de multiples échantillons. Les sorties doivent être strictement indexées pour correspondre à la liste d'entrée `entries`.
- **Détections sur le corpus :** Reçoit tous les échantillons en attente en un seul appel : `ctx.conclude()` y est donc actif.

#### `ReduceProcessor` (N → M)
- **Signature de Type :** `process(ctx: ProcessorContext, entries: list[ProcessorEntry]) -> list[str]`
- **Concurrence :** Barrière de synchronisation globale. Suspend l'exécution des threads jusqu'à ce que tous les échantillons actifs atteignent cette étape.
- **Rôle :** Renvoie une liste ordonnée de chaînes `sample_id` définissant quels échantillons survivent. Tout ID d'échantillon absent de la liste renvoyée est définitivement marqué avec `SampleStatus.FILTERED`.
- **Détections sur le corpus :** Voit tous les échantillons actifs en un seul appel : `ctx.conclude()` y est donc actif.

### Le Contrat de Sortie

Quoi que fasse un processeur, il enregistre les trois mêmes choses : `data`, un dictionnaire arbitraire cloisonné par espace de noms ; `artifacts`, une association entre une étiquette et un chemin de fichier relatif ; et un statut. Ce contrat est délibérément indépendant de tout domaine, et c'est sur lui que repose tout ce qui se situe en aval du moteur.

Une étape qui voit le corpus entier d'un seul coup peut enregistrer une chose de plus. `ctx.conclude(**fields)` consigne une détection portant sur le corpus plutôt que sur un échantillon en particulier : quel modèle se trouve derrière un point d'accès, combien de bugs distincts représente un tas de plantages, si une portée est correctement configurée. Les champs sont fusionnés dans `RunState.conclusion` au sein de `run.json` et écrits à l'instant même où ils sont produits : une exécution interrompue conserve donc la conclusion à laquelle elle était déjà parvenue. Dans une étape map, l'appel ne fait rien et en journalise la raison : cette voie s'exécute une fois par échantillon sur un pool de threads, et plusieurs d'entre elles écrivant un verdict sur le corpus formeraient une compétition dont le vainqueur serait le dernier échantillon terminé.

Le [rapport]({{ '/fr/reference/cli.html' | relative_url }}) en est la conséquence la plus visible. Il s'agit d'une projection de l'état persistant, et non d'une étape du pipeline : il lit les mêmes `data` et `artifacts` que n'importe quel processeur aurait pu lire. C'est pourquoi une chasse aux pilotes, un audit de code source ou n'importe quoi d'autre s'affichent sans que le code du rapport sache de quoi il s'agit. Un pipeline ne fournit que le vocabulaire, et celui-ci est un [bloc de YAML]({{ '/fr/reference/pipeline-yaml.html' | relative_url }}) plutôt que du code.

Comme le rapport ne contient rien que le répertoire d'exécution ne contienne déjà, il peut être construit pendant qu'une exécution se déroule, reconstruit après avoir été supprimé, et reconstruit encore pour une exécution terminée depuis des semaines. C'est cette même propriété qui rend la couche LLM interchangeable : un backend est sélectionné à partir de la chaîne `model` du pipeline, et aucun processeur, aucune étape et aucun fichier d'état ne sait lequel a répondu.
