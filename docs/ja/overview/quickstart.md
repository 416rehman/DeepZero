---
layout: default
title: クイックスタート
order: 1
---

## クイックスタート

DeepZero は、分析するためのターゲットコーパスと、その処理方法を詳述する[パイプライン設定]({{ '/ja/reference/pipeline-yaml.html' | relative_url }})を必要とします。[セキュリティ解析パイプライン]({{ '/ja/reference/included-pipeline.html' | relative_url }})が 2 つ同梱されています。1 つは、未加工のバイナリデータセット（Snappy Driver Installer のコーパスなど）の中から新しい BYOVD（Bring Your Own Vulnerable Driver）候補を探し、その際 [LOLDrivers プロジェクト](https://www.loldrivers.io/)を使って既知のハッシュを明示的に除外するものです。もう 1 つは、git リポジトリを対象にソースコードを監査するものです。

### 1. インストール

DeepZero には **Python 3.11+** が必要です。

```bash
git clone https://github.com/416rehman/DeepZero.git
cd DeepZero
python -m pip install -e .
```

以下のデモには基本インストールだけで十分です。2 つのセキュリティ解析パイプラインには、手順 3 の追加設定が必要です。

### 2. ローカルデモを試す

基本パッケージをインストールしたら、クローンしたリポジトリ直下で同梱の安全なテキストサンプルを実行します。

```sh
deepzero run pipelines/demo/samples -p pipelines/demo/pipeline.yaml
deepzero status -p pipelines/demo/pipeline.yaml
deepzero report -p pipelines/demo/pipeline.yaml --open
```

デモに API キー、外部ツール、ドライバー群は不要です。2 ファイルを検出し、`hello.txt` を残して `tiny.txt` をサイズで除外し、HTML レポートを生成します。オーケストレーションと状態保存の例であり、脆弱性検出は行いません。同じコマンドを再実行すると保存済み結果から再開します。[デモの説明](https://github.com/416rehman/DeepZero/tree/main/pipelines/demo)も参照してください。

### 3. セキュリティ解析の連携を設定する

```sh
python -m pip install -e ".[full]"
```

以降のコマンドはクローンしたリポジトリ内で実行してください。`full` には PE 解析用の LIEF と API モデル用の LiteLLM が含まれます。エンジンのみなら `python -m pip install -e .` でインストールできます。

外部ツールも同じ環境にインストールしてください。

- 両セキュリティ解析パイプライン: PATH 上の **Semgrep**（`python -m pip install semgrep`）と LLM バックエンド。
- ソース監査: PATH 上の **Git**。
- ドライバー解析: **Ghidra** とそのバージョンが対応する **JDK**。`.env` の `GHIDRA_INSTALL_DIR` に自分のインストール先を設定します。
- 既定の LLM: **Claude Code CLI** をインストールし、自分のアカウントでサインインしてください。CLI の既定モデルを使い、API キーは不要です。API モデルとキーを下で設定することもできます。

WSL を使う場合は、ツール、Python、DeepZero をすべて WSL 内にインストールして実行してください。

#### 環境設定

AI 分析ステージを統合する場合は、`.env` ファイルを作成して API キーを構成します。

```bash
cp .env.example .env
```

PowerShell では `Copy-Item .env.example .env` を使います。`.env` の `DEEPZERO_MODEL` で両セキュリティ解析パイプラインのバックエンドとモデルを変更でき、`-m` なら 1 回の実行だけ変更できます。たとえば `DEEPZERO_MODEL=openai/gpt-4o` には自分の `OPENAI_API_KEY` が必要です。

同梱の 2 つのセキュリティ解析パイプラインはどちらも `claude-code` モデルを宣言しています。これは、すでにサインイン済みの Claude Code CLI を駆動するもので、API キーをまったく必要としません。代わりに任意の [LiteLLM モデル]({{ '/ja/reference/pipeline-yaml.html' | relative_url }})を、パイプラインの `model` フィールドまたはコマンドラインの `-m` で指定することもできます。上記の API キーはそのためのものです。

### 4. 実行に踏み切る前の確認

これらの実行は長時間かかります。次のものは安価で、数時間ではなく数秒で答えを返し、しかも何も開始しません。

```bash
# すべてのプロセッサを解決し、その前提条件と、すべてのプロンプトを検査する
deepzero validate pipelines/loldrivers/pipeline.yaml
```

エラーを報告したときは終了コード 1 を返すため、読むためだけのものではなく、コミットフックや CI のステップとしても機能します。

### 5. パイプラインの実行

ターゲットパスに対して同梱の LOLDrivers パイプラインを実行します。

```bash
deepzero run ./drivers -p pipelines/loldrivers/pipeline.yaml
```

`./drivers` は自分のドライバー群のパスに置き換えるか、1 行に 1 つのリポジトリ URL を書いた `repos.txt` を作成してください。これらの入力データは同梱されていません。

あるいは、リポジトリのマニフェストやチェックアウトのディレクトリに対してソースコード監査を実行します。

```bash
deepzero run repos.txt -p pipelines/source_audit/pipeline.yaml
```

このどちらにも `--preflight` を付けられます。これは、LLM バックエンドが実際にサインイン済みかを、ごく小さな呼び出し 1 回で確認します。バックエンドの準備ができていなければ数秒で停止し、そうでなければ実行はそのまま通常どおり進みます。つまり、単独で打ち込む確認コマンドではなく、もともと始めるつもりだった実行に添えるフラグです。これがなければ、数時間経ってから最初の評価ステージで気づくことになります。

```bash
deepzero run ./drivers -p pipelines/loldrivers/pipeline.yaml --preflight
```

<div class="callout">
    <p><strong>注意:</strong> DeepZero は安全に<a href="{{ '/ja/overview/architecture.html' | relative_url }}">実行を並列化</a>し、中間出力をキャッシュします。正常に停止するには、SIGINT（<code>Ctrl+C</code>）を送信してください。同じパラメータでの後続の実行は、<a href="{{ '/ja/system/state-persistence.html' | relative_url }}">ディスクに保存された状態</a>から即座に再開されます。</p>
</div>

コーパスごとに専用のワークディレクトリが割り当てられます。そのため、同じパイプラインを 2 つ目のターゲットに向けても、1 つ目の結果に再開するのではなく、2 つ目の実行が始まります。どちらも引き続き再開可能です。

### 6. 結果を読む

実行は最初のステージの前にレポートの URL を表示し、結果が届くたびにそのレポートを更新し続けます。そのため、実行中に開いて眺めることができます。進行中の実行に対するものも含め、いつでも改めて構築するには次のようにします。

```bash
deepzero report -p loldrivers --open
```

パイプラインだけを名指しすると、そのパイプラインの最新のコーパスに解決され、そのパイプラインが他にどのコーパスを見てきたかも示されます。最も新しい実行が、いつも尋ねられている実行だとは限らないからです。どのパイプラインやコーパスが生み出したものかを問わず、`work` の下にあるすべての実行を新しい順に見るには、次のようにします。

```bash
deepzero runs
```

各実行のパイプライン、コーパス、ステータス、サンプル数が一覧され、そのうちの 1 つを閲覧するための `deepzero report -w <dir>` の行が表示されます。フラグなしの `deepzero report` も同じ問いに直接答えます。実行が 1 つならそれが選ばれ、複数あれば選ぶための一覧になります。

レポートは実行状態だけから導出されるため、削除して再構築できます。また、見つかったものを何と呼ぶかは[パイプラインが宣言します]({{ '/ja/reference/pipeline-yaml.html' | relative_url }})。
