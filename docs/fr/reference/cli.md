---
layout: default
title: Référence de la CLI
order: 1
---

## Interface en Ligne de Commande

La CLI `deepzero` est le point d'interaction principal pour l'exécution et la gestion des pipelines.

```bash
# Exécution standard
deepzero run ./targets -p pipelines/loldrivers/pipeline.yaml

# Vérifier que le backend LLM est connecté avant de s'engager dans une longue exécution
deepzero run ./targets -p pipelines/source_audit/pipeline.yaml --preflight

# Exécuter avec nettoyage de l'état (nouvelle exécution)
deepzero run ./targets -p pipelines/loldrivers/pipeline.yaml --clean

# Lister toutes les exécutions présentes sur le disque, quelle qu'en soit l'origine
deepzero runs

# Construire un rapport HTML consultable et l'ouvrir
deepzero report -p loldrivers --open

# Vérifier l'état de l'exécution
deepzero status -p loldrivers

# Lancer la REPL d'analyse interactive
deepzero interactive -w work/loldrivers

# Démarrer l'API REST Starlette
deepzero serve -w work/loldrivers --port 8420

# Échafauder un nouveau pipeline personnalisé
deepzero init my_custom_pipeline

# Valider le schéma sans exécution
deepzero validate loldrivers

# Inspecter le registre système
deepzero list-processors
```

`deepzero --version` affiche la version installée, et `--help` fonctionne sur le groupe comme sur chaque commande.

### Commandes Principales

| Commande | Description |
| --------- | ----------- |
| `run` | Exécute un pipeline sur une cible. Reprend automatiquement si un état existe. |
| `report` | Construit un rapport HTML consultable à partir des résultats d'une exécution. Peut être lancé sans risque pendant que l'exécution se déroule. |
| `runs` | Liste toutes les exécutions présentes sur le disque, quels que soient le pipeline et le corpus qui les ont produites. |
| `status` | Affiche l'état actuel de l'exécution du pipeline, les verdicts et les métriques des étapes. |
| `validate` | Effectue une validation à blanc (dry-run) du schéma d'un pipeline, des importations de processeurs et des prompts. |
| `list-processors` | Liste tous les types de processeurs intégrés et enregistrés dynamiquement. |
| `init` | Échafaude un nouveau répertoire de pipeline avec un `pipeline.yaml` standard. |
| `interactive` | REPL d'analyse interactive avec conversation assistée par LLM sur les résultats du pipeline. |
| `serve` | Démarre le serveur API REST pour exposer l'état du pipeline en externe. |

### `run`

```bash
deepzero run <TARGET> -p <pipeline> [options]
```

| Drapeau | Défaut | Description |
|---------|---------|-------------|
| `TARGET` | requis | Argument positionnel. Chemin vers le corpus d'analyse. Doit exister ; un fichier ou un répertoire, selon ce qu'accepte l'étape d'ingestion du pipeline. |
| `-p, --pipeline` | requis | Nom du pipeline, répertoire ou chemin de fichier YAML discret. |
| `-m, --model` | le `model` du pipeline | Remplace le modèle LLM pour cette exécution, par exemple `openai/gpt-4o`. |
| `-w, --work-dir` | le réglage `work_dir` du pipeline | Remplace la racine sous laquelle le répertoire d'exécution est construit. |
| `--clean` | désactivé | Supprime définitivement les données de l'exécution précédente et repart de zéro. |
| `--preflight` | désactivé | Vérifie que le backend LLM est authentifié avant l'exécution. Effectue un unique appel minimal. |
| `--redo` | aucun | Réexécute une étape nommée et toutes celles qui la suivent, en conservant le travail antérieur et en supprimant la sortie que ces étapes avaient enregistrée. Répétable. |
| `--retry-timeouts` | désactivé | Retente les échantillons qui ont manqué de temps, en conservant tous les autres résultats. |
| `--timeout-multiplier` | `2.0` | De combien allonger le délai lors d'une nouvelle tentative sur une étape qui a manqué de temps. |
| `-v, --verbose` | désactivé | Journalisation détaillée, y compris les traces d'appels issues du code de DeepZero lui-même. |

Une exécution sans état derrière elle repart de zéro ; une exécution avec état reprend, et l'en-tête indique quelle exécution est reprise. Modifier `--model` entre deux exécutions est autorisé et enregistré : l'état de l'exécution est mis à jour pour nommer le modèle qui sera réellement appelé, afin que `status` et le rapport ne décrivent pas un modèle qui n'est plus utilisé.

`--clean` déplace le répertoire précédent sous un autre nom et le supprime en arrière-plan, afin qu'un corpus de plusieurs centaines de milliers de fichiers ne retienne pas la commande pendant sa suppression.

#### Où réside l'état d'une exécution

Les répertoires de travail sont cloisonnés par corpus :

```text
<réglage work_dir>/<nom du pipeline>/<clé de corpus>/
```

La clé de corpus est dérivée du chemin cible : son nom de base, augmenté d'une courte empreinte du chemin absolu résolu. Deux corpus traités par le même pipeline ne partagent donc jamais un magasin d'échantillons, un manifeste ou un rapport, et chacun reprend indépendamment. Un même chemin produit toujours la même clé : une nouvelle exécution retombe donc dans le répertoire qu'elle avait quitté.

`-w, --work-dir` sur `run` ne remplace que le premier segment. Les segments du pipeline et du corpus sont toujours ajoutés à la suite, car ce sont eux qui séparent deux exécutions.

#### Le rapport qu'une exécution écrit au fil de l'eau

Une exécution écrit son rapport HTML dans `<répertoire de travail>/report` et en affiche l'URL avant le démarrage de la première étape. Il est reconstruit lorsque des résultats arrivent plutôt qu'à intervalle fixe, et pas plus d'une fois toutes les 15 secondes, afin qu'une étape rapide ne puisse pas dépenser le temps de l'exécution à écrire du HTML. Il est écrit une dernière fois à l'arrêt de l'exécution, interrompue ou terminée, de sorte que ce qui se trouve sur le disque soit toujours l'état final.

#### Vérifier le LLM avant une longue exécution

`--preflight` demande au backend s'il est prêt et refuse de démarrer s'il ne l'est pas. Cela existe parce que l'alternative consiste à l'apprendre plusieurs heures plus tard, à la première étape d'évaluation, une fois que les étapes coûteuses qui la précèdent se sont déjà exécutées.

Ce que fait la vérification dépend du backend, car être authentifié ne signifie pas la même chose partout. Un backend de type CLI d'agent comme `claude-code` envoie un prompt minimal, puisque DeepZero ne peut pas lire sur le disque si ce binaire est connecté. Un backend à clé d'API répond à partir de la vérification de clé déjà effectuée lors de la validation et ne dépense rien.

Une limite de débit ou une erreur réseau n'est pas traitée comme un échec d'authentification et ne bloque pas l'exécution. La vérification est optionnelle plutôt que systématique, car cet unique prompt constitue une consommation réelle, aussi minime soit-elle.

Elle ne s'exécute que lorsque le pipeline configure un modèle. Un pipeline sans étape LLM n'a rien à vérifier.

#### Retenter ce qui a manqué de temps

Une étape qui atteint son `timeout` enregistre l'échantillon comme ayant manqué de temps plutôt que comme ayant échoué. C'est une affirmation sur le budget, pas sur l'échantillon : ceux qui l'atteignent sont les plus volumineux, c'est-à-dire, dans la plupart des corpus, ceux qui méritent d'être examinés, et les classer avec de véritables erreurs biaise discrètement l'exécution à leur détriment.

Le budget borne le temps que l'étape passe à attendre, pas la durée du travail. Le thread du processeur est abandonné plutôt que tué : un processus externe qu'il a lancé tourne donc encore une fois que l'étape est passée à la suite. Consultez [`timeout`]({{ '/fr/reference/pipeline-yaml.html' | relative_url }}).

Une exécution reprise ne les retente pas d'elle-même, car le budget qui était trop court l'est toujours. Demandez-le :

```bash
deepzero run <target> -p <pipeline> --retry-timeouts
```

Cela n'oublie que les étapes qui ont manqué de temps et leur accorde `--timeout-multiplier` (2x par défaut) de plus. Tous les autres résultats produits par l'exécution sont conservés : une nouvelle tentative coûte donc le temps nécessaire à ces étapes et rien d'autre. Les étapes qui ne déclarent aucun délai ne sont pas touchées. Le rapport les regroupe séparément et indique le budget que chacune a dépassé.

#### Réexécuter une seule étape

Modifier un prompt, un ensemble de règles ou la configuration d'un scanneur invalide les résultats de cette étape, et rien de ce qui la précède. Décompiler un corpus une seconde fois pour lui reposer une question coûterait des heures sans raison : nommez plutôt l'étape.

```bash
deepzero run <target> -p <pipeline> --redo assess
```

Chaque échantillon oublie cette étape et toutes les suivantes, et conserve tout ce qui précède. Les étapes suivantes partent aussi parce qu'elles ont consommé une sortie sur le point de changer : une évaluation rédigée à partir de détections qui n'existent plus laisserait un même échantillon décrire deux exécutions différentes. Un échantillon qu'une étape désormais obsolète avait filtré rejoint l'exécution, de sorte qu'un ensemble de règles restreint est libre de rendre un verdict différent à son sujet.

La sortie que ces étapes avaient enregistrée part avec l'état. Plusieurs processeurs traitent leur propre fichier sur le disque comme un cache et l'adoptent au lieu de refaire le travail : n'oublier que l'état conduirait donc l'étape à réadopter le fichier périmé et à l'enregistrer comme s'il venait d'être produit, ce qui est pire que de ne rien réexécuter du tout. `--redo` supprime donc chaque artefact que les étapes abandonnées avaient enregistré, et indique combien de fichiers il a retirés. Un artefact enregistré hors du répertoire propre à l'échantillon est laissé intact, car il n'appartient pas à cette exécution.

`--redo` est répétable et démarre à la plus précoce des étapes nommées. Un nom d'étape inconnu est refusé, avec la liste des noms d'étapes réels du pipeline, plutôt que d'être traité comme n'ayant rien à faire. Si aucun échantillon n'avait atteint l'une des étapes nommées, la commande le dit et ne change rien.

### `report`

```bash
deepzero report -p <pipeline> [--open]
deepzero report -w work/loldrivers/drivers-1a2b3c4d
```

| Drapeau | Défaut | Description |
|---------|---------|-------------|
| `-p, --pipeline` | aucun | Nom ou chemin du pipeline. Se résout vers le corpus le plus récent de ce pipeline. |
| `-w, --work-dir` | aucun | Un répertoire d'exécution, ou la racine d'un pipeline, auquel cas le corpus le plus récent est lu et nommé. Prioritaire sur `--pipeline`. |
| `-o, --out` | `<work_dir>/report` | Où écrire le rapport. |
| `--open` | désactivé | Ouvre le rapport dans un navigateur une fois terminé. |
| `-v, --verbose` | désactivé | Journalisation détaillée. |

Aucun des deux drapeaux n'est requis. Si les deux sont donnés, c'est `--work-dir` qui tranche. Si aucun ne l'est, `report` cherche dans `work`, c'est-à-dire le répertoire portant littéralement ce nom et non le réglage `work_dir` du pipeline. S'il n'y trouve qu'une exécution, elle est retenue et nommée. S'il y en a plusieurs, elles sont listées dans un tableau numéroté et, depuis un terminal, la commande demande laquelle par son numéro. Un appelant n'ayant nulle part où lire une réponse se voit présenter la même liste ainsi que la ligne `deepzero report -w <exécution>` qui en désigne une précisément, et la commande sort avec le code 1, car une invite bloquerait un script. S'il n'y a aucune exécution, la commande le dit et sort avec le code 1.

Le rapport est dérivé de l'état de l'exécution : supprimez son répertoire, relancez la commande, et vous le récupérez. La seule chose qui ne revient pas est `report/marks.json`, qui retient ce qu'un lecteur a marqué comme vérifié et qui est la seule chose sous ce répertoire qu'aucune étape ne peut produire. Il peut également être construit sans risque pendant qu'une exécution se déroule : il lit les fichiers d'état et n'écrit rien dont dépende l'exécuteur, de sorte qu'il décrit l'exécution telle qu'elle était au moment de sa construction.

Il écrit :

| Fichier | Contenu |
|---------|---------|
| `index.html` | Synthèse et liste classée, de taille bornée |
| `items/<id>.html` | Une page par échantillon méritant d'être lu, avec des liens vers les artefacts de cet échantillon |
| `inventory.csv` | Chaque échantillon, une ligne, pour un tableur |
| `findings.jsonl` | Chaque détection, un objet JSON par ligne |
| `report.json` | Totaux de synthèse pour une machine, ainsi que le vocabulaire dans lequel ils sont nommés |

Un échantillon obtient sa propre page lorsqu'il y a quelque chose à y lire : des détections, une évaluation, une erreur, ou une étape qui a manqué de temps. Les autres figurent toujours dans le CSV, et l'index signale lorsqu'une liste a été plafonnée et où trouver le reste.

La résolution par nom de pipeline retient le corpus le plus récent, et le signale lorsque le pipeline en a vu plusieurs, en nommant les autres. L'exécution la plus récente n'est pas toujours celle sur laquelle porte la question, et répondre silencieusement à propos d'un autre corpus est l'échec qu'il faut éviter. Passez `--work-dir` pour en désigner un précisément.

La manière dont le pipeline nomme ses échantillons, ses issues et ce vers quoi il a été pointé provient du bloc `report:` du pipeline, qui réside dans la définition du pipeline et non dans le répertoire d'exécution. `--work-dir` l'obtient tout de même : l'exécution enregistre quel pipeline l'a produite, et le bloc est donc récupéré par son nom. Une exécution peut cependant survivre au pipeline qui l'a créée, et lorsque ce pipeline ne se charge plus, le rapport retombe sur la formulation par défaut plutôt que de refuser d'être construit. Consultez [le bloc report]({{ '/fr/reference/pipeline-yaml.html' | relative_url }}).

### `runs`

```bash
deepzero runs
deepzero runs -w work --open
```

| Drapeau | Défaut | Description |
|---------|---------|-------------|
| `-w, --work-dir` | `work` | Racine à parcourir. Tout répertoire situé en dessous et contenant un `run.json` compte comme une exécution, à n'importe quelle profondeur. |
| `--open` | désactivé | Construit le rapport de l'exécution la plus récente et l'ouvre dans un navigateur. |
| `-v, --verbose` | désactivé | Journalisation détaillée. |

Affiche un tableau de toutes les exécutions présentes sur le disque, quels que soient le pipeline et le corpus qui les ont produites, de la plus récente à la plus ancienne : le pipeline qui l'a écrite, le répertoire du corpus, le statut de l'exécution, le nombre d'échantillons découverts par l'ingestion, si un rapport a été construit, et la date de la dernière écriture de l'état. La commande affiche ensuite la ligne `deepzero report -w <exécution la plus récente> --open`, de sorte que l'exécution en tête de tableau puisse être ouverte sans avoir à taper son chemin.

Ce qui est recherché, c'est le fichier marqueur `run.json`, à n'importe quelle profondeur, plutôt que la forme `<répertoire de travail>/<pipeline>/<corpus>/`. Une exécution se range toujours selon cette forme, mais seulement par rapport à sa propre racine, et `-w` sur `run` peut placer cette racine n'importe où : filtrer sur la forme depuis ici laisserait de côté toute exécution dont la racine n'est pas celle qui est parcourue.

La colonne du rapport indique `built` ou `not built`. C'est un fait sur le répertoire plutôt que sur les résultats : un rapport est dérivé de l'état de l'exécution, `not built` signifie donc à une commande de distance, et non perdu.

La commande sort avec le code 1 lorsque la racine n'est pas un répertoire, et lorsqu'elle en est un mais ne contient aucune exécution.

### `status`

```bash
deepzero status -p loldrivers
```

| Drapeau | Défaut | Description |
|---------|---------|-------------|
| `-p, --pipeline` | aucun | Nom ou chemin du pipeline. Se résout vers le corpus le plus récent de ce pipeline. |
| `-w, --work-dir` | aucun | Un répertoire d'exécution, ou la racine d'un pipeline, auquel cas le corpus le plus récent est lu et nommé. Prioritaire sur `--pipeline`. |
| `-v, --verbose` | désactivé | Journalisation détaillée. |

L'un des deux est requis. Affiche l'identifiant de l'exécution, la cible, le modèle, les horodatages, un tableau par étape des nombres d'échantillons terminés, filtrés, en échec et ayant manqué de temps, ainsi que les totaux des verdicts. « Manqué de temps » dispose de sa propre colonne, afin qu'une étape où tout a manqué de temps ne se lise pas comme une étape que rien n'a atteinte, ce qui est l'exact contraire de ce qui s'est produit.

### `validate`

```bash
deepzero validate <PIPELINE_REF>
```

Charge le pipeline, résout chaque processeur, exécute le `validate()` propre à chaque processeur, et vérifie chaque prompt par rapport aux valeurs que les étapes qui le précèdent produisent réellement. Cette commande n'accepte aucun drapeau. Lancez-la avant une longue exécution : c'est l'endroit le moins coûteux pour découvrir un binaire manquant, un ensemble de règles illisible ou un prompt nommant quelque chose qu'aucune étape n'enregistre.

Elle sort avec le code 1 lorsqu'elle signale une erreur, et 0 sinon : elle peut donc conditionner un commit. Les avertissements, comme un pipeline qui ne configure aucun modèle, sont affichés mais ne font pas échouer la commande : ils décrivent un pipeline qui démarrera, pas un pipeline incapable de démarrer.

### `list-processors`

Affiche chaque processeur enregistré avec son type et sa classe d'implémentation. N'accepte aucun drapeau. Seuls les processeurs intégrés sont listés ; un processeur externe est résolu à partir de son chemin au moment du chargement et n'est pas enregistré sous un nom.

### `init`

```bash
deepzero init <NAME>
```

Crée `pipelines/<NAME>/pipeline.yaml` sous le répertoire de travail, avec un squelette commenté. La commande refuse d'agir plutôt que d'écraser un répertoire existant.

### `interactive`

```bash
deepzero interactive -w work/loldrivers/drivers-1a2b3c4d
```

| Drapeau | Défaut | Description |
|---------|---------|-------------|
| `-m, --model` | `claude-code/claude-opus-5` | Modèle pour la conversation. N'importe quelle chaîne de modèle acceptée par les backends. |
| `-w, --work-dir` | `work` | Répertoire d'exécution depuis lequel charger le contexte. |
| `-v, --verbose` | désactivé | Journalisation détaillée. |

Une REPL qui charge l'état d'une exécution dans le prompt système afin de pouvoir lui poser des questions. `/status`, `/findings [filtre]`, `/clear`, `/help` et `/quit` sont traités localement ; tout le reste part vers le modèle, et un `/mot` non reconnu est signalé plutôt que facturé comme un tour de conversation. `/findings` liste chaque détection enregistrée par l'exécution, restreinte aux lignes correspondant à son argument, dans le vocabulaire déclaré par le pipeline qui a produit l'exécution.

`-w` accepte un répertoire d'exécution ou la racine d'un pipeline, en nommant le corpus retenu lorsqu'il y en a plusieurs. La valeur par défaut est littéralement `work`, c'est-à-dire la racine située au-dessus des répertoires de pipelines, qui ne se résout à aucune exécution : la REPL le dit et répond sans contexte d'exécution plutôt que de faire comme si elle en avait chargé un. Pointez donc `-w` vers l'exécution que vous visez.

`report` trouve bien une exécution sous un simple `work` là où celle-ci n'y parvient pas, et c'est une véritable différence plutôt qu'une coquille dans l'une des deux : `report` parcourt l'arborescence à la recherche de répertoires d'exécution, tandis qu'`interactive` résout un seul niveau et retient le corpus le plus récent sous ce qui lui a été donné. Une conversation vaut la certitude qu'apporte le fait de devoir nommer l'exécution ; un rapport, lui, est peu coûteux à reconstruire sur une autre.

### `serve` et l'API REST

| Drapeau | Défaut | Description |
|---------|---------|-------------|
| `--host` | `127.0.0.1` | Hôte d'écoute. Toute valeur autre que la boucle locale affiche un avertissement, car le serveur devient alors accessible depuis le réseau. |
| `--port` | `8420` | Port d'écoute. |
| `-w, --work-dir` | `work` | Répertoire de travail à servir. Un répertoire d'exécution, ou la racine d'un pipeline, auquel cas le corpus le plus récent est servi et nommé. |

Nécessite l'extra : `pip install deepzero[serve]`, qui installe Starlette et uvicorn.

> [!WARNING]
> **Fonctionnalité Expérimentale / En cours de développement**
> Le serveur API REST est actuellement incomplet, très instable, et **ne doit pas être utilisé**. Il est fourni strictement pour le développement expérimental en local.

Démarre une API REST Starlette en lecture seule pour interroger l'état d'exécution et les données des échantillons. Elle sert exactement une exécution, ce qui explique que le répertoire de travail soit résolu vers un corpus unique avant l'affichage de l'URL, plutôt qu'après qu'une requête est revenue vide.

| Point d'accès | Méthode | Description |
|----------|--------|-------------|
| `/api/health` | GET | Vérification de l'état de santé, et le répertoire de travail servi |
| `/api/runs` | GET | L'exécution servie sous forme de liste à un élément, ou une liste vide |
| `/api/run` | GET | L'état complet de cette exécution, ou 404 |
| `/api/samples` | GET | Lister les échantillons (filtrables via `?verdict=`, `?classification=`, `?stage=`, `?status=`) |
| `/api/samples/{sample_id}` | GET | État complet de l'échantillon avec l'historique des données du pipeline |
| `/api/samples/{sample_id}/artifacts/{name}` | GET | Lire un artefact de fichier spécifique généré par un processeur |

`verdict` est l'endroit où un échantillon a quitté le pipeline, et `classification` est ce qu'une étape a conclu à son sujet. Les deux voyagent dans la réponse, et chacun filtre donc le champ dont il porte le nom. `stage` correspond à l'étape courante de l'échantillon ; `status` retient un échantillon dès qu'une étape de son historique porte ce statut. Un identifiant d'échantillon contenant un séparateur de chemin est refusé, car cet identifiant devient un chemin sur le système de fichiers et ce serveur peut être lié à toutes les interfaces.
