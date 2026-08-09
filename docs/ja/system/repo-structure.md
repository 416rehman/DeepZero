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
│   ├── backends/        # モデルのスキームで解決される差し替え可能な LLM バックエンド
│   └── report.py        # 実行状態から閲覧可能なレポートを構築する
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

各パイプラインのディレクトリには、その `pipeline.yaml`、LLM ステージがレンダリングする Jinja プロンプトテンプレート、スキャンステージが読み込む semgrep ルールが収められています。パイプラインを 1 つ追加するのに、そのディレクトリの外側を変更する必要はありません。それがこの構造の狙いです。`pipelines/` と `processors/` はコード内に登録されるのではなく、パスによって読み取られます。
