---
layout: default
title: 基本アーキテクチャ
order: 2
---

## エンジンアーキテクチャ

DeepZero オーケストレーションエンジンは、[パイプライン]({{ '/ja/reference/pipeline-yaml.html' | relative_url }}) によって定義された厳密な有向処理グラフ上で動作します。実行エンジンは、上限のあるスレッドプール（[`ThreadPoolExecutor`](https://docs.python.org/3/library/concurrent.futures.html#threadpoolexecutor)）に並列処理を展開しながら、フォールトトレラントで再開可能な[状態管理]({{ '/ja/system/state-persistence.html' | relative_url }})を保証します。

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

### コンポーネントのライフサイクル

データモデルは、サンプルが進むにつれて以下の抽象化を経て遷移します：

1. **`Sample`**: `IngestProcessor` によって出力される基本構造。物理的な `source_path` を一意の `sample_id`（通常は SHA-256 ハッシュまたは決定論的な UUID）に束縛し、そのサンプルの `data` 辞書を初期化します。
2. **`SampleState`**: `StateStore` によって維持される永続的なレコード。判定（`PENDING`、`ACTIVE`、`FILTERED`、`FAILED`、`TIMED_OUT`、`COMPLETED`）を追跡し、プロセッサごとの `StageOutput` インスタンスを対応付けた `history` を保持します。`TIMED_OUT` を `FAILED` と分けているのは、それがサンプルについて何も語っていないからであり、予算を延ばせば変わりうる唯一の結果だからです。
3. **`ProcessorEntry`**: Map / BulkMap / Reduce プロセッサに渡される、動的に生成されるメモリ効率の良いファサード。遅延ロードの仕組み（`_store`）を注入しており、`.history` または `.upstream_data()` にアクセスされたときにだけ過去の実行データをディスクから取得します。

### 処理パラダイム

プロセッサは実行トポロジーと並行モデルを決定します。すべては基底の `Processor` クラスを継承し、`validate()`、`setup()`、`process()`、`teardown()` というライフサイクルフックを公開します。自作する方法については[カスタムプロセッサの構築]({{ '/ja/extensibility/building-custom.html' | relative_url }})を参照してください。

#### `IngestProcessor` (1 → N)
- **型シグネチャ:** `process(ctx: ProcessorContext, target: Path) -> list[Sample]`
- **並行性:** 同期実行。パイプラインの実行ごとにちょうど 1 回だけ実行されます。
- **役割:** 最初のコーパスを生成します。インジェスト以前には上流データが存在しません。

#### `MapProcessor` (1 → 1)
- **型シグネチャ:** `process(ctx: ProcessorContext, entry: ProcessorEntry) -> ProcessorResult`
- **並行性:** スレッドによるファンアウト。パイプライン YAML の `parallel:` フィールドで設定します。`parallel: 0` は自動調整で、`max_workers` と、プロセッサが `max_parallelism()` から返す値の両方に縛られます。
- **制約:** 厳密にスレッドセーフでなければなりません。共有される可変状態は避けてください。
- **予算:** `timeout:` が縛るのは、1 つのサンプルについてステージが待つ長さであって、作業が走る長さではありません。ワーカースレッドは強制終了されるのではなく放置されるため、外部プロセスを起動するプロセッサは、そのプロセッサ自身がそのプロセスに制限を課すべきです。

#### `BulkMapProcessor` (N → N)
- **型シグネチャ:** `process(ctx: ProcessorContext, entries: list[ProcessorEntry]) -> list[ProcessorResult]`
- **並行性:** アクティブなサンプルの一部または全体に対する同期実行。
- **役割:** 外部プロセスの起動（一枚岩の JVM ツールや Semgrep の一括スキャンなど）を最適化し、重い起動コストを複数のサンプルで償却します。出力は入力の `entries` リストと厳密に添字が対応していなければなりません。

#### `ReduceProcessor` (N → M)
- **型シグネチャ:** `process(ctx: ProcessorContext, entries: list[ProcessorEntry]) -> list[str]`
- **並行性:** 全体の同期バリア。アクティブなすべてのサンプルがこのステージに到達するまで、スレッド実行を停止します。
- **役割:** どのサンプルが生き残るかを定める `sample_id` 文字列の順序付きリストを返します。返されたリストに含まれないサンプル ID は、恒久的に `SampleStatus.FILTERED` が付きます。

### 出力の契約

プロセッサが何をしていようと、記録するものは同じ 3 つです。任意の内容を持ち名前空間化された辞書である `data`、ラベルを相対ファイルパスに対応付ける `artifacts`、そしてステータスです。この契約は意図的に特定の領域に依存しないようにしてあり、エンジンより下流にあるものはすべてこの上に成り立っています。

その帰結がもっともはっきり表れているのが[レポート]({{ '/ja/reference/cli.html' | relative_url }})です。レポートはパイプラインのステージではなく、永続化された状態の射影です。どのプロセッサでも読めたはずの同じ `data` と `artifacts` を読んでいるだけであり、だからこそドライバー探索でもソースコード監査でもそれ以外でも、レポート側のコードがそれらの中身を知らないまま描画できます。パイプラインが与えるのは語彙だけで、それはコードではなく [YAML のブロック]({{ '/ja/reference/pipeline-yaml.html' | relative_url }})です。

レポートは実行ディレクトリにない情報を一切持たないため、実行中に構築することも、削除したあとに再構築することも、数週間前に終わった実行に対してもう一度構築することもできます。LLM のレイヤーを差し替えられるのも同じ性質によるものです。バックエンドはパイプラインのモデル文字列から選択され、どのバックエンドが応答したかを、プロセッサもステージも状態ファイルも意識しません。
