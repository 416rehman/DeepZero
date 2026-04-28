---
layout: default
title: クイックスタート
order: 1
---

## クイックスタート

DeepZero は、分析するためのターゲットとなるファイルコーパスと、その処理方法を詳述する[パイプライン設定]({{ '/ja/reference/pipeline-yaml.html' | relative_url }})を必要とします。[LOLDrivers](https://www.loldrivers.io/) プロジェクトからの既知のハッシュをフィルタリングすることにより、未加工のバイナリデータセットの中から新しい脆弱なドライバー（BYOVD）候補を見つけるように設計された[完全なサンプルパイプライン]({{ '/ja/reference/included-pipeline.html' | relative_url }})を提供しています。

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

### 3. パイプラインの実行

ターゲットパスに対して組み込みの LOLDrivers パイプラインを実行します。

```bash
deepzero run C:\drivers -p .\pipelines\loldrivers\pipeline.yaml
```

<div class="callout">
    <p><strong>注意:</strong> DeepZero は安全に<a href="{{ '/ja/overview/architecture.html' | relative_url }}">実行を並列化</a>し、中間出力をキャッシュします。正常に停止するには、SIGINT（<code>Ctrl+C</code>）を送信してください。同じパラメータでの後続の実行は、<a href="{{ '/ja/system/state-persistence.html' | relative_url }}">ディスクに保存された状態</a>から即座に再開されます。</p>
</div>
