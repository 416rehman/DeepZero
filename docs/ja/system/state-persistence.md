---
layout: default
title: 状態の永続化
order: 1
---

## 永続化サブシステム

パイプラインのデータの整合性は、抽象的な `StateStore` モジュール（`engine/state.py` で定義）によってバックアップされます。ファイルシステムにバックアップされる実装は、SIGKILL や OS レベルのカーネル割り込み中でも、厳密なアトミック置換によって破損から保護されます。

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
            <text x="60" y="-5" font-family="JetBrains Mono, monospace" font-size="14" font-weight="bold" text-anchor="middle" fill="var(--text-primary)">メモリ</text>
            <text x="60" y="15" font-family="Inter, sans-serif" font-size="12" text-anchor="middle" fill="var(--text-tertiary)">SampleState</text>
        </g>

        <!-- Path to Temp -->
        <path d="M 220 120 L 320 120" fill="none" stroke="var(--text-tertiary)" stroke-width="2" stroke-dasharray="6 6"/>
        <text x="270" y="110" font-family="Inter, sans-serif" font-size="12" text-anchor="middle" fill="var(--text-secondary)">シリアライズ</text>

        <!-- Temp Node -->
        <g transform="translate(320, 120)">
            <rect x="0" y="-40" width="140" height="80" fill="var(--bg-secondary)" stroke="var(--border)" stroke-width="2" stroke-dasharray="4 4" rx="8"/>
            <text x="70" y="-5" font-family="JetBrains Mono, monospace" font-size="14" font-weight="bold" text-anchor="middle" fill="var(--text-secondary)">state.tmp</text>
            <text x="70" y="15" font-family="Inter, sans-serif" font-size="12" text-anchor="middle" fill="var(--text-tertiary)">バッファ</text>
        </g>

        <!-- Path to Final -->
        <path d="M 460 120 L 580 120" fill="none" stroke="var(--accent)" stroke-width="3"/>
        <circle cx="0" cy="0" r="5" fill="var(--accent)">
            <animateMotion path="M 460 120 L 580 120" dur="1.5s" repeatCount="indefinite" />
        </circle>
        <text x="520" y="110" font-family="Inter, sans-serif" font-size="12" font-weight="bold" text-anchor="middle" fill="var(--accent)">os.replace</text>
        <text x="520" y="140" font-family="Inter, sans-serif" font-size="10" text-anchor="middle" fill="var(--text-tertiary)">アトミック置換</text>

        <!-- Final Node -->
        <g transform="translate(580, 120)">
            <rect x="-10" y="-30" width="120" height="80" fill="var(--bg-primary)" stroke="var(--border)" stroke-width="1" rx="4"/>
            <rect x="-5" y="-35" width="120" height="80" fill="var(--bg-primary)" stroke="var(--border)" stroke-width="1" rx="4"/>
            <rect x="0" y="-40" width="120" height="80" fill="var(--bg-primary)" stroke="var(--text-primary)" stroke-width="2" rx="4"/>
            <text x="60" y="-5" font-family="JetBrains Mono, monospace" font-size="14" font-weight="bold" text-anchor="middle" fill="var(--text-primary)">state.json</text>
            <text x="60" y="15" font-family="Inter, sans-serif" font-size="12" text-anchor="middle" fill="var(--text-tertiary)">永続化</text>
        </g>
    </svg>
</div>

### アトミック置換 (`atomic_replace`)

アクティブなアーティファクト（`state.json` など）に破壊的に書き込むのではなく、永続化レイヤーはシリアライゼーションを中間の `.tmp` バッファにルーティングします。バッファの名前は、宛先の名前の拡張子を付け足すのではなく置き換えたものになるため、`state.json` は `state.tmp` として用意されます。シリアライゼーションが完了すると、`os.replace` が宛先の inode をアトミックに上書きします。ホストの EDR やアンチウイルスが新規に作成されたバイナリを走査することで発生する `PermissionError` のロックは、リトライとバックオフの仕組みが捕捉します。

### スキーマのバージョニング

バージョンが付与され、かつそれが検査されるのは、サンプルの状態です。`state.json` は内部の `STATE_VERSION` を保持する `_version` フィールドとともに書き出され、読み込み時にそれより古いものは拒否されます。v2 のランタイムで v1 の JSON を読めば、もはやそのレコードを説明しないスキーマで解釈して予測できない変異バグを誘発するのではなく、何も返ってきません。

残る 2 つのファイルは検査されません。`run_manifest.json` も同じ `_version` フィールドを持ちますが、それが読み返されることはありません。このマニフェストは、サンプルが保存されるたびにそこから書き直される派生的な要約だからです。`run.json` はバージョンの付与も検査もされません。JSON を `RunState` 自身のフィールド名で絞り込み、認識できないものを捨てる形で読み込まれるため、古いバージョンが書いたレコードも、持っているフィールドはそのまま読み込まれ、残りはデフォルトのままになります。

### ワークスペースの階層

```text
work/<pipeline_name>/<corpus_key>/
├── run.json             # シリアライズされた `RunState`：実行メトリクス、パイプラインのメタデータ、
│                        #   コーパス全体についての結論、そして実行の生存記録
├── pipeline.yaml        # 初期化時のパイプライン YAML 設定の不変スナップショット
├── run_manifest.json    # 全サンプルを集約した全体像。`status` と `interactive` が読む
├── report/              # 閲覧可能な HTML レポート。結果が届くたびに再構築される
└── samples/
    └── <sample_id>/     # 分離されたサンドボックス
        ├── state.json   # シリアライズされた `SampleState`：`StageOutput` マップの完全な台帳
        ├── context.md   # `engine/context.py` が生成する統合済みの LLM コンテキスト
        └── ...          # プロセッサ固有のアーティファクト
```

`RunState` には、メトリクスのほかに名前を挙げておく価値のあるものが 2 つあります。`conclusion` は、個々のサンプルについてではなくコーパスについての結論を保持します。あるエンドポイントの背後にいるのがどのモデルなのか、山積みのクラッシュがいくつの異なるバグを表しているのか、スコープが正しく設定されているのか、といったものです。これは、すべてのサンプルを見るステージが `ctx.conclude(...)` を通じて書き込むもので、答えがすべてサンプル単位である多くのパイプラインでは空のままです。その隣にある `host`、`pid`、`pid_token`、`heartbeat_at` は、誰がその実行を書いているかを記録します。`running` というステータスは、その背後のプロセスを確かめられるまでは主張にすぎず、強制終了された実行が自らその主張を取り下げることは決してありません。生きている実行と見捨てられた実行とを別のプロセスが見分けられるのは、この 4 つのフィールドがあるからです。

### コーパスのスコープ

同じパイプラインに与えた 2 つのターゲットを切り分けているのが、この `<corpus_key>` のセグメントです。これは実行対象から導出されます。ベース名に、解決された絶対パスの短いダイジェストを付け加えたもので、読みやすさと一意性を両立させています。Windows では先にパスの大文字小文字を畳み込みます。`C:\Drivers` と `c:\drivers` は同じコーパスだからです。

このセグメントがなければ、同じパイプラインを 2 つ目のコーパスに向けたときに、1 つ目のサンプルストアに再開してしまいます。ディスク上のどのファイルにも対応しなくなったサンプルが解析済みとして扱われ、実行結果は与えられてもいないコーパスについて報告することになります。このセグメントがあることで、各コーパスは自身の状態、自身のマニフェスト、自身のレポートを持ち、それぞれ独立して再開します。

解決後のパスが同じであれば常に同じキーになるため、再実行すれば中断した場所に戻ります。このディレクトリ以下はほぼすべてが派生物であり、`report/` を削除しても、通常は失うのは再構築の手間だけで、実行そのものではありません。

例外が 1 つだけあり、それは取り戻せません。`report/marks.json` はレビューマークを保持します。サンプルごとに、読み手が確かめたかどうか、そして成り立っていたか成り立たなかったか、加えて書き留めた記述です。それは読み手が何を確かめたかであり、どのステージにも知りえないため、実行状態のどこにも存在しません。これがレポートの隣に保存し直されるのは、まさに、誰か一人のブラウザに取り残されるのではなく、開いた人すべてに対して描画されるようにするためであり、再構築のたびに読み直されます。`report/` を削除すればこれは失われます。開始前にコーパスのディレクトリごと削除する `run --clean` でも同じです。

### `history` 台帳

`SampleState.history` の辞書は、プロセッサのステージ名を `StageOutput` のインスタンスに厳密に対応付けます。出力のデータ構造は厳格に分離され、名前空間化されています。上流の Map からメトリクスを取り出す下流のプロセッサは、`history["upstream_processor"].data.get("metric")` のように問い合わせます（[カスタムプロセッサの構築]({{ '/ja/extensibility/building-custom.html' | relative_url }})を参照）。

この名前空間化により、異なるヒューリスティック解析手法の間でフィールドが衝突することが恒久的に防がれます。

### ステージ入力のフィンガープリント

各 `StageOutput` は `input_digest` も運びます。これは、そのステージが何を生み出すかを決めるもののすべて、すなわちそのプロセッサ、その設定、そしてその設定が指し示すファイル（プロンプト、ルールセット、解析スクリプトなど）のフィンガープリントです。ステージの完了時に記録され、再開した実行がそのステージはもう終わっているかを問うときに突き合わされます。

両方のダイジェストがそろっていて食い違う場合、保存されている結果は、パイプラインがもう持っていない入力を記述しています。したがってそれは完了ではなく古いものとして数えられ、そのステージは走り直します。再開した実行が、どの結果が今も成り立っているのかを自ら判断できるのはこれによるものであり、読み手が何を書き換えたかを覚えている必要はありません。どちらかのダイジェストが空であればこの問いは立てられず、答えようのない問いは、数時間かかったかもしれない作業を捨てる根拠にはなりません。そのため、ダイジェストが記録される以前に書き出された結果は、やり直されるのではなく信頼されます。

コーパスそのものはフィンガープリントに含まれません。コーパスはすでにワークディレクトリによってキー付けされていますし、すべてのサンプルを読むかどうかを決めるためにすべてのサンプルを読めば、その確認が守ろうとしているステージよりも高くつきます。
