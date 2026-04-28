---
layout: default
title: 状态持久化
order: 1
---

## 持久化子系统

数据完整性由 `StateStore` (定义于 `engine/state.py`) 处理。通过严格的原子交换方法 (atomic swapping methodologies)，即使面临 SIGKILL 或操作系统级别的中断，对文件系统执行的操作也具备极强的防破坏能力。

<div class="architecture-diagram" style="margin: 3rem 0;">
    <svg viewBox="0 0 800 250" style="width: 100%; height: auto; max-width: 800px;" xmlns="http://www.w3.org/2000/svg">
        <defs>
            <pattern id="isoGridState" width="40" height="23.094" patternUnits="userSpaceOnUse" patternTransform="scale(1)">
                <path d="M 40 0 L 0 23.094 M 0 0 L 40 23.094 M 20 23.094 L 20 0" fill="none" stroke="var(--border)" stroke-width="0.5"/>
            </pattern>
        </defs>

        <rect width="100%" height="100%" fill="url(#isoGridState)" opacity="0.3"/>
        
        <!-- Memory Node -->
        <g transform="translate(100, 120)">
            <rect x="0" y="-40" width="120" height="80" fill="var(--bg-primary)" stroke="var(--text-primary)" stroke-width="2" rx="8"/>
            <text x="60" y="-5" font-family="JetBrains Mono, monospace" font-size="14" font-weight="bold" text-anchor="middle" fill="var(--text-primary)">内存 (Memory)</text>
            <text x="60" y="15" font-family="Inter, sans-serif" font-size="12" text-anchor="middle" fill="var(--text-tertiary)">SampleState</text>
        </g>

        <!-- Path to Temp -->
        <path d="M 220 120 L 320 120" fill="none" stroke="var(--text-tertiary)" stroke-width="2" stroke-dasharray="6 6"/>
        <text x="270" y="110" font-family="Inter, sans-serif" font-size="12" text-anchor="middle" fill="var(--text-secondary)">序列化</text>
        
        <!-- Temp Node -->
        <g transform="translate(320, 120)">
            <rect x="0" y="-40" width="140" height="80" fill="var(--bg-secondary)" stroke="var(--border)" stroke-width="2" stroke-dasharray="4 4" rx="8"/>
            <text x="70" y="-5" font-family="JetBrains Mono, monospace" font-size="14" font-weight="bold" text-anchor="middle" fill="var(--text-secondary)">state.json.tmp</text>
            <text x="70" y="15" font-family="Inter, sans-serif" font-size="12" text-anchor="middle" fill="var(--text-tertiary)">缓冲</text>
        </g>
        
        <!-- Path to Final -->
        <path d="M 460 120 L 580 120" fill="none" stroke="var(--accent)" stroke-width="3"/>
        <circle cx="0" cy="0" r="5" fill="var(--accent)">
            <animateMotion path="M 460 120 L 580 120" dur="1.5s" repeatCount="indefinite" />
        </circle>
        <text x="520" y="110" font-family="Inter, sans-serif" font-size="12" font-weight="bold" text-anchor="middle" fill="var(--accent)">os.replace</text>
        <text x="520" y="140" font-family="Inter, sans-serif" font-size="10" text-anchor="middle" fill="var(--text-tertiary)">原子交换</text>
        
        <!-- Final Node -->
        <g transform="translate(580, 120)">
            <rect x="-10" y="-30" width="120" height="80" fill="var(--bg-primary)" stroke="var(--border)" stroke-width="1" rx="4"/>
            <rect x="-5" y="-35" width="120" height="80" fill="var(--bg-primary)" stroke="var(--border)" stroke-width="1" rx="4"/>
            <rect x="0" y="-40" width="120" height="80" fill="var(--bg-primary)" stroke="var(--text-primary)" stroke-width="2" rx="4"/>
            <text x="60" y="-5" font-family="JetBrains Mono, monospace" font-size="14" font-weight="bold" text-anchor="middle" fill="var(--text-primary)">state.json</text>
            <text x="60" y="15" font-family="Inter, sans-serif" font-size="12" text-anchor="middle" fill="var(--text-tertiary)">持久层</text>
        </g>
    </svg>
</div>

### 原子交换 (`atomic_replace`)

持久化层不是直接写入预期的制品 (如 `state.json`)，而是将数据编组为临时的 `.tmp` 缓冲区。序列化完成后，一次 `os.replace` 操作会强制覆盖目标的原子 inode。主机端 EDR / 防病毒启发式扫描经常会锁定新创建的二进制文件从而触发 `PermissionError`，引擎自带的重试补偿机制 (retry-backoff) 可主动拦截并处理这些锁定。

### 架构版本控制

所有的状态对象都标记了内部的 `STATE_VERSION`。如果引擎在反序列化期间遇到架构漂移 (例如，在 v2 运行时读取 v1 版本的 JSON)，它会显式弃用该状态对象，而不是引发不可预测的异常更改错误。

### 工作空间层级

```text
work/<pipeline_name>/
├── run.json             # 序列化的 `RunState`: 执行指标和流水线元数据
├── pipeline.yaml        # 初始化期间流水线 YAML 配置的不可变快照
├── run_manifest.json    # 所有样本的宏观综合总览 (由 Starlette API 使用)
└── samples/
    └── <sample_id>/     # 隔离的沙盒
        ├── state.json   # 序列化的 `SampleState`: 完整的 `StageOutput` 映射账本
        ├── context.md   # 通过 `engine/context.py` 生成的合成 LLM 上下文
        └── ...          # 处理器生成的特定产物
```

### `history` 账本

`SampleState.history` 字典严格地将处理器阶段名称映射到 `StageOutput` 实例。输出的数据结构被严格隔离并通过命名空间管理。如果下游处理器需要提取上游映射阶段的指标，可以查询：`history["upstream_processor"].data.get("metric")` (参阅 [构建自定义处理器]({{ '/zh-CN/extensibility/building-custom.html' | relative_url }}))。

这种基于命名空间的方法可永久防止不同启发式分析技术之间的字段冲突。
