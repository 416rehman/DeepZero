---
layout: default
title: CLI リファレンス
order: 1
---

## コマンドラインインターフェース

`deepzero` CLI は、パイプラインを実行および管理するための主要な相互作用ポイントです。

```bash
# 標準実行
deepzero run ./targets -p pipelines/loldrivers/pipeline.yaml

# 状態をクリアして実行 (クリーンラン)
deepzero run ./targets -p pipelines/loldrivers/pipeline.yaml --clean

# 実行ステータスの確認
deepzero status -p loldrivers

# 対話型 REPL の起動
deepzero interactive -w work/loldrivers

# Starlette REST API を起動
deepzero serve -w work/loldrivers --port 8420

# カスタムパイプラインの作成
deepzero init my_custom_pipeline

# 実行せずにスキーマを検証
deepzero validate loldrivers

# システムレジストリのリスト
deepzero list-processors
```

### 主要なコマンド

| コマンド | 説明 |
| ------- | ----------- |
| `run` | ターゲットに対してパイプラインを実行します。状態が存在する場合は自動的に再開します。 |
| `status` | パイプライン実行の現在のステータスとステージメトリクスを表示します。 |
| `interactive` | LLM を活用した対話型分析 REPL。 |
| `serve` | コンテキスト推論状態の REST API サーバーを起動します。 |
| `init` | 新しいパイプラインディレクトリを作成します。 |
| `validate` | パイプラインのスキーマを検証します。 |
| `list-processors` | 登録されているすべてのプロセッサタイプを一覧表示します。 |
