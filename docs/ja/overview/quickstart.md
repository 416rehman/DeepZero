---
layout: default
title: クイックスタート
order: 1
---

## クイックスタート

DeepZero は、分析するためのターゲットコーパスと、その処理方法を詳述する[パイプライン設定]({{ '/ja/reference/pipeline-yaml.html' | relative_url }})を必要とします。[完全なパイプライン]({{ '/ja/reference/included-pipeline.html' | relative_url }})が 2 つ同梱されています。1 つは、未加工のバイナリデータセット（Snappy Driver Installer のコーパスなど）の中から新しい BYOVD（Bring Your Own Vulnerable Driver）候補を探し、その際 [LOLDrivers プロジェクト](https://www.loldrivers.io/)を使って既知のハッシュを明示的に除外するものです。もう 1 つは、git リポジトリを対象にソースコードを監査するものです。

### 1. インストール

DeepZero には **Python 3.11+** が必要です。

```bash
git clone https://github.com/416rehman/DeepZero.git
cd DeepZero
pip install -e .
```

### 2. 環境設定

AI 分析ステージを統合する場合は、`.env` ファイルを作成して API キーを構成します。

```bash
cp .env.example .env
```

同梱の 2 つのパイプラインはどちらも `claude-code` モデルを宣言しています。これは、すでにサインイン済みの Claude Code CLI を駆動するもので、API キーをまったく必要としません。代わりに任意の [LiteLLM モデル]({{ '/ja/reference/pipeline-yaml.html' | relative_url }})を、パイプラインの `model` フィールドまたはコマンドラインの `-m` で指定することもできます。上記の API キーはそのためのものです。

### 3. 実行に踏み切る前の確認

これらの実行は長時間かかります。以下の 2 つはどちらも安価で、数時間ではなく数秒で失敗します。

```bash
# すべてのプロセッサを解決し、その前提条件と、すべてのプロンプトを検査する
deepzero validate pipelines/loldrivers/pipeline.yaml
```

```bash
# LLM バックエンドが実際にサインイン済みかを、ごく小さな呼び出し 1 回で確認する
deepzero run C:\drivers -p .\pipelines\loldrivers\pipeline.yaml --preflight
```

### 4. パイプラインの実行

ターゲットパスに対して同梱の LOLDrivers パイプラインを実行します。

```bash
deepzero run C:\drivers -p .\pipelines\loldrivers\pipeline.yaml
```

あるいは、リポジトリのマニフェストやチェックアウトのディレクトリに対してソースコード監査を実行します。

```bash
deepzero run repos.txt -p .\pipelines\source_audit\pipeline.yaml
```

<div class="callout">
    <p><strong>注意:</strong> DeepZero は安全に<a href="{{ '/ja/overview/architecture.html' | relative_url }}">実行を並列化</a>し、中間出力をキャッシュします。正常に停止するには、SIGINT（<code>Ctrl+C</code>）を送信してください。同じパラメータでの後続の実行は、<a href="{{ '/ja/system/state-persistence.html' | relative_url }}">ディスクに保存された状態</a>から即座に再開されます。</p>
</div>

コーパスごとに専用のワークディレクトリが割り当てられます。そのため、同じパイプラインを 2 つ目のターゲットに向けても、1 つ目の結果に再開するのではなく、2 つ目の実行が始まります。どちらも引き続き再開可能です。

### 5. 結果を読む

実行は最初のステージの前にレポートの URL を表示し、結果が届くたびにそのレポートを更新し続けます。そのため、実行中に開いて眺めることができます。進行中の実行に対するものも含め、いつでも改めて構築するには次のようにします。

```bash
deepzero report -p loldrivers --open
```

レポートは実行状態だけから導出されるため、削除して再構築できます。また、見つかったものを何と呼ぶかは[パイプラインが宣言します]({{ '/ja/reference/pipeline-yaml.html' | relative_url }})。
