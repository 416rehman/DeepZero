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
            <text x="70" y="-5" font-family="JetBrains Mono, monospace" font-size="14" font-weight="bold" text-anchor="middle" fill="var(--text-secondary)">state.json.tmp</text>
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

Au lieu d'écrire directement dans les artefacts attendus (par ex., `state.json`), la couche de persistance rassemble les données dans des tampons temporaires `.tmp`. Une fois la sérialisation terminée, une opération `os.replace` écrase de force l'inode atomique de destination. Un mécanisme de réessai avec temporisation (retry-backoff) intercepte activement les verrous `PermissionError` déclenchés par les heuristiques EDR/Antivirus de l'hôte lors de l'analyse des binaires nouvellement créés.

### Versionnage des Schémas

Tous les objets d'état sont marqués avec une `STATE_VERSION` interne. Si le moteur détecte une dérive de schéma lors de la désérialisation (par exemple, la lecture d'un JSON v1 sous un environnement d'exécution v2), il rend explicitement l'objet d'état obsolète au lieu d'induire des bugs de mutation imprévisibles.

### Hiérarchie de l'Espace de Travail

```text
work/<pipeline_name>/
├── run.json             # `RunState` sérialisé : Métriques d'exécution et métadonnées du pipeline
├── pipeline.yaml        # Instantané immuable de la configuration YAML du pipeline lors de l'initialisation
├── run_manifest.json    # Vue d'ensemble macro agrégée de tous les échantillons (utilisé par l'API Starlette)
└── samples/
    └── <sample_id>/     # Bac à sable isolé (sandbox)
        ├── state.json   # `SampleState` sérialisé : Registre complet des cartes `StageOutput`
        ├── context.md   # Contexte LLM synthétisé, généré via `engine/context.py`
        └── ...          # Artefacts spécifiques au processeur
```

### Le Registre `history`

Le dictionnaire `SampleState.history` associe strictement les noms des étapes des processeurs aux instances de `StageOutput`. Les structures de données de sortie sont strictement isolées et cloisonnées par des espaces de noms. Un processeur en aval qui extrait des métriques d'un map en amont interrogera : `history["upstream_processor"].data.get("metric")` (voir [Construire des Processeurs Personnalisés]({{ '/fr/extensibility/building-custom.html' | relative_url }})).

Ce cloisonnement par espaces de noms empêche définitivement les collisions de champs entre des techniques d'analyse heuristique divergentes.
