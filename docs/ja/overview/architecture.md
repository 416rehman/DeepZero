---
layout: default
title: 基本アーキテクチャ
order: 2
---

## エンジンアーキテクチャ

DeepZero オーケストレーションエンジンは、[パイプライン]({{ '/ja/reference/pipeline-yaml.html' | relative_url }}) によって定義された厳密な有向非巡回グラフ（DAG）処理で動作します。実行エンジンは、フォールトトレラントで再開可能な[状態管理]({{ '/ja/system/state-persistence.html' | relative_url }})を保証します。

### コンポーネントのライフサイクル

データモデルは以下の抽象化を経て流れます：

1. **`Sample`**: `IngestProcessor` によって出力される基本構造。物理パスを一意の `sample_id` にマッピングします。
2. **`SampleState`**: `StateStore` によって維持される永続的なレコード。判定（`PENDING`、`ACTIVE`、`FILTERED`、`FAILED`、`COMPLETED`）を追跡します。
3. **`ProcessorEntry`**: メモリの遅延初期化を利用して Map/Reduce プロセッサに渡されるファサード。
