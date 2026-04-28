---
layout: default
title: LOLDrivers 流水线
order: 3
---

## LOLDrivers 流水线参考

我们在 `pipelines/loldrivers/` 中维护了一个 BYOVD（自带易受攻击驱动程序，Bring Your Own Vulnerable Driver）参考流水线。

1. **discover:** PE 文件摄取和 LIEF 头解析。
2. **kernel_filter:** 对暴露了 IOCTL 攻击面的内核态驱动程序进行约束处理。
3. **loldrivers_filter:** 排除 loldrivers.io 目录中已知的实体。
4. **decompile:** 执行 Ghidra 无头反编译。
5. **semgrep_scanner:** 针对导出的 C 源码进行大规模静态分析。
6. **pick_top_10:** 将候选项启发式缩减到最高信号层。
7. **assess:** LLM 提示词注入和逻辑评估。
