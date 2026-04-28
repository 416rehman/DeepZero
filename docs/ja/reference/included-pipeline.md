---
layout: default
title: LOLDrivers パイプライン
order: 3
---

## LOLDrivers パイプラインリファレンス

リファレンスの BYOVD (Bring Your Own Vulnerable Driver) パイプラインは `pipelines/loldrivers/` に維持されています。

1. **discover:** PE インジェストと LIEF ヘッダー解析。
2. **kernel_filter:** IOCTL 表面を公開するカーネルモードドライバーに対する制約処理。
3. **loldrivers_filter:** loldrivers.io カタログに登録されている既知のエンティティの暗号化ハッシュによる除外。
4. **decompile:** Ghidra を使用したヘッドレスデコンパイルの実行。
5. **semgrep_scanner:** エクスポートされた C ソースコードに対する一括静的解析。
6. **pick_top_10:** スコアリングアルゴリズムによる上位候補への発見的削減。
7. **assess:** LLM プロンプトの注入と論理的評価。
