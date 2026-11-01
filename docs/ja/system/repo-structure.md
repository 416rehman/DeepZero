---
layout: default
title: リポジトリ構造
order: 2
---

## リポジトリ構造

```text
src/deepzero/
├── __init__.py          # SemVer 定義
├── __main__.py          # モジュールエントリポイント
├── cli.py               # Click アプリケーションインターフェース
├── api/                 # Starlette REST エンドポイント
├── engine/              # コア実行とオーケストレーションロジック
│   ├── pipeline.py      # pipeline.yaml の読み込みと検証、コーパスキーの導出
│   ├── runner.py        # コーパスに対して各ステージを幅優先で駆動する
│   ├── stage.py         # プロセッサの基底クラス、StageSpec、ステージ入力のダイジェスト
│   ├── state.py         # StateStore、RunState、SampleState
│   ├── registry.py      # プロセッサの参照をクラスに解決する
│   ├── report.py        # 実行状態から閲覧可能なレポートを構築する
│   ├── ui.py            # 実行中のパイプラインのライブ端末ダッシュボード
│   ├── context.py       # LLM に渡すために各サンプルの context.md を書き出す
│   └── backends/        # モデルのスキームで解決される差し替え可能な LLM バックエンド
└── stages/              # 標準ライブラリプロセッサ

processors/              # リファレンスおよび提供されたプロセッサ
├── ghidra_decompile/    # Ghidra ヘッドレスデコンパイラ (Map)
├── git_ingest/          # git リポジトリの検出とクローン (Ingest)
├── loldrivers_filter/   # loldrivers.io ハッシュ除外フィルタ (Map)
├── pe_ingest/           # PE ヘッダーパーサーとドライバーメタデータ抽出 (Ingest)
└── semgrep_scanner/     # semgrep 一括スキャナー (BulkMap)

pipelines/               # パイプライン宣言とロジック
├── loldrivers/          # BYOVD カーネルドライバー調査
└── source_audit/        # git リポジトリを対象としたソースコード監査

docs/                    # Jekyll ベースの GitHub Pages ドキュメント
tests/                   # Pytest 検証スイート
```

`engine/` の一覧に挙げているのは、これ以降のページで扱うモジュールです。相互参照からファイルまで辿れるようにするためであり、このパッケージにはこのほかにもいくつかのモジュールがあります。

各パイプラインのディレクトリには、その `pipeline.yaml`、LLM ステージがレンダリングする Jinja プロンプトテンプレート、スキャンステージが読み込む semgrep ルールが収められています。パイプラインを 1 つ追加するのに、そのディレクトリの外側を変更する必要はありません。それがこの構造の狙いです。`pipelines/` と `processors/` はコード内に登録されるのではなく、パスによって読み取られます。
