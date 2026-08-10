---
layout: default
title: YAML du Pipeline
order: 2
---

## Configuration du Pipeline

Un **Pipeline** dans DeepZero est un graphe d'exécution déclaratif définissant un processus de transformation de données continu et résilient. Il traduit un ensemble de données physiques brutes en un ensemble de données analytiques à fort signal.

Le schéma du pipeline est rigoureusement défini en YAML. DeepZero résout la configuration dynamiquement, prenant en charge l'expansion de variables shell native (par exemple, `${VAR:-default}`).

### Schéma de Configuration

```yaml
name: my_pipeline
description: Pipeline standard de recherche de vulnérabilités
version: "1.0"
model: openai/gpt-4o  # le schéma sélectionne le backend, voir ci-dessous

settings:
  work_dir: work
  max_workers: 8  # Plafond global des limites de threads du ThreadPoolExecutor

stages:
  # Étape 1 : DOIT être un IngestProcessor
  - name: discover
    processor: file_discovery
    config:
      extensions: ["*"]

  # Étape 2 : Filtre Synchrone
  - name: filter
    processor: metadata_filter
    config:
      require:
        is_executable: true

  # Étape 3 : Traitement Map à latence élevée
  - name: decompile
    processor: ghidra_decompile/ghidra_decompile.py
    parallel: 4           # Restreint la concurrence de mapping à 4 JVMs Ghidra simultanées
    timeout: 300          # Budget par échantillon : l'étape cesse d'attendre au bout de 300 secondes
    on_failure: skip      # Gère les exceptions de manière silencieuse plutôt que d'avorter (skip, retry, abort)
    max_retries: 2        # Contrainte d'exécution de la logique de réessai
    config:
      ghidra_install_dir: ${GHIDRA_INSTALL_DIR}
```

### Options des Étapes

Chaque étape définie sous le tableau `stages:` accepte les attributs suivants :

| Champ | Type | Défaut | Description |
|-------|------|---------|-------------|
| `name` | string | `stage_N` | Nom unique de l'étape au sein du pipeline |
| `processor` | string | requis | Référence du processeur (voir ci-dessous) |
| `config` | dict | `{}` | Configuration spécifique au processeur |
| `parallel` | int | `4` | Concurrence pour les processeurs Map. `0` s'adapte automatiquement, dans les limites décrites ci-dessous |
| `timeout` | int | `0` | Budget par échantillon en secondes, pour les étapes Map (0 = aucun budget) |
| `on_failure` | string | `skip` | Définit le comportement de tolérance aux pannes : `skip`, `retry`, ou `abort` |
| `max_retries` | int | `0` | Nombre de réessais lorsque `on_failure: retry` |
| `limit` | int | `0` | Se place dans `config`, lu par le moteur : tronque le corpus survivant après cette étape (0 = tout conserver) |

#### `parallel`

`parallel: 0` signifie automatique, et non illimité. L'exécuteur part de `os.cpu_count()` puis abaisse cette valeur deux fois : au plafond que le processeur déclare dans `max_parallelism()`, et au réglage `max_workers` du pipeline, en retenant le plus petit des deux. Un processeur qui lance une JVM ou un outil externe par échantillon déclare ce plafond précisément pour qu'un `parallel: 0` laissé par défaut ne puisse pas épuiser la machine, et l'exécution journalise le plafond qu'elle a appliqué. Un `parallel: N` explicite est honoré exactement tel qu'il est écrit, et n'est plafonné ni par l'un ni par l'autre.

#### `timeout`

`timeout` est le budget dont dispose un échantillon dans une étape Map. Lorsqu'il est épuisé, l'étape cesse d'attendre, enregistre cet échantillon comme ayant manqué de temps, et passe au suivant.

Ce qu'il ne fait pas, c'est tuer quoi que ce soit. Rien en Python ne peut arrêter un thread déjà en cours d'exécution : le thread de travail du processeur est donc abandonné plutôt que terminé. Un processus externe qu'il a lancé continue de tourner jusqu'à ce qu'il s'achève de lui-même, et la mémoire que ce thread retient le reste jusqu'à ce qu'il rende la main. Le budget borne le temps que l'*étape* passe à attendre, pas la durée du travail. Un processeur qui délègue à un outil externe devrait transmettre une limite à cet outil également, ce que fait `semgrep_scanner` avec sa propre clé de configuration `timeout`.

Seules les étapes Map sont couvertes. Les étapes reduce et bulk-map constituent une seule invocation pour l'ensemble du corpus plutôt qu'une invocation par échantillon, et ni l'une ni l'autre ne s'exécute sous ce budget.

Manquer de temps n'est pas un échec : `on_failure: retry` ne le retente donc pas, et une exécution reprise le laisse en l'état, car le budget qui était trop court l'est toujours. Demander une nouvelle tentative, c'est le rôle de [`--retry-timeouts`]({{ '/fr/reference/cli.html' | relative_url }}).

#### `limit`

`limit` se place dans le bloc `config` d'une étape, mais c'est le moteur qui le lit, et non le processeur. Il peut donc être défini sur n'importe quelle étape, quelles que soient les clés que ce processeur accepte, et un processeur déclarant une `Config` typée n'avertira pas que cette clé lui est inconnue.

Une fois l'étape terminée, chaque échantillon encore actif au-delà des `limit` premiers est marqué comme filtré à cette étape et ne participe plus à la suite de l'exécution. Le décompte porte sur l'ensemble du corpus survivant, et non sur les seuls échantillons que cette étape a traités.

L'ordre est celui dans lequel l'exécution transporte le corpus à cet instant, et c'est ce qui rend `limit` intéressant sur une étape reduce, ou sur celle qui la suit. Une étape reduce renvoie ses survivants classés, l'exécuteur adopte ce classement avant que la troncature n'ait lieu, et `limit` conserve alors les mieux classés plutôt qu'une tranche arbitraire. Sur une étape derrière laquelle aucun classement n'a eu lieu, elle conserve les échantillons qui se présentent en premier, quels qu'ils soient.

### Champs de Premier Niveau

| Champ | Type | Défaut | Description |
|-------|------|---------|-------------|
| `name` | string | le nom du répertoire du pipeline | Nomme le pipeline, et nomme son répertoire de travail |
| `description` | string | `""` | Texte libre |
| `version` | string | aucun | Métadonnée libre que le moteur ne lit jamais. Les deux pipelines fournis en déclarent une par convention, à l'intention de qui les maintient |
| `model` | string | `""` | Modèle pour chaque étape LLM. Un pipeline sans étape LLM n'en a pas besoin ; `deepzero validate` avertit lorsqu'il en manque un |
| `settings` | dict | `{}` | `work_dir` (défaut `work`) et `max_workers` (défaut `min(4, cpu_count)`) |
| `knowledge` | dict | `{}` | Valeurs arbitraires au niveau du pipeline, lisibles par n'importe quel processeur via `ctx.get_knowledge(key)` |
| `report` | dict | `{}` | La manière dont `deepzero report` présente les résultats de ce pipeline, voir ci-dessous |
| `stages` | list | requis | Au moins une, dont la première doit être un processeur d'ingestion |

`work_dir` est la racine, et non le répertoire d'exécution. Une exécution aboutit dans `<work_dir>/<nom du pipeline>/<clé de corpus>/`, où la clé de corpus est dérivée du chemin cible : deux corpus traités par un même pipeline n'entrent donc jamais en collision et chacun reprend de son côté. Consultez la [référence de la CLI]({{ '/fr/reference/cli.html' | relative_url }}).

### Choisir un Modèle

La partie de `model` située avant le premier `/` est un schéma, et c'est elle qui sélectionne le backend :

| Chaîne de modèle | Backend |
|------------------|---------|
| `claude-code`, `claude-code/<model-id>` | La CLI Claude Code installée localement, à laquelle vous êtes déjà connecté |
| tout le reste, par exemple `openai/gpt-4o`, `gemini/...`, `gpt-4o` | LiteLLM, qui couvre tous les points d'accès à clé d'API qu'il prend en charge |

`claude-code` exécute un pipeline via un abonnement Claude Code, sans clé d'API. DeepZero ne manipule jamais d'identifiants pour cela : il appelle la CLI à laquelle vous vous êtes déjà connecté et hérite de l'authentification dont dispose ce binaire. La partie située après la barre oblique est transmise telle quelle comme modèle : `claude-code/claude-opus-5` sélectionne donc un modèle précis, tandis que `claude-code` seul laisse la CLI sur son modèle par défaut. Les deux pipelines fournis déclarent un modèle `claude-code`, et `-m` le remplace pour une exécution.

Comme ces appels transportent du contenu non fiable, de la sortie de décompilateur et du code source tiré de dépôts inconnus, la CLI est invoquée avec ses outils et ses serveurs MCP refusés. Une complétion n'en a aucun besoin, et les laisser actifs permettrait à un prompt injecté d'atteindre un shell.

Le registre est ouvert : `register_backend()` ajoute un schéma sans modifier DeepZero, et rien dans le fournisseur, le pipeline ou les étapes n'a besoin de changer pour en gagner un. Tout schéma qu'aucun backend ne revendique retombe sur LiteLLM.

Quel que soit le backend sélectionné, on lui demande s'il peut fonctionner avant qu'une étape n'en ait besoin : `deepzero validate` vérifie la clé d'API pour un modèle LiteLLM et la présence du binaire pour une CLI d'agent, et [`deepzero run --preflight`]({{ '/fr/reference/cli.html' | relative_url }}) va plus loin en confirmant que la CLI est bien connectée.

### Logique de Résolution (`engine/registry.py`)

La forme de la valeur `processor:` détermine la manière dont elle est résolue, de sorte qu'une référence n'est jamais ambiguë entre un fichier externe et un nom intégré :

| Référence | Résolue comme |
|-----------|---------------|
| Contient `/` ou `\`, par exemple `ghidra_decompile/ghidra_decompile.py` | Un fichier situé sous l'une des racines de processeurs listées ci-dessous. La première sous-classe de Processor qu'il contient est utilisée, en ignorant les classes de base elles-mêmes |
| La même chose, suivie de `:NomDeClasse` | Cette classe précise dans ce fichier, ce dont a besoin un fichier définissant plusieurs processeurs |
| Un nom simple, par exemple `metadata_filter` | Le registre interne, peuplé dans `stages/__init__.py` |
| Un nom simple contenant `:`, par exemple `my.python.module:MyClass` | Un module importable présent sur `sys.path`, et une classe qu'il contient |

Tout le reste produit une erreur nommant les processeurs intégrés, plutôt qu'un échec plus tard dans l'exécution.

Une référence portant un séparateur est cherchée sous cinq racines, dans cet ordre, et la
première qui existe l'emporte :

1. chaque chemin de `$DEEPZERO_PROCESSORS`, séparé comme cette plateforme sépare les
   entrées de `PATH` : `;` sous Windows, `:` ailleurs
2. `processors/` dans le répertoire de travail
3. `processors/` à côté du YAML propre au pipeline
4. `processors/` dans le répertoire parent du répertoire du pipeline
5. le répertoire du pipeline lui-même, pour un pipeline gardant un processeur à côté de son
   YAML plutôt que dans un sous-répertoire

Le répertoire de travail est parcouru avant le répertoire du pipeline, ce qui explique pourquoi les pipelines fournis se résolvent depuis la racine du dépôt. Ce n'est pourtant pas la seule racine : un pipeline conservé n'importe où peut transporter ses propres processeurs à côté de lui et être lancé depuis n'importe quel répertoire, sans que le moteur dicte l'endroit d'où la commande est émise.

`$DEEPZERO_PROCESSORS` est parcouru avant toutes les autres racines, et c'est ce qui en fait une bibliothèque partagée de processeurs : un nom qui s'y trouve masque le même nom placé sous le `processors/` du répertoire de travail ou à côté du pipeline. Une référence ne correspondant à aucune racine échoue en nommant chacun des chemins essayés, de sorte qu'une faute de frappe se lise comme une faute de frappe plutôt que comme un fichier manquant.

### Expansion Dynamique

Avant que la validation du schéma ne lie les processeurs, DeepZero parcourt l'ensemble de l'arbre DOM YAML, en évaluant les correspondances Regex pour `\$\{([^}]+)\}`. Les variables d'environnement dictent la configuration d'exécution résolue. Cela empêche explicitement de coder en dur des clés d'API ou des répertoires d'installation au sein des pipelines `.yaml` validés.

### Valeurs des Prompts

Une étape dont la `config` porte un `prompt` effectue le rendu de ce fichier comme un modèle Jinja. La valeur peut être un chemin ou un nom de fichier situé à côté du pipeline ; dans les deux cas le fichier est chargé, jamais utilisé comme le texte du prompt lui-même.

Chaque prompt peut utiliser ceci :

| Valeur | Type | Description |
|--------|------|-------------|
| `sample_name` | string | Le nom de fichier de l'échantillon tel que l'étape d'ingestion l'a enregistré |
| `sample_path` | string | Chemin absolu vers l'échantillon sur le disque |
| `history` | dict | `{stage_name: data}` pour chaque étape déjà exécutée |
| `config` | dict | Le bloc `config` propre à cette étape |

Au-delà de cela, un prompt peut utiliser tout ce que les étapes **qui le précèdent** ont enregistré. Chaque processeur déclare ces noms dans son attribut `provides`, et il en existe deux sortes :

- **Les clés de données**, c'est-à-dire tout ce que le processeur place dans `data`, comme `device_name` ou `finding_count`. Disponibles directement sous ce nom, ainsi que sous `history`.
- **Les artefacts**, c'est-à-dire un fichier écrit par le processeur, atteignable par son chemin, séparateurs et extension incorporés au nom. `decompiled/dispatch_ioctl.c` devient `decompiled_dispatch_ioctl_c`. Le JSON est analysé en un objet, et une longue liste de suffixes de code source, de balisage et de texte brut arrive sous forme de texte ; une étape qui a besoin d'un autre ensemble déclare `text_extensions` dans sa propre `config`, ce qui remplace la liste plutôt que de s'y ajouter. Rien d'autre n'est exposé. Le texte qui dépasse le budget de contexte, soit `max_context_tokens` multiplié par quatre caractères, est tronqué et le signale, et un fichier JSON plus volumineux que ce budget est ignoré avec un avertissement plutôt qu'analysé.

Une valeur n'est disponible que pour les étapes situées *après* celle qui l'enregistre : un prompt ne peut donc pas atteindre la sortie de sa propre étape.

Pour voir ce qu'un pipeline donné propose, exécutez :

```bash
deepzero validate <pipeline>
```

Un prompt nommant quelque chose qu'aucune étape antérieure ne produit est signalé comme une erreur listant ce qui était disponible à la place. Le rendu au moment de l'exécution est strict sur le même point : une étape qui y parvient malgré tout échoue sur cet échantillon plutôt que de laisser partir le prompt. Cela compte, car un nom inconnu ne produirait sinon rien au rendu : on demanderait au modèle de juger une charge utile vide, et le verdict reviendrait assuré et dénué de sens.

### Le Bloc `report`

`deepzero report` est construit à partir de ce que le moteur garantit, qui est identique pour chaque pipeline : chaque étape enregistre `data`, `artifacts` et un statut. Ce qui diffère, c'est le vocabulaire. Un pipeline de pilotes noyau, un audit de code source et un balayage de licences produisent les mêmes formes d'issues et les appellent de manières complètement différentes.

Les formes sont donc fixes et les mots sont déclarés :

```yaml
report:
  title: Source repository audit
  entity: repository
  entity_plural: repositories
  target_label: repository list
  classification_key: classification
  positive_when: [vulnerable]
  negative_when: [not exploitable]
  columns:
    - scan.finding_count
    - discover.primary_language
  findings_files: [findings.json]
```

Chaque champ est optionnel, et chaque valeur par défaut reproduit le comportement qu'avait un pipeline avant l'existence de ce bloc. Un pipeline qui ne déclare rien obtient tout de même un rapport exploitable.

| Champ | Type | Défaut | Description |
|-------|------|---------|-------------|
| `title` | string | `<nom du pipeline> results` | Titre de `index.html` |
| `entity` | string | `sample` | Le nom donné à un résultat unique dans l'interface |
| `entity_plural` | string | `entity` + `s` | Nécessaire uniquement là où ajouter un s est incorrect, par exemple repository |
| `target_label` | string | `corpus` | Ce vers quoi l'exécution a été pointée |
| `classification_key` | string | `classification` | La clé de `data` de l'étape qui porte la conclusion |
| `positive_when` | list | `vulnerab`, `exploitab`, `confirmed` | Valeurs comptées comme étant ce que vous recherchez |
| `negative_when` | list | `safe`, `not vulnerab`, `benign`, `clean` | Valeurs comptées comme n'ayant rien trouvé |
| `columns` | list | choisies automatiquement | Valeurs `étape.clé` à afficher en regard de chaque résultat |
| `findings_files` | list | `findings.json` | Noms de fichiers, dans le répertoire d'un échantillon, où lire les détections |
| `lexicon` | dict | voir ci-dessous | Les mots désignant les issues |

`vulnerable_when` et `safe_when` sont acceptés comme anciens noms de `positive_when` et `negative_when` et signifient exactement la même chose. `positive_when` l'emporte si les deux sont fournis.

`target_label` mérite sa place parce que la valeur par défaut, « corpus », suppose un tas de fichiers sur un disque. Une exécution portant sur une application en production a un périmètre, et une exécution portant sur un ensemble de dépôts a la liste ou le répertoire de copies de travail vers lequel elle a été pointée. Appeler l'un ou l'autre un corpus se lit comme une erreur dans un rapport que quelqu'un d'autre va ouvrir.

Nommez ce que l'en-tête affiche, c'est-à-dire la cible de l'exécution, plutôt que ce dont l'exécution traite. « Organisation » est la valeur tentante à se tromper : elle se lit bien, et elle étiquette ensuite un chemin de manifeste qui peut lister des dépôts appartenant à plusieurs organisations.

#### Comment un verdict est mis en correspondance

La valeur enregistrée sous `classification_key` est passée en minuscules puis testée d'abord contre les sous-chaînes de `positive_when`, puis contre celles de `negative_when`. Des sous-chaînes, et non des valeurs exactes : `vulnerab` couvre donc « vulnerable » et « vulnerability ».

Tester les positifs en premier est ce qui rend les valeurs par défaut dignes d'être remplacées. Un pipeline dont le verdict négatif est `[NOT EXPLOITABLE]` contient `exploitab`, qui est un positif par défaut : il serait donc compté comme une trouvaille. Restreindre `positive_when` à `[vulnerable]` est ce que fait l'audit de code source fourni, et c'est le point à vérifier lorsque les verdicts d'une exécution et les décomptes du rapport divergent.

Un verdict ne correspondant à aucune des deux listes n'est pas silencieusement écarté. Il aboutit sous « Unclear verdict », ce qui est une affirmation différente d'avoir été jugé sûr.

#### Colonnes

`columns` nomme des valeurs `étape.clé`, en utilisant le nom de l'étape tel qu'il figure dans ce pipeline, et place chacune en regard de chaque résultat. Déclarez celles qui déterminent ce qu'il faut lire ensuite : si une détection peut être exercée, quelle quantité de code a réellement été analysée, quelle révision a été jugée. Lorsqu'aucune n'est déclarée, le rapport retient jusqu'à six clés, numériques ou au nom significatif, parmi ce que l'exécution a enregistré.

Rien n'a besoin d'être ajouté au rapport pour cela. Une clé est disponible dès l'instant où un processeur l'enregistre dans `data` et où le pipeline la nomme ici.

#### Détections

`findings_files` nomme les fichiers, situés dans le répertoire de chaque échantillon, où lire les détections. Tout artefact JSON dont le contenu ressemble à une liste de détections est également repris, de sorte qu'un processeur écrivant sous un autre nom apparaît quand même sans configuration.

Une détection peut également nommer la chose dont elle est une occurrence. Le rapport lit ce nom dans `finding_id`, à défaut dans `key`, puis dans `fingerprint`, et toute détection portant le même nom est regroupée comme une seule chose vue à plusieurs endroits. Le rapport gagne alors une section « Distinct findings » listant chaque nom, ce dont il s'agit, et sur combien d'entités il est apparu. La section est absente d'un rapport où aucune détection ne porte de nom.

Le moteur n'en invente jamais. Tout ce qu'il pourrait dériver intégrerait l'emplacement et ne correspondrait donc jamais d'un échantillon à l'autre, ce qui est précisément le cas pour lequel ce nom existe. Un même avis de sécurité sur quarante dépôts n'est une seule détection plutôt que quarante que si le processeur le dit, et il en va de même d'une cause racine unique derrière trois mille plantages, ou d'un même chemin de contamination atteint depuis deux points d'entrée.

#### Le lexique

Le rapport dispose d'une catégorie pour la chose recherchée, d'une pour les détections sur lesquelles rien n'a tranché, et d'une pour un résultat analysé de bout en bout sans que rien n'ait été signalé. Cela relève de la structure. Seuls leurs noms vous appartiennent :

| Champ | Défaut | Où il apparaît |
|-------|---------|----------------|
| `discipline` | `vulnerability research` | À côté du nom du produit dans l'en-tête |
| `positive` | `Vulnerable` | L'étiquette de la catégorie, et son filtre |
| `positive_help` | `an assessment stage concluded these are vulnerable` | L'explication affichée en regard de cette étiquette |
| `positive_phrase` | `assessed as vulnerable` | Complète « 12 repositories ... » dans la ligne de synthèse |
| `nothing_positive` | `Nothing was confirmed vulnerable` | Le titre affiché lorsque l'exécution n'a rien trouvé sur quoi agir |
| `unconfirmed` | `Needs assessment` | Des détections existent, aucune évaluation n'a tranché à leur sujet |
| `negative` | `Clear` | Analysé de bout en bout, rien de signalé |

Les issues restantes sont nommées par le moteur et ne sont pas configurables, car elles décrivent ce qu'a fait le moteur plutôt que ce que cherchait le pipeline : « Errored », « Ran out of time », « Unclear verdict » et « Filtered out ».

Chaque clé est lue pour elle-même : en déclarer une laisse donc les autres à leur valeur par défaut. Une clé qui ne fait pas partie des sept ci-dessus est ignorée, tout comme une clé laissée vide, et un `lexicon:` écrit comme une valeur plutôt que comme un bloc retombe intégralement sur les valeurs par défaut, au lieu de faire échouer le rapport qu'une longue exécution vient tout juste de mériter.

La formulation finalement en vigueur est écrite dans `report.json` à côté des décomptes, sous `bucket_labels`, `entity`, `entity_plural` et `target_label` : tout ce qui produit ses propres intitulés à partir de ce fichier nomme donc chaque issue comme le fait le HTML.

C'est ce qui emmène l'outil au-delà de la recherche de vulnérabilités. Un pipeline auditant les licences des dépendances a les mêmes trois issues et pas un seul des mots par défaut pour les désigner : il dit donc ce qu'elles sont.

```yaml
report:
  entity: package
  target_label: dependency tree
  classification_key: licence_status
  positive_when: [incompatible]
  negative_when: [compatible]
  lexicon:
    discipline: licence compliance
    positive: Incompatible
    positive_help: the declared licence conflicts with this project's
    positive_phrase: carry an incompatible licence
    nothing_positive: No incompatible licences were found
    unconfirmed: Needs a decision
    negative: Compatible
```

Rien d'autre ne change. Le rapport classe, filtre, regroupe et exporte exactement comme il le fait pour une chasse aux pilotes, parce que rien de tout cela n'a jamais dépendu du sujet de l'exécution.

### Marques de Revue

Un pipeline enregistre ce qu'il a conclu. Savoir si une personne a réellement vérifié cette conclusion est une affirmation distincte, que seul le lecteur peut formuler : le rapport porte donc des marques qu'il ajoute au fil de sa lecture.

Sur la page de n'importe quel résultat, il y en a deux, car une revue soit a abouti à une réponse, soit n'y est pas parvenue :

| Marque | Signification |
|--------|---------------|
| **Confirmed** | vérifié, et cela tient |
| **Refuted** | vérifié, et cela n'a pas tenu |

L'une comme l'autre ouvre une note où consigner ce que vous avez lancé, sur quoi, et ce qui s'est passé, afin que quelqu'un d'autre puisse répéter la tentative. La note appartient à la marque : un résultat qui n'en porte aucune n'a nulle part où en accueillir une, de sorte qu'une revue qui n'a rien tranché s'enregistre en laissant le résultat intact, plutôt qu'en notant où elle s'est arrêtée.

Tout ce qui ne porte ni l'une ni l'autre compte comme **Unreviewed**, que personne ne l'ait ouvert ou que quelqu'un l'ait ouvert sans pouvoir trancher. Ces deux cas relevaient autrefois de contrôles distincts, et côte à côte ils se lisent comme la même chose.

Refuted n'est délibérément pas fondu dans Unreviewed. C'est un travail achevé, avec une réponse définitive, et un résultat qui n'a pas tenu ne devrait jamais ressembler à un résultat que personne n'a examiné.

Les marques apparaissent en regard de chaque ligne de l'index et peuvent servir de filtre, Unreviewed compris, ce qui donne la liste des résultats sur lesquels personne n'a encore tranché. La synthèse compte les trois, de sorte qu'une exécution peut se lire comme ce qui est réellement établi plutôt que seulement comme ce qui a été avancé.

Le rapport est un fichier, les marques vivent donc dans le navigateur. **export marks** les écrit sous forme de `marks.json` ; enregistrez ce fichier à côté de `index.html` et elles font alors partie du rapport : affichées pour quiconque l'ouvre, et incluses dans `inventory.csv` sous `review` et `review_note`. Les marques sont indexées sur le pipeline et la cible plutôt que sur le chemin du fichier : relancer l'analyse sur le même corpus les conserve donc.
