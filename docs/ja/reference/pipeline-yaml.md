---
layout: default
title: パイプライン YAML
order: 2
---

## パイプライン設定

DeepZero における **パイプライン** は、継続的で回復力のあるデータ変換処理を定義する宣言型の実行グラフです。未加工の物理データセットを、信号の濃い分析用データセットへと変換します。

パイプラインのスキーマは YAML で厳密に定義されています。DeepZero は設定を動的に解決し、シェルと同じ形式の変数展開（`${VAR:-default}` など）をサポートします。

### 設定スキーマ

```yaml
name: my_pipeline
description: 標準的な脆弱性調査パイプライン
version: "1.0"
model: openai/gpt-4o  # スキームがバックエンドを選択する。後述

settings:
  work_dir: work
  max_workers: 8  # ThreadPoolExecutor のスレッド数に対する全体の上限

stages:
  # ステージ 1: 必ず IngestProcessor であること
  - name: discover
    processor: file_discovery
    config:
      extensions: ["*"]

  # ステージ 2: 同期フィルタ
  - name: filter
    processor: metadata_filter
    config:
      require:
        is_executable: true

  # ステージ 3: 待ち時間の長い Map 処理
  - name: decompile
    processor: ghidra_decompile/ghidra_decompile.py
    parallel: 4           # 同時に走る Ghidra JVM を 4 つに制限する
    timeout: 300          # process.py 経由でサンプルごとに 300 秒の強制終了時間を課す
    on_failure: skip      # 中断せず静かに例外を処理する (skip, retry, abort)
    max_retries: 2        # リトライ回数の上限
    config:
      ghidra_install_dir: ${GHIDRA_INSTALL_DIR}
```

### ステージのオプション

`stages:` 配列の下に定義される各ステージは、以下の属性を受け付けます。

| フィールド | タイプ | デフォルト | 説明 |
|-------|------|----------------|-------------|
| `name` | string | `stage_N` | パイプライン内で一意なステージ名 |
| `processor` | string | 必須 | プロセッサの参照（後述） |
| `config` | dict | `{}` | プロセッサ固有の設定 |
| `parallel` | int | `4` | Map プロセッサの並行数。`0` は `os.cpu_count()` に自動調整 |
| `timeout` | int | `0` | サンプルごとのタイムアウト秒数（0 はタイムアウトなし） |
| `on_failure` | string | `skip` | 耐障害性の挙動を定義: `skip`、`retry`、`abort` |
| `max_retries` | int | `0` | `on_failure: retry` のときのリトライ回数 |

### トップレベルのフィールド

| フィールド | タイプ | デフォルト | 説明 |
|-------|------|----------------|-------------|
| `name` | string | パイプラインディレクトリの名前 | パイプラインの名前であり、そのワークディレクトリの名前でもあります |
| `description` | string | `""` | 自由記述 |
| `model` | string | `""` | すべての LLM ステージが使うモデル。LLM ステージのないパイプラインには不要です。設定されていない場合、`deepzero validate` が警告します |
| `settings` | dict | `{}` | `work_dir`（デフォルト `work`）と `max_workers`（デフォルト `min(4, cpu_count)`） |
| `knowledge` | dict | `{}` | パイプラインレベルの任意の値。`ctx.get_knowledge(key)` で任意のプロセッサから読めます |
| `report` | dict | `{}` | `deepzero report` がこのパイプラインの結果をどう提示するか。後述 |
| `stages` | list | 必須 | 最低 1 つ。その最初のステージはインジェストプロセッサでなければなりません |

`work_dir` は実行ディレクトリそのものではなく、そのルートです。実行は `<work_dir>/<pipeline name>/<corpus key>/` に置かれ、コーパスキーはターゲットパスから導出されます。そのため、1 つのパイプラインを通した 2 つのコーパスが衝突することはなく、それぞれが独立して再開します。[CLI リファレンス]({{ '/ja/reference/cli.html' | relative_url }})を参照してください。

### モデルの選択

`model` の最初の `/` より前の部分はスキームであり、これがバックエンドを選択します。

| モデル文字列 | バックエンド |
|--------------|---------|
| `claude-code`、`claude-code/<model-id>` | ローカルにインストール済みで、すでにサインインしている Claude Code CLI |
| それ以外すべて。例: `openai/gpt-4o`、`gemini/...`、`gpt-4o` | LiteLLM。同ライブラリがサポートするあらゆる API キー方式のエンドポイントを網羅します |

`claude-code` は、API キーなしで Claude Code のサブスクリプションを使ってパイプラインを実行します。DeepZero はその資格情報を一切扱いません。すでにサインインした CLI を呼び出し、そのバイナリが持つ認証をそのまま受け継ぎます。スラッシュより後ろの部分はモデルとしてそのまま渡されるため、`claude-code/claude-opus-5` は特定のモデルを選び、`claude-code` だけなら CLI のデフォルトのままになります。同梱の 2 つのパイプラインはどちらも `claude-code` モデルを宣言しており、`-m` で 1 回の実行だけ上書きできます。

これらの呼び出しは信頼できない内容、すなわちデコンパイラの出力や見知らぬ人のリポジトリから取得したソースコードを運ぶため、CLI はツールと MCP サーバーを無効にした状態で呼び出されます。補完にはそれらは必要なく、有効なままにしておくと、注入されたプロンプトがシェルに到達しうるからです。

このレジストリは開かれています。`register_backend()` は DeepZero にパッチを当てずにスキームを追加でき、1 つ追加するのにプロバイダー、パイプライン、ステージのいずれも変更する必要はありません。どのバックエンドも名乗り出ないスキームは LiteLLM に委ねられます。

どのバックエンドが選ばれたとしても、ステージがそれを必要とする前に、そもそも動かせるのかを確認します。`deepzero validate` は LiteLLM のモデルなら API キーを、エージェント CLI ならバイナリの存在を確認し、[`deepzero run --preflight`]({{ '/ja/reference/cli.html' | relative_url }}) はさらに踏み込んで、CLI がサインイン済みであることを確かめます。

### 解決ロジック (`engine/registry.py`)

`processor:` の値の形が、それをどう解決するかを決めます。そのため、外部ファイルと組み込みの名前とで参照が曖昧になることはありません。

| 参照 | 解決のされ方 |
|-----------|-------------|
| `/` または `\` を含む。例: `ghidra_decompile/ghidra_decompile.py` | 作業ディレクトリ下の `processors/` にあるファイル。その中の最初の Processor サブクラスが使われ、基底クラス自体は無視されます |
| 上記に `:ClassName` を付けたもの | そのファイル内の特定のクラス。1 つのファイルに複数のプロセッサを定義する場合に必要です |
| 名前だけ。例: `metadata_filter` | 内部レジストリ。`stages/__init__.py` で登録されます |
| `:` を含む名前。例: `my.python.module:MyClass` | `sys.path` 上のインポート可能なモジュールと、その中のクラス |

それ以外は、実行の途中で失敗するのではなく、組み込みの名前を列挙したエラーになります。外部のパスはパイプラインディレクトリではなく作業ディレクトリを基準に解決される点に注意してください。同梱パイプラインをリポジトリのルートから実行するのはそのためです。

### 動的展開

スキーマ検証がプロセッサを束縛する前に、DeepZero は YAML の DOM ツリー全体を走査し、`\$\{([^}]+)\}` に対する正規表現のマッチを評価します。実行時の設定は環境変数によって決まります。これにより、コミットされる `.yaml` パイプラインの中に API キーやインストールディレクトリをハードコードすることを明確に防いでいます。

### プロンプトの値

`config` に `prompt` を持つステージは、そのファイルを Jinja テンプレートとしてレンダリングします。値にはパスも、パイプラインの隣にあるファイル名も指定できます。いずれの場合もファイルが読み込まれるのであって、その文字列自体がプロンプト本文として使われることはありません。

すべてのプロンプトが以下を使えます。

| 値 | タイプ | 説明 |
|-------|------|-------------|
| `sample_name` | string | インジェストステージが記録したそのサンプルのファイル名 |
| `sample_path` | string | ディスク上のサンプルへの絶対パス |
| `history` | dict | すでに実行されたすべてのステージについての `{stage_name: data}` |
| `config` | dict | このステージ自身の `config` ブロック |

これらに加えて、プロンプトは**それより前の**ステージが記録したものを何でも使えます。各プロセッサはそうした名前を `provides` 属性に宣言しており、名前には 2 種類あります。

- **データキー**: `device_name` や `finding_count` のように、プロセッサが `data` に入れたもの。その名前で直接使え、`history` からも使えます。
- **アーティファクト**: プロセッサが書き出したファイル。パスの区切り文字と拡張子を名前に畳み込んだ形で参照します。`decompiled/dispatch_ioctl.c` は `decompiled_dispatch_ioctl_c` になります。JSON はオブジェクトに解析され、`.c`、`.h`、`.txt`、`.md`、`.py`、`.yaml`、`.yml` はテキストとして届きます。それ以外のファイル形式は公開されません。コンテキストの予算を超えるものは切り詰められ、大きすぎる JSON は解析されずに警告とともにスキップされます。

ある値が使えるのは、それを記録したステージより*後ろの*ステージだけです。したがってプロンプトが自分自身のステージの出力に手を伸ばすことはできません。

あるパイプラインが何を提供するのかを確認するには、次を実行します。

```bash
deepzero validate <pipeline>
```

前のどのステージも生み出さない名前を指しているプロンプトは、代わりに何が使えたのかを列挙したエラーとして報告され、同じ検査は実行がそこに到達した場合にもその実行を失敗させます。これが重要なのは、そうしなければ未知の名前は何も描画されないまま通り過ぎてしまうからです。モデルは空の内容について判断を求められ、その判定は自信に満ちた無意味なものとして返ってきます。

### report ブロック

`deepzero report` は、エンジンが保証するもの、つまりどのパイプラインでも同じであるものの上に構築されています。各ステージは `data`、`artifacts`、ステータスを記録する、という点です。異なるのは語彙です。カーネルドライバーのパイプライン、ソースコード監査、ライセンスの棚卸しは、いずれも同じ形の結果を生み出しながら、それらをまったく違う名前で呼びます。

そこで、形は固定し、言葉は宣言できるようにしてあります。

```yaml
report:
  title: Source repository audit
  entity: repository
  entity_plural: repositories
  target_label: organisation
  classification_key: classification
  positive_when: [vulnerable]
  negative_when: [not exploitable]
  columns:
    - scan.finding_count
    - discover.primary_language
  findings_files: [findings.json]
```

すべてのフィールドは省略可能で、どのデフォルトも、このブロックが存在しなかった頃の挙動をそのまま再現します。何も宣言しないパイプラインでも、使えるレポートは得られます。

| フィールド | タイプ | デフォルト | 説明 |
|-------|------|---------|-------------|
| `title` | string | `<pipeline name> results` | `index.html` の見出し |
| `entity` | string | `sample` | UI 上で 1 件の結果を何と呼ぶか |
| `entity_plural` | string | `entity` + `s` | s を付けるのが誤りになる場合にのみ必要。例: repository |
| `target_label` | string | `corpus` | 実行が何に向けられたのか |
| `classification_key` | string | `classification` | 結論を保持しているステージの `data` キー |
| `positive_when` | list | `vulnerab`、`exploitab`、`confirmed` | 探しているものとして数える値 |
| `negative_when` | list | `safe`、`not vulnerab`、`benign`、`clean` | 何も見つからなかったものとして数える値 |
| `columns` | list | 自動選択 | 各結果に添えて表示する `stage.key` の値 |
| `findings_files` | list | `findings.json` | サンプルのディレクトリ内で検出結果を読み取るファイル名 |
| `lexicon` | dict | 後述 | 結果を表す言葉 |

`vulnerable_when` と `safe_when` は `positive_when` と `negative_when` の旧名として受け付けられ、意味はまったく同じです。両方が指定された場合は `positive_when` が優先されます。

`target_label` が存在する理由は、デフォルトの「corpus」がディスク上のファイルの山を前提にしているからです。稼働中のアプリケーションに対する実行には対象範囲があり、ある組織のリポジトリ群に対する実行にはその組織があります。そのどちらをもコーパスと呼べば、他人が開くレポートの中で、それは間違いとして読まれます。

#### 判定の照合方法

`classification_key` の下に記録された値は小文字化され、まず `positive_when` の部分文字列と、次に `negative_when` の部分文字列と突き合わされます。完全一致ではなく部分文字列なので、`vulnerab` は「vulnerable」と「vulnerability」の両方をカバーします。

先に肯定側を照合するという性質こそが、デフォルトを上書きする価値を生みます。否定側の判定が `[NOT EXPLOITABLE]` であるパイプラインは、デフォルトの肯定側にある `exploitab` を含んでいるため、検出として数えられてしまいます。`positive_when` を `[vulnerable]` に絞り込むのが同梱のソースコード監査パイプラインの取っている方法であり、実行自身の判定とレポートの集計が食い違うときに最初に確認すべき点です。

どちらのリストにも一致しない判定が黙って捨てられることはありません。それは「Unclear verdict」に分類されます。これは安全と判断されたこととは別の主張です。

#### columns

`columns` は、このパイプラインでのステージ名を用いた `stage.key` の値を列挙し、それぞれをすべての結果に添えます。次に何を読むかを決めるものを宣言してください。その検出結果がそもそも実際に動かせるのか、どれだけのコードが本当にスキャンされたのか、どのリビジョンが判断されたのか、といったものです。何も宣言されていない場合、レポートは実行が記録したものの中から、数値または特徴的な名前を持つキーを最大 6 つまで拾い上げます。

このためにレポートに何かを追加する必要はありません。キーは、プロセッサが `data` に記録し、パイプラインがここで名指しした時点で使えるようになります。

#### 検出結果

`findings_files` は、各サンプルのディレクトリ内で検出結果を読み取るファイルを列挙します。内容が検出結果のリストらしく見える JSON アーティファクトも同様に拾われるため、別の名前で書き出すプロセッサでも設定なしで表示されます。

#### 語彙 (lexicon)

レポートには、探しているものを入れる区分、まだ誰も判断を下していない検出結果の区分、そして最後まで解析して何も指摘されなかった結果の区分があります。これらは構造として定まっています。あなたが決められるのはその名前だけです。

| フィールド | デフォルト | 表示される場所 |
|-------|---------|------------------|
| `discipline` | `vulnerability research` | ヘッダーの製品名の隣 |
| `positive` | `Vulnerable` | その区分のラベルと、そのフィルタ |
| `positive_help` | `an assessment stage concluded these are vulnerable` | そのラベルに添えて表示される説明 |
| `positive_phrase` | `assessed as vulnerable` | サマリー行の「12 repositories ...」を完成させる語句 |
| `nothing_positive` | `Nothing was confirmed vulnerable` | 実行が対処すべきものを何も見つけなかったときの見出し |
| `unconfirmed` | `Needs assessment` | 検出結果はあるが、どの評価もそれに判断を下していない |
| `negative` | `Clear` | 最後まで解析され、何も指摘されなかった |

残りの結果はエンジンが名付けるもので、設定できません。パイプラインが何を探していたかではなく、エンジンが何をしたかを表すものだからです。「Errored」「Ran out of time」「Unclear verdict」「Filtered out」がそれにあたります。

このツールを脆弱性研究の外へ連れ出すのが、この仕組みです。依存関係のライセンスを監査するパイプラインは同じ 3 つの結果を持ちながら、そのどれについてもデフォルトの言葉が当てはまりません。そこで、それが何であるかを自ら述べます。

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

これ以外は何も変わりません。レポートはドライバー探索のときとまったく同じように順位付け、絞り込み、分類、書き出しを行います。そのどれ 1 つとして、実行が何についてのものかに依存したことはないからです。

### レビューマーク

パイプラインは自らが結論したことを記録します。その結論を人間が実際に確かめたかどうかは別の主張であり、それを述べられるのは読み手だけです。そのため、レポートは読み手が読みながら付けるマークを備えています。

どの結果のページにも 3 つのマークがあります。

| マーク | 意味 |
|------|-------|
| **confirmed** | 確かめた結果、成り立っている |
| **did not hold up** | 確かめた結果、成り立たなかった。明確な答えの出た完了済みの結果 |
| **outstanding** | 目を通したが、まだ裏付けの取れていないものが残っている |

後ろの 2 つは、何を、何に対して実行し、何が起きたのかを書き留める欄を開きます。他の誰かが同じ試みを繰り返せるようにするためです。何を未解決とみなすかは読み手に委ねられています。クラッシュの再現、前提条件の証明、差分の確認のいずれであっても、レポートの側から見れば同じ形の未完了の作業だからです。

マークはインデックスの各行に表示され、絞り込みの対象になります。まだ誰も目を通していない結果の一覧である **Unreviewed** も含まれます。サマリーはそれぞれを数えるので、実行の結果を、単に何が主張されたかではなく実際に何が分かっているかとして読めます。成り立たなかった結果が、誰も検討していない結果と取り違えられることはありません。

レポートはファイルなので、マークはブラウザの中にあります。**Export marks** はマークを `marks.json` として書き出します。これを `index.html` の隣に保存すると、マークはレポートの一部になります。開いた人すべてに対して描画され、`inventory.csv` にも `review` および `review_note` として含まれます。マークはファイルパスではなくパイプラインとターゲットをキーにしているため、同じコーパスに対して再実行してもそのまま残ります。
