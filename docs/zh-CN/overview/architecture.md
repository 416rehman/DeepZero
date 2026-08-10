---
layout: default
title: 核心架构
order: 2
---

## 引擎架构

DeepZero 的编排引擎在由 [流水线]({{ '/zh-CN/reference/pipeline-yaml.html' | relative_url }}) 严格定义的单向处理图上运行。执行引擎保证容错且可恢复的 [状态管理]({{ '/zh-CN/system/state-persistence.html' | relative_url }})，同时将并行操作扇出并分配至容量有限的线程池 ([`ThreadPoolExecutor`](https://docs.python.org/3/library/concurrent.futures.html#threadpoolexecutor)) 中。

<div class="architecture-diagram" style="margin: 3rem 0;">
    <svg viewBox="0 0 800 400" style="width: 100%; height: auto; max-width: 800px;" xmlns="http://www.w3.org/2000/svg">
        <defs>
            <linearGradient id="flowGrad" x1="0%" y1="0%" x2="100%" y2="0%">
                <stop offset="0%" stop-color="var(--border)" />
                <stop offset="50%" stop-color="var(--text-tertiary)" />
                <stop offset="100%" stop-color="var(--border)" />
            </linearGradient>
            <pattern id="isoGridSmall" width="40" height="23.094" patternUnits="userSpaceOnUse" patternTransform="scale(1)">
                <path d="M 40 0 L 0 23.094 M 0 0 L 40 23.094 M 20 23.094 L 20 0" fill="none" stroke="var(--border)" stroke-width="0.5"/>
            </pattern>
        </defs>
        
        <rect width="100%" height="100%" fill="url(#isoGridSmall)" opacity="0.3"/>

        <!-- Ingest Node -->
        <g transform="translate(150, 200)">
            <path d="M 0 0 L 60 -30 L 120 0 L 60 30 Z" fill="var(--bg-primary)" stroke="var(--text-primary)" stroke-width="1.5" stroke-linejoin="round"/>
            <path d="M 0 0 L 0 40 L 60 70 L 120 40 L 120 0 L 60 30 Z" fill="var(--bg-secondary)" stroke="var(--text-primary)" stroke-width="1.5" stroke-linejoin="round"/>
            <path d="M 60 30 L 60 70" stroke="var(--text-primary)" stroke-width="1.5"/>
            <text x="60" y="-5" font-family="JetBrains Mono, monospace" font-size="12" font-weight="bold" text-anchor="middle" fill="var(--text-secondary)" transform="skewX(30) rotate(-30)">摄取 (INGEST)</text>
            <text x="60" y="30" font-family="Inter, sans-serif" font-size="10" text-anchor="middle" fill="var(--text-tertiary)" transform="skewX(30) rotate(-30)">1 → N</text>
        </g>

        <!-- Connecting Lines to Map -->
        <path d="M 210 170 L 250 150 L 300 150 L 350 125" fill="none" stroke="url(#flowGrad)" stroke-width="2" stroke-dasharray="6 6">
            <animate attributeName="stroke-dashoffset" from="100" to="0" dur="2s" repeatCount="indefinite" />
        </path>
        <path d="M 210 170 L 350 170" fill="none" stroke="url(#flowGrad)" stroke-width="2" stroke-dasharray="6 6">
            <animate attributeName="stroke-dashoffset" from="100" to="0" dur="2s" repeatCount="indefinite" />
        </path>
        <path d="M 210 170 L 250 190 L 300 190 L 350 215" fill="none" stroke="url(#flowGrad)" stroke-width="2" stroke-dasharray="6 6">
            <animate attributeName="stroke-dashoffset" from="100" to="0" dur="2s" repeatCount="indefinite" />
        </path>

        <!-- Map Nodes -->
        <g transform="translate(350, 90)">
            <path d="M 0 0 L 40 -20 L 80 0 L 40 20 Z" fill="var(--bg-primary)" stroke="var(--text-primary)" stroke-width="1.5" stroke-linejoin="round"/>
            <path d="M 0 0 L 0 20 L 40 40 L 80 20 L 80 0 L 40 20 Z" fill="var(--bg-secondary)" stroke="var(--text-primary)" stroke-width="1.5" stroke-linejoin="round"/>
            <path d="M 40 20 L 40 40" stroke="var(--text-primary)" stroke-width="1.5"/>
            <circle cx="40" cy="0" r="3" fill="var(--text-primary)"/>
            <text x="40" y="-10" font-family="JetBrains Mono, monospace" font-size="10" text-anchor="middle" fill="var(--text-secondary)" transform="skewX(30) rotate(-30)">映射 (MAP)</text>
        </g>
        <g transform="translate(350, 160)">
            <path d="M 0 0 L 40 -20 L 80 0 L 40 20 Z" fill="var(--bg-primary)" stroke="var(--text-primary)" stroke-width="1.5" stroke-linejoin="round"/>
            <path d="M 0 0 L 0 20 L 40 40 L 80 20 L 80 0 L 40 20 Z" fill="var(--bg-secondary)" stroke="var(--text-primary)" stroke-width="1.5" stroke-linejoin="round"/>
            <path d="M 40 20 L 40 40" stroke="var(--text-primary)" stroke-width="1.5"/>
            <circle cx="40" cy="0" r="3" fill="var(--text-primary)"/>
            <text x="40" y="-10" font-family="JetBrains Mono, monospace" font-size="10" text-anchor="middle" fill="var(--text-secondary)" transform="skewX(30) rotate(-30)">映射 (MAP)</text>
        </g>
        <g transform="translate(350, 230)">
            <path d="M 0 0 L 40 -20 L 80 0 L 40 20 Z" fill="var(--bg-primary)" stroke="var(--text-primary)" stroke-width="1.5" stroke-linejoin="round"/>
            <path d="M 0 0 L 0 20 L 40 40 L 80 20 L 80 0 L 40 20 Z" fill="var(--bg-secondary)" stroke="var(--text-primary)" stroke-width="1.5" stroke-linejoin="round"/>
            <path d="M 40 20 L 40 40" stroke="var(--text-primary)" stroke-width="1.5"/>
            <circle cx="40" cy="0" r="3" fill="var(--text-primary)"/>
            <text x="40" y="-10" font-family="JetBrains Mono, monospace" font-size="10" text-anchor="middle" fill="var(--text-secondary)" transform="skewX(30) rotate(-30)">映射 (MAP)</text>
        </g>

        <!-- Connecting Lines to Reduce -->
        <path d="M 430 90 L 480 115 L 520 115 L 560 170" fill="none" stroke="url(#flowGrad)" stroke-width="2" stroke-dasharray="6 6">
            <animate attributeName="stroke-dashoffset" from="100" to="0" dur="2s" repeatCount="indefinite" />
        </path>
        <path d="M 430 160 L 560 170" fill="none" stroke="url(#flowGrad)" stroke-width="2" stroke-dasharray="6 6">
            <animate attributeName="stroke-dashoffset" from="100" to="0" dur="2s" repeatCount="indefinite" />
        </path>
        <path d="M 430 230 L 480 205 L 520 205 L 560 170" fill="none" stroke="url(#flowGrad)" stroke-width="2" stroke-dasharray="6 6">
            <animate attributeName="stroke-dashoffset" from="100" to="0" dur="2s" repeatCount="indefinite" />
        </path>

        <!-- Reduce Node -->
        <g transform="translate(560, 180)">
            <path d="M 0 0 L 60 -30 L 120 0 L 60 30 Z" fill="var(--accent)" stroke="var(--bg-primary)" stroke-width="1.5" stroke-linejoin="round"/>
            <path d="M 0 0 L 0 40 L 60 70 L 120 40 L 120 0 L 60 30 Z" fill="var(--text-secondary)" stroke="var(--bg-primary)" stroke-width="1.5" stroke-linejoin="round"/>
            <path d="M 60 30 L 60 70" stroke="var(--bg-primary)" stroke-width="1.5"/>
            <text x="60" y="-5" font-family="JetBrains Mono, monospace" font-size="12" font-weight="bold" text-anchor="middle" fill="var(--bg-primary)" transform="skewX(30) rotate(-30)">归约 (REDUCE)</text>
            <text x="60" y="30" font-family="Inter, sans-serif" font-size="10" text-anchor="middle" fill="var(--text-tertiary)" transform="skewX(30) rotate(-30)">N → M</text>
            
            <!-- Output stream -->
            <path d="M 60 10 L 90 -5" fill="none" stroke="var(--bg-primary)" stroke-width="2" stroke-dasharray="2 2"/>
            <path d="M 70 20 L 100 5" fill="none" stroke="var(--bg-primary)" stroke-width="2" stroke-dasharray="2 2"/>
        </g>
    </svg>
</div>

### 组件生命周期

当一个样本在抽象流程中进展时，数据模型会经历以下转换：

1. **`Sample`**: 由 `IngestProcessor` 生成的基础结构体。它将物理路径 `source_path` 绑定到唯一的 `sample_id` (通常是 SHA-256 哈希值或确定性的 UUID) 并初始化样本的 `data` 字典。
2. **`SampleState`**: 由 `StateStore` 维护的持久化记录。它跟踪样本的裁决状态 `verdict` (`PENDING`, `ACTIVE`, `FILTERED`, `FAILED`, `TIMED_OUT`, `COMPLETED`)，并维护一个映射了每个处理器 `StageOutput` 实例的 `history` (历史记录)。`TIMED_OUT` 与 `FAILED` 分开，是因为它并没有对样本本身说任何事情，而且它是唯一一种加长预算就能改变的结果。
3. **`ProcessorEntry`**: 动态生成的、具有内存效率的封装，用于传入 Map/BulkMap/Reduce 处理器。它注入了一种惰性加载机制 (`_store`)，仅当访问 `.history` 或 `.upstream_data()` 时，才会从磁盘中调取历史执行数据。

### 处理范式

处理器规定了执行拓扑和并发模型。所有处理器都继承自 `Processor` 基类，暴露了以下生命周期钩子：`validate()`, `setup()`, `process()`, 和 `teardown()`。要了解如何编写自定义处理器，请参阅 [构建自定义处理器]({{ '/zh-CN/extensibility/building-custom.html' | relative_url }})。

#### `IngestProcessor` (1 → N)
- **类型签名:** `process(ctx: ProcessorContext, target: Path) -> list[Sample]`
- **并发:** 同步。在每次流水线运行中精确执行一次。
- **职责:** 生成初始语料库。在摄取 (Ingest) 之前不存在上游数据。

#### `MapProcessor` (1 → 1)
- **类型签名:** `process(ctx: ProcessorContext, entry: ProcessorEntry) -> ProcessorResult`
- **并发:** 线程级扇出分配。通过流水线 YAML 中的 `parallel:` 字段进行配置。`parallel: 0` 表示自动缩放，并受 `max_workers` 以及处理器 `max_parallelism()` 返回值的双重约束。
- **约束:** 必须是严格的线程安全。避免共享可变状态。
- **预算:** `timeout:` 约束的是阶段在一个样本上等多久，而不是这份工作跑多久。工作线程只会被撇下，绝不会被杀掉，因此会启动外部进程的处理器应当自己去约束那个进程。

#### `BulkMapProcessor` (N → N)
- **类型签名:** `process(ctx: ProcessorContext, entries: list[ProcessorEntry]) -> list[ProcessorResult]`
- **并发:** 对活动样本的子集或全部样本进行同步执行。
- **职责:** 优化外部进程的调用 (例如，启动一个庞大的 JVM 工具或进行 Semgrep 批量扫描)，从而在多个样本中均摊庞大的启动开销。输出结果必须有严格索引，才能与输入的 `entries` 列表匹配。

#### `ReduceProcessor` (N → M)
- **类型签名:** `process(ctx: ProcessorContext, entries: list[ProcessorEntry]) -> list[str]`
- **并发:** 全局同步屏障。在此阶段暂停线程执行，直到所有活动样本都到达。
- **职责:** 返回一个包含存活样本的 `sample_id` 字符串有序列表。任何未包含在返回列表中的样本 ID 都将永久打上 `SampleStatus.FILTERED` 状态标签。

### 输出契约

无论处理器在做什么，它记录下来的都是同样的三样东西：`data`，一个任意的、带命名空间的字典；`artifacts`，一个从标签到相对文件路径的映射；以及一个状态。这份契约刻意不带任何领域色彩，而引擎下游的一切都建立在它之上。

[报告]({{ '/zh-CN/reference/cli.html' | relative_url }}) 是最清楚的例证。它是持久化状态的一次投影，而不是流水线中的一个阶段：它读取的就是任何处理器都能读取的那些 `data` 和 `artifacts`，正因如此，驱动程序狩猎、源代码审计以及其他任何事情都能被渲染出来，而报告代码并不知道它们分别是什么。流水线只提供词汇，而那是 [一块 YAML]({{ '/zh-CN/reference/pipeline-yaml.html' | relative_url }}) 而不是代码。

由于报告不包含任何运行目录里没有的内容，它可以在运行进行中生成，可以在被删除后重建，也可以为几周前就已结束的运行再次重建。同样的性质也让 LLM 层可以随意替换：后端是从流水线的模型字符串中选出的，而没有任何处理器、阶段或状态文件知道是哪一个后端作了回答。
