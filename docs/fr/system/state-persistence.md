---
layout: default
title: Persistance de l'État
order: 1
---

## Sous-système de Persistance

L'intégrité des données est gérée par le `StateStore` (défini dans `engine/state.py`). Les opérations s'exécutant sur le système de fichiers sont fortement protégées contre la corruption, même en cas de SIGKILL ou d'interruption au niveau du système d'exploitation, via des méthodologies strictes d'échange atomique (atomic swapping).

<div class="architecture-diagram" style="margin: 3rem 0;">
    <svg viewBox="0 0 800 250" style="width: 100%; height: auto; max-width: 800px;" xmlns="http://www.w3.org/2000/svg">
        <defs>
            <pattern id="isoGridState" width="40" height="23.094" patternUnits="userSpaceOnUse" patternTransform="scale(1)">
                <path d="M 40 0 L 0 23.094 M 0 0 L 40 23.094 M 20 23.094 L 20 0" fill="none" stroke="var(--border)" stroke-width="0.5"/>
            </pattern>
        </defs>

        <rect width="100%" height="100%" fill="url(#isoGridState)" opacity="0.3"/>
        
        <!-- Memory Node -->
        <g transform="translate(100, 120)">
            <rect x="0" y="-40" width="120" height="80" fill="var(--bg-primary)" stroke="var(--text-primary)" stroke-width="2" rx="8"/>
            <text x="60" y="-5" font-family="JetBrains Mono, monospace" font-size="14" font-weight="bold" text-anchor="middle" fill="var(--text-primary)">Mémoire</text>
            <text x="60" y="15" font-family="Inter, sans-serif" font-size="12" text-anchor="middle" fill="var(--text-tertiary)">SampleState</text>
        </g>

        <!-- Path to Temp -->
        <path d="M 220 120 L 320 120" fill="none" stroke="var(--text-tertiary)" stroke-width="2" stroke-dasharray="6 6"/>
        <text x="270" y="110" font-family="Inter, sans-serif" font-size="12" text-anchor="middle" fill="var(--text-secondary)">Sérialisation</text>
        
        <!-- Temp Node -->
        <g transform="translate(320, 120)">
            <rect x="0" y="-40" width="140" height="80" fill="var(--bg-secondary)" stroke="var(--border)" stroke-width="2" stroke-dasharray="4 4" rx="8"/>
            <text x="70" y="-5" font-family="JetBrains Mono, monospace" font-size="14" font-weight="bold" text-anchor="middle" fill="var(--text-secondary)">state.tmp</text>
            <text x="70" y="15" font-family="Inter, sans-serif" font-size="12" text-anchor="middle" fill="var(--text-tertiary)">Tampon</text>
        </g>
        
        <!-- Path to Final -->
        <path d="M 460 120 L 580 120" fill="none" stroke="var(--accent)" stroke-width="3"/>
        <circle cx="0" cy="0" r="5" fill="var(--accent)">
            <animateMotion path="M 460 120 L 580 120" dur="1.5s" repeatCount="indefinite" />
        </circle>
        <text x="520" y="110" font-family="Inter, sans-serif" font-size="12" font-weight="bold" text-anchor="middle" fill="var(--accent)">os.replace</text>
        <text x="520" y="140" font-family="Inter, sans-serif" font-size="10" text-anchor="middle" fill="var(--text-tertiary)">Échange Atomique</text>
        
        <!-- Final Node -->
        <g transform="translate(580, 120)">
            <rect x="-10" y="-30" width="120" height="80" fill="var(--bg-primary)" stroke="var(--border)" stroke-width="1" rx="4"/>
            <rect x="-5" y="-35" width="120" height="80" fill="var(--bg-primary)" stroke="var(--border)" stroke-width="1" rx="4"/>
            <rect x="0" y="-40" width="120" height="80" fill="var(--bg-primary)" stroke="var(--text-primary)" stroke-width="2" rx="4"/>
            <text x="60" y="-5" font-family="JetBrains Mono, monospace" font-size="14" font-weight="bold" text-anchor="middle" fill="var(--text-primary)">state.json</text>
            <text x="60" y="15" font-family="Inter, sans-serif" font-size="12" text-anchor="middle" fill="var(--text-tertiary)">Persistant</text>
        </g>
    </svg>
</div>

### Échanges Atomiques (`atomic_replace`)

Au lieu d'écrire directement dans les artefacts attendus (par ex., `state.json`), la couche de persistance rassemble les données dans des tampons temporaires `.tmp`. Le tampon reprend le nom de la destination en remplaçant son suffixe plutôt qu'en le prolongeant : `state.json` est donc préparé sous le nom `state.tmp`. Une fois la sérialisation terminée, une opération `os.replace` écrase de force l'inode atomique de destination. Un mécanisme de réessai avec temporisation (retry-backoff) intercepte activement les verrous `PermissionError` déclenchés par les heuristiques EDR/Antivirus de l'hôte lors de l'analyse des binaires nouvellement créés.

### Versionnage des Schémas

L'état des échantillons est la partie qui est à la fois marquée et contrôlée. `state.json` est
écrit avec un champ `_version` portant la `STATE_VERSION` interne, et au chargement tout ce qui
est plus ancien est refusé : lire un JSON v1 sous un environnement d'exécution v2 ne renvoie
rien du tout, au lieu d'induire des bugs de mutation imprévisibles en interprétant un
enregistrement sous un schéma qui ne le décrit plus.

Les deux autres fichiers ne sont pas contrôlés. `run_manifest.json` porte le même champ
`_version`, mais rien ne le relit, car le manifeste est un résumé dérivé réécrit à partir des
échantillons chaque fois qu'ils sont enregistrés. `run.json` n'est ni marqué ni vérifié : il est
chargé en filtrant le JSON à travers les propres noms de champs de `RunState` et en écartant
tout ce qui n'est pas reconnu, de sorte qu'un enregistrement écrit par une version antérieure se
charge avec les champs dont il dispose, le reste restant à ses valeurs par défaut.

### Hiérarchie de l'Espace de Travail

```text
work/<pipeline_name>/<corpus_key>/
├── run.json             # `RunState` sérialisé : métriques d'exécution, métadonnées du pipeline,
│                        #   la conclusion portant sur tout le corpus et le registre de vivacité de l'exécution
├── pipeline.yaml        # Instantané immuable de la configuration YAML du pipeline lors de l'initialisation
├── run_manifest.json    # Vue d'ensemble macro agrégée de tous les échantillons, lue par `status` et `interactive`
├── report/              # Rapport HTML consultable, reconstruit à mesure que les résultats arrivent
└── samples/
    └── <sample_id>/     # Bac à sable isolé (sandbox)
        ├── state.json   # `SampleState` sérialisé : Registre complet des cartes `StageOutput`
        ├── context.md   # Contexte LLM synthétisé, généré via `engine/context.py`
        └── ...          # Artefacts spécifiques au processeur
```

Deux parties de `RunState` méritent d'être nommées au-delà des métriques. `conclusion` porte une détection à propos du corpus plutôt qu'à propos d'un échantillon en particulier : quel modèle se trouve derrière un point d'accès, combien de bugs distincts représente un tas de plantages, si une portée est correctement configurée. Elle est écrite via `ctx.conclude(...)` par une étape qui voit tous les échantillons, et reste vide pour les nombreux pipelines dont toutes les réponses sont par échantillon. À côté d'elle, `host`, `pid`, `pid_token` et `heartbeat_at` enregistrent qui écrit l'exécution : un statut `running` n'est qu'une affirmation tant que le processus qui la porte n'a pas été vérifié, et une exécution tuée n'a jamais l'occasion de retirer cette affirmation elle-même ; ce sont donc ces quatre champs qui permettent à un autre processus de distinguer une exécution vivante d'une exécution abandonnée.

### Cloisonnement par Corpus

Le segment `<corpus_key>` est ce qui sépare deux cibles traitées par un même pipeline. Il est dérivé de la cible de l'exécution : son nom de base, augmenté d'une courte empreinte du chemin absolu résolu, de sorte qu'il soit à la fois lisible et sans ambiguïté. Sous Windows, la casse du chemin est d'abord normalisée, car `C:\Drivers` et `c:\drivers` désignent le même corpus.

Sans ce segment, pointer le même pipeline vers un second corpus reviendrait à reprendre dans le magasin d'échantillons du premier : des échantillons ne correspondant plus à rien sur le disque seraient considérés comme déjà analysés, et l'exécution rapporterait des résultats pour un corpus qui ne lui a jamais été soumis. Avec lui, chaque corpus dispose de son propre état, de son propre manifeste et de son propre rapport, et chacun reprend indépendamment.

Un même chemin résolu produit toujours la même clé : une nouvelle exécution retombe donc là où elle s'était arrêtée. Presque tout ce que contient ce répertoire est dérivé, et supprimer `report/` coûte normalement une reconstruction, pas une exécution.

Il y a une exception, et elle n'est pas récupérable. `report/marks.json` contient les marques de relecture : pour chaque échantillon, si un lecteur l'a examiné et l'a jugé tenant ou non tenant, ainsi qu'une note. C'est ce que le lecteur a vérifié, ce qu'aucune étape ne peut savoir, et cela n'existe donc nulle part dans l'état de l'exécution. Ce fichier est justement réenregistré à côté du rapport afin qu'il s'affiche pour quiconque l'ouvre au lieu d'être bloqué dans le navigateur d'une seule personne, et il est relu à chaque reconstruction. Supprimer `report/` le détruit, tout comme `run --clean`, qui retire l'ensemble du répertoire du corpus avant de démarrer.

### Le Registre `history`

Le dictionnaire `SampleState.history` associe strictement les noms des étapes des processeurs aux instances de `StageOutput`. Les structures de données de sortie sont strictement isolées et cloisonnées par des espaces de noms. Un processeur en aval qui extrait des métriques d'un map en amont interrogera : `history["upstream_processor"].data.get("metric")` (voir [Construire des Processeurs Personnalisés]({{ '/fr/extensibility/building-custom.html' | relative_url }})).

Ce cloisonnement par espaces de noms empêche définitivement les collisions de champs entre des techniques d'analyse heuristique divergentes.

### Empreintes des Entrées d'une Étape

Chaque `StageOutput` porte un `input_digest` : une empreinte du processeur, de la configuration et des fichiers suivis selon les contrôles ci-dessous. Elle est enregistrée à la fin de l'étape puis comparée lors d'une reprise pour détecter les résultats périmés.

Là où les deux empreintes sont présentes et diffèrent, le résultat stocké décrit des entrées que
le pipeline n'a plus : il compte donc comme périmé plutôt que comme fait, et l'étape est
relancée. C'est ce qui permet à une exécution reprise de déterminer d'elle-même quels résultats
tiennent toujours, au lieu de laisser au lecteur le soin de se rappeler ce qu'il a modifié. Là où
l'une des deux empreintes est vide, la question ne peut pas être posée, et une question sans
réponse ne justifie pas de jeter un travail qui a pu prendre des heures : les résultats écrits
avant que l'empreinte ne soit enregistrée sont donc retenus plutôt que refaits.

Les empreintes incluent le code source du processeur, les fichiers référencés récursivement par sa configuration et la configuration globale qu'il déclare lire. Un changement de modèle invalide l'évaluation LLM et ses descendants, mais conserve le travail non LLM fourni, tel que la décompilation. Une invalidation en amont efface aussi les états et artefacts enregistrés en aval. Un réducteur recalcule son groupe quand les résultats ou ses membres changent.

Par défaut, un processeur personnalisé prend toute la configuration globale dans son empreinte ; `cache_global_keys` peut limiter cette dépendance (`()` pour sa seule configuration locale). Déclarez les fichiers requis dans la configuration. Les ressources externes et variables d'environnement lues directement par son code ne sont pas suivies automatiquement : utilisez `--redo <stage>` si elles changent.

`cache_path_keys` sélectionne les clés de configuration suivies comme dépendances de fichiers ou dossiers (`None` : toutes ; `()` : aucune). Utilisez `cache_files(pipeline_dir)` pour déclarer les scripts ou métadonnées de version nécessaires, sans lire toute une installation ni les dossiers de sortie ou de cache.

### Actualiser le corpus découvert

Par défaut, une reprise utilise le dernier instantané de découverte. `--refresh` recherche les entrées nouvelles ou modifiées au même chemin cible. Des métadonnées de découverte identiques conservent les résultats ; les échantillons modifiés et leurs résultats en aval sont retraités. Les échantillons retirés sont déplacés dans `retired_samples/` avec leurs artefacts. `--redo discover` relance aussi la découverte des pipelines fournis. La détection dépend des métadonnées produites par le processeur d'ingestion ; elle ne surveille pas toutes les modifications de fichiers ou du réseau.

Pour un manifeste git, activez aussi `refresh: true` dans la configuration de l'ingestion pour récupérer de nouveaux commits distants ; `--refresh` seul réexamine les clones en cache.

```bash
deepzero run ./drivers -p pipelines/loldrivers/pipeline.yaml --refresh
```

Un seul processus peut écrire dans un même pipeline/corpus. Un verrou système refuse un second `deepzero run` avant nettoyage, reprise d'étape ou actualisation ; il est libéré à la fin du processus, sans suppression manuelle du fichier de verrou.
