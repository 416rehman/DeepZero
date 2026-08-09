---
layout: default
title: プロセッサの構築
order: 2
---

## カスタムプロセッサの構築

ユーザーのロジックは、`deepzero.engine.stage` の型付き抽象化を拡張することで DeepZero に統合されます。これらのステージが実行フェーズにどう対応するかは、[基本アーキテクチャ]({{ '/ja/overview/architecture.html' | relative_url }})を参照してください。

### プロセッサコンテキスト (`ProcessorContext`)

各ライフサイクルフックに注入される `ctx` オブジェクトは、システム全体のコンテキストとユーティリティを提供します：
- `ctx.pipeline_dir`: 実行中のパイプラインのルートディレクトリ。ローカルのテンプレートやルールセットを解決するのに役立ちます。
- `ctx.global_config`: パイプラインレベルの `settings`、`knowledge`、および設定された `model` を含む TypedDict。`ctx.get_setting(key)` と `ctx.get_knowledge(key)` はその短縮形です。
- `ctx.llm`: バックオフとリトライを内蔵した汎用のプロキシインスタンス（`LLMProtocol` の実装）。パイプラインがモデルを設定していない場合は `None` です。どのバックエンドを駆動するかはパイプラインの `model` 文字列から解決されるため、`ctx.llm.complete()` を呼ぶプロセッサは API キー経由でもローカルのエージェント CLI 経由でも同じように動きます。[モデルの選択]({{ '/ja/reference/pipeline-yaml.html' | relative_url }})を参照してください。
- `ctx.log`: 設定済みで名前空間の付いた `logging.Logger`。
- `ctx.progress`: 進捗報告のフック。`update(amount=, total=, description=)` を呼ぶことで、長時間かかるインジェストや一括処理のステージが、ハングしているように見えるのではなくダッシュボード上で動きを示せます。
- `ctx.shutdown_event`: `threading.Event`。実行が中断されるとセットされます。長い処理を行うプロセッサはこれを確認し、書き込みの途中で強制終了されるのではなく早期に復帰すべきです。

### 実行フック

プロセッサは、エンジンから呼び出される特定のライフサイクルフックを実装します：

1. **`validate(ctx: ProcessorContext) -> list[str]`**: 最初のスキーマ検証時（`deepzero validate` 経由、または実行前）に呼び出されます。依存関係（バイナリの欠落、解析できない YAML など）に問題があれば、エラー文字列のリストを返します。
2. **`setup(global_config: dict) -> None`**: スレッドプールが動き出す前に、ちょうど 1 回だけ実行されます。
3. **`process(...)`**: 中心となる処理。シグネチャはプロセッサの種類によって異なります。
4. **`teardown() -> None`**: パイプラインの完了時、または致命的な中断時に実行されます。

### 設定定義

受け入れる YAML 設定を厳密に定義し検証するには、`Config` という名前の埋め込み `@dataclass` を使用します。エンジンは [パイプライン YAML]({{ '/ja/reference/pipeline-yaml.html' | relative_url }}) の辞書を解析して `Config` オブジェクトのインスタンスを作成し、その際に標準の Python [`dataclasses`](https://docs.python.org/3/library/dataclasses.html) を用いて `${ENV_VARS}` を自動的に完全展開します。

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
        # 上流の IngestProcessor が出力したデータを取得する
        sha = entry.upstream_data("discover", "sha256", default="UNKNOWN")

        # ProcessorEntry はサンプルごとに隔離されたサンドボックスに束縛される
        out_file = entry.sample_dir / "heuristics.json"
        out_file.write_text('{"entropy": 7.1}')

        # ProcessorResult が経路を決める
        if self.config.target_arch != "x86_64":
            return ProcessorResult.filter(reason="unsupported_arch")

        return ProcessorResult.ok(
            artifacts={"heuristics": "heuristics.json"},
            data={"analyzed": True, "entropy_ok": True}
        )
```

### 結果の種類 (`ProcessorResult`)

Map / BulkMap プロセッサは、厳密に形式化された `ProcessorResult` を返さなければなりません：
- **`.ok(data={...}, artifacts={...})`**: 実行を `COMPLETED` として記録します。`data` の辞書はそのプロセッサの履歴ブロックに名前空間化されます。`artifacts` はキーを相対ファイルパスに対応付けます。
- **`.filter(reason="...", data={...})`**: サンプルの処理を静かに終了します。`SampleState.verdict` は `FILTERED` に変わります。
- **`.fail(error="...")`**: 致命的で予期しないエラーにより処理を終了します。`SampleState.verdict` は `FAILED` に変わります。

### 後続ステージが使えるものの宣言

プロセッサの `data` のキーとアーティファクトは、そのプロセッサより後に走るステージのプロンプトから使えるようになります。その名前を `provides` に宣言しておくと、未知の名前が何も描画されないまま通り過ぎるのではなく、実行前に `deepzero validate` がプロンプトを検査できます：

```python
class Decompiler(MapProcessor):
    description = "Static heuristics extraction"
    provides = (
        "device_name",                    # このプロセッサが data に入れるキー
        "decompiled_dispatch_ioctl_c",    # アーティファクト decompiled/dispatch_ioctl.c
    )
```

アーティファクトの名前は、そのパスの区切り文字と拡張子を名前に畳み込んだものです。`engine/stage.py` の `template_key_for_artifact` が、レンダリングと検証の双方が従う唯一の規則です。ときどきしか記録されない名前も列挙してください。プロンプト側は、それが存在しない場合にも耐えることが前提になっています。プロンプトが受け取るものについては[プロンプトの値]({{ '/ja/reference/pipeline-yaml.html' | relative_url }})を参照してください。

### 上流データへのアクセス

プロセッサは本質的に、先行するプロセッサが生成したアーティファクトやデータに依存します。`ProcessorEntry` ファサードは、これらのデータをそのまま取得できる遅延ロード方式のヘルパーメソッドを公開しています：

```python
# 特定のフィールドの短縮取得（フォールバック付き）
sha = entry.upstream_data("discover", "sha256", default="")

# 直前のステージの StageOutput オブジェクトをそのまま取得
output = entry.upstream("scan")
findings = output.data.get("finding_count", 0)
json_file = output.artifacts.get("findings_file")
```

### 基底クラス

パイプラインのトポロジー要件に応じて、適切な基底クラスを拡張します：

| 基底クラス | プロセッサタイプ | `process()` のシグネチャ |
|-----------|---------------|----------------------|
| `IngestProcessor` | `ingest` | `(ctx, target: Path) → list[Sample]` |
| `MapProcessor` | `map` | `(ctx, entry: ProcessorEntry) → ProcessorResult` |
| `BulkMapProcessor` | `bulk_map` | `(ctx, entries: list[ProcessorEntry]) → list[ProcessorResult]` |
| `ReduceProcessor` | `reduce` | `(ctx, entries: list[ProcessorEntry]) → list[str]` |
