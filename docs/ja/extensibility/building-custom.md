---
layout: default
title: プロセッサの構築
order: 2
---

## カスタムプロセッサの構築

ユーザーのロジックは、`deepzero.engine.stage` の型付き抽象化を拡張することで DeepZero に統合されます。

### プロセッサコンテキスト (`ProcessorContext`)

各ライフサイクルフックに注入される `ctx` オブジェクトは、システム全体のコンテキストを提供します：
- `ctx.pipeline_dir`: 実行中のパイプラインのルートディレクトリ。
- `ctx.global_config`: `settings`、`knowledge`、および `model` を含む TypedDict。
- `ctx.llm`: LiteLLM を抽象化する API プロバイダーインスタンス。
- `ctx.log`: 設定済みのロガー。

### 設定定義

受け入れる YAML 設定を定義するには、`Config` という名前の `@dataclass` を使用します。エンジンは [パイプライン YAML]({{ '/ja/reference/pipeline-yaml.html' | relative_url }}) を解析し、`Config` オブジェクトのインスタンスを作成します。
