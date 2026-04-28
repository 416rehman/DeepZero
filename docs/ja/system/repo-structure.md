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
└── stages/              # 標準ライブラリプロセッサ

processors/              # リファレンスおよび提供されたプロセッサ
pipelines/               # パイプライン宣言と設定 YAML
tests/                   # Pytest 検証スイート
```
