---
layout: default
title: パイプライン YAML
order: 2
---

## パイプライン設定

DeepZero における **パイプライン** は、データ変更のワークフローを定義する宣言型の実行グラフです。スキーマは YAML で厳密に定義されています。

### 設定スキーマ

```yaml
name: my_pipeline
description: 標準的な脆弱性調査パイプライン
version: "1.0"
model: openai/gpt-4o

settings:
  work_dir: work
  max_workers: 8

stages:
  - name: discover
    processor: file_discovery
    config:
      extensions: ["*"]
```

### ステージの引数

| フィールド | タイプ | デフォルト | 説明 |
|-------|------|----------------|-------------|
| `name` | string | `stage_N` | ステージの一意の名前 |
| `processor` | string | 必須 | プロセッサのリファレンス登録 |
| `config` | dict | `{}` | プロセッサに注入される設定 |
| `parallel` | int | `4` | Map プロセッサの最大並行数 |
