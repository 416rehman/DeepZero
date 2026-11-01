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
- `ctx.global_config`: パイプラインレベルの `settings`、`knowledge`、設定された `model`、そしてそのパイプラインの読み込み元ディレクトリを文字列で保持する `pipeline_dir` を含む TypedDict。最後のキーが存在するのは、`setup()` がこの設定だけを受け取りコンテキストを受け取らないからです。これがないと、パイプラインに同梱されるファイルを指す設定値が、代わりに作業ディレクトリを基準に解決されてしまいます。`ctx.get_setting(key)` と `ctx.get_knowledge(key)` はその短縮形です。
- `ctx.llm`: バックオフとリトライを内蔵した汎用のプロキシインスタンス（`LLMProtocol` の実装）。パイプラインがモデルを設定していない場合は `None` です。どのバックエンドを駆動するかはパイプラインの `model` 文字列から解決されるため、`ctx.llm.complete()` を呼ぶプロセッサは API キー経由でもローカルのエージェント CLI 経由でも同じように動きます。[モデルの選択]({{ '/ja/reference/pipeline-yaml.html' | relative_url }})を参照してください。
- `ctx.log`: 設定済みで名前空間の付いた `logging.Logger`。
- `ctx.progress`: 進捗報告のフック。`update(amount=, total=, description=)` を呼ぶことで、長時間かかるインジェストや一括処理のステージが、ハングしているように見えるのではなくダッシュボード上で動きを示せます。
- `ctx.shutdown_event`: `threading.Event`。実行が中断されるとセットされます。長い処理を行うプロセッサはこれを確認し、書き込みの途中で強制終了されるのではなく早期に復帰すべきです。
- `ctx.conclude(**fields)`: 個々のサンプルについてではなく、コーパスについての結論を記録します。答えが全体を通してしか出ない問いがあります。あるエンドポイントの背後にいるのがどのモデルなのか、山積みのクラッシュがいくつの異なるバグを表しているのか、といったものです。渡したフィールドはその実行の `conclusion` にマージされ、実行はその場で保存されます。そのため、中断された実行でも、そこまでに導き出していたものは残ります。

エンジンが `conclude` を実際の書き込み先につなぐのは `reduce` ステージと `bulk_map` ステージだけです。1 回の呼び出しですべてのサンプルを見るのがこの 2 つだからです。

```python
class ModelFingerprint(ReduceProcessor):
    def process(self, ctx: ProcessorContext, entries: list[ProcessorEntry]) -> list[str]:
        ctx.conclude(headline="every probe answers as the same model family", probes=len(entries))
        return [e.sample_id for e in entries]
```

Map ステージやインジェストステージでは、`ctx.conclude()` が使えるのは reduce ステージと bulk_map ステージだけであり、この呼び出しは無視されたことをログに残したうえで、何もしません。スレッドプールに広がるサンプルごとの処理は、自分自身と競合せずにコーパスを代弁することができないからです。最後に終わったサンプルが勝ち、負けた側は自分が上書きされたことを知ることさえありません。

### 実行フック

プロセッサは、エンジンから呼び出される特定のライフサイクルフックを実装します：

1. **`validate(ctx: ProcessorContext) -> list[str]`**: 最初のスキーマ検証時（`deepzero validate` 経由、または実行前）に呼び出されます。依存関係（バイナリの欠落、解析できない YAML など）に問題があれば、エラー文字列のリストを返します。ここでのコンテキストは縮小されたものです。`ctx.global_config` が持つのは `settings`、`knowledge`、`model` だけで、`pipeline_dir` のキーはなく、`ctx.llm` はまだプロバイダーが構築されていないため `None` です。そのどちらかに頼る検査は、パイプラインを読み違えます。`ctx.pipeline_dir` 自体は設定されているため、同じ場所に置かれたファイルはそちらから解決してください。
2. **`setup(global_config: dict) -> None`**: スレッドプールが動き出す前に、ちょうど 1 回だけ実行されます。
3. **`process(...)`**: 中心となる処理。シグネチャはプロセッサの種類によって異なります。
4. **`teardown() -> None`**: パイプラインの完了時、または致命的な中断時に実行されます。

サンプル 1 件あたりのコストが高い Map プロセッサでは、もう 1 つ上書きする価値のあるものがあります：

5. **`max_parallelism() -> int | None`**: 自動並行数の上限です。これが効くのは、ステージの YAML が `parallel: 0` を宣言している場合だけです。0 より大きい `parallel: N` は書かれたとおりに尊重され、この上限も `max_workers` 設定も参照される前に採用されます。サンプルごとに JVM、コンテナ、数ギガバイトのメモリを要する場合は int を返してください。自動調整を求めたステージが、コアごとに 1 つのワーカーを取ってしまうことがなくなります。デフォルトの `None` は上限なしを意味します。`parallel:` を省略することは `parallel: 0` と書くことと同じではありません。それを名指ししていないステージは 4 で読み込まれ、これは明示された数値として数えられるため、この上限がそこに届くことはありません。

### プロセッサインスタンスが持つもの

`ctx` が記述するのは実行そのものです。ステージに属するものは、プロセッサオブジェクト自身が持ちます。
- `self.config`: 解析済みの `Config` データクラス。プロセッサが `Config` を宣言していない場合は生の YAML 辞書です。
- `self.spec`: このインスタンスの生成元となった `StageSpec`。その名前、`config` ブロック、`parallel`、`on_failure`、`max_retries`、`timeout` を持ちます。
- `self.log`: ステージ名で名前空間化されたロガー。
- `self.global_config`: `ctx` が持つものと同じ `GlobalConfig`。`setup()` が走る前にエンジンが設定します。
- `self.processor_dir`: このプロセッサ自身の `.py` ファイルが置かれているディレクトリ。その隣に同梱されるスクリプト、テンプレート、ルールファイルのためのものです。これは `ctx.pipeline_dir` ではありません。パイプラインはまったく別の場所にあるプロセッサを名指しできるため、その場合この 2 つは別の場所を指します。
- `self.cache_dir`: `./.cache/<ステージ名>` にある永続的なディレクトリで、最初にアクセスされたときに作成されます。エンジンはこれを一切消さないため実行をまたいで残り、ダウンロードなど、繰り返すには高価すぎる作業の置き場になります。

### 設定定義

プロセッサが受け付ける YAML 設定は、`Config` という名前の埋め込み `@dataclass` で宣言します。エンジンは [パイプライン YAML]({{ '/ja/reference/pipeline-yaml.html' | relative_url }}) の中の `${VAR}` と `${VAR:-default}` を展開し、標準の Python [`dataclasses`](https://docs.python.org/3/library/dataclasses.html) を用いて、そのステージの `config` ブロックから `Config` のインスタンスを作成します。

フィールドを宣言することと、それを強制することは別です。データクラスが宣言していないキーは、このプロセッサが読まないものとして、受け付ける名前を並べたうえでログに残され、そして捨てられます。実行はそのまま続きます。`limit` はエンジン自身が読むため、この警告の対象外です。型は何も検査されません。設定されていない `${VAR}` は文字どおり残るのではなく空文字列に展開されるため、環境変数の欠落はエラーではなく、存在するが空のフィールドとして届きます。すべてのフィールドにデフォルトを与え、本当の検査は、どのサンプルにも触れる前に走る `validate()` で行ってください。

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
        # 上流の IngestProcessor が出力したデータを取得する
        sha = entry.upstream_data("discover", "sha256", default="UNKNOWN")

        # entry.source_path が解析対象そのもの。インジェストステージがこのサンプルに
        # ついて記録したものであり、それに触れる唯一の手がかりでもある
        entropy = self._shannon_entropy(entry.source_path.read_bytes())

        # ProcessorEntry はサンプルごとに隔離されたサンドボックスに束縛される
        out_file = entry.sample_dir / "heuristics.json"
        out_file.write_text(json.dumps({"sha256": sha, "entropy": entropy}))

        # ProcessorResult が経路を決める
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

### 結果の種類 (`ProcessorResult`)

Map / BulkMap プロセッサは、厳密に形式化された `ProcessorResult` を返さなければなりません：
- **`.ok(data={...}, artifacts={...})`**: 実行を `COMPLETED` として記録します。`data` の辞書はそのプロセッサの履歴ブロックに名前空間化されます。`artifacts` はキーを相対ファイルパスに対応付けます。
- **`.filter(reason="...", data={...})`**: サンプルの処理を静かに終了します。`SampleState.verdict` は `FILTERED` に変わります。
- **`.fail(error="...")`**: 致命的で予期しないエラーにより処理を終了します。`SampleState.verdict` は `FAILED` に変わります。
- **`.timed_out(budget)`**: 処理が壊れたのではなく、時間切れになったことを表します。`SampleState.verdict` は `TIMED_OUT` に変わり、予算も一緒に運ばれるため、レポートは代わりにどれだけ与えればよいかを示せます。自前で予算を課すプロセッサからはこれを返してください。ステージレベルの `timeout:` は、これを自分で生成します。

Map プロセッサはさらに **`should_skip(ctx, entry) -> str | None`** を上書きし、理由の文字列を返すことで、その作業はすでに済んでいると宣言できます。典型的には、自分の出力ファイルがすでにディスク上にある場合です。スキップされたサンプルは通過したものとして数えられ、下流へ進みます。これを行うときは、その出力をアーティファクトとして記録してください。`deepzero run --redo` が記録済みのアーティファクトを削除するのは、まさにキャッシュされたファイルが再び採用されるのを防ぐためであり、実行が記録しなかったファイルは、それを説明する状態よりも長く残ってしまいます。

パスだけを見るのではなく、必ず `entry.cache_is_valid` も一緒に確認してください。

```python
def should_skip(self, ctx: ProcessorContext, entry: ProcessorEntry) -> str | None:
    if entry.cache_is_valid and (entry.sample_dir / "out.json").exists():
        return "cached"
    return None
```

`cache_is_valid` が `False` になるのは、ディスク上のそのファイルが、その後に書き換えられたプロンプト、ルールセット、設定から生まれている場合です。エンジンは、前回の実行に対して記録された入力ダイジェストと、このステージの入力が今生み出すダイジェストとを突き合わせます。`.exists()` だけを見る `should_skip` は、パイプラインがもう立てていない問いへの答えを採用し直してしまいます。組み込みの LLM ステージも同梱の Semgrep スキャナーも、すでにあるファイルを採用する箇所ではこの防護を取り入れています。

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

### エントリが持つもの (`ProcessorEntry`)

Map、BulkMap、Reduce のいずれのプロセッサにも、生のサンプルではなくエントリが渡されます。
- `entry.sample_id`: そのサンプルの一意な識別子であり、その状態が保存されるときのキーでもあります。
- `entry.source_path`: 解析対象への `Path`。インジェストステージがこのサンプルについて記録したものです。Map プロセッサが自分の入力に触れる唯一の手がかりがこれです。
- `entry.filename`: 表示用の名前。ログとレポートで使われます。
- `entry.sample_dir`: このサンプル専用に隔離された作業ディレクトリ。出力はここに置きます。
- `entry.cache_is_valid`: すでに `sample_dir` にある出力が、このステージの現在の入力から生み出されたものかどうか。前述の `should_skip` の項で説明したとおりです。

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
