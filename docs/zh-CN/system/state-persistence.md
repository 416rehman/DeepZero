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
            <text x="70" y="-5" font-family="JetBrains Mono, monospace" font-size="14" font-weight="bold" text-anchor="middle" fill="var(--text-secondary)">state.tmp</text>
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

持久化层不是直接写入预期的制品 (如 `state.json`)，而是将数据编组为临时的 `.tmp` 缓冲区。缓冲区沿用目标文件的名称，并且是把后缀替换掉而不是往后追加，因此 `state.json` 的暂存文件是 `state.tmp`。序列化完成后，一次 `os.replace` 操作会强制覆盖目标的原子 inode。主机端 EDR / 防病毒启发式扫描经常会锁定新创建的二进制文件从而触发 `PermissionError`，引擎自带的重试补偿机制 (retry-backoff) 可主动拦截并处理这些锁定。

### 架构版本控制

样本状态是既被标记、又被把关的那一部分。`state.json` 写出时带有一个 `_version` 字段，承载内部的 `STATE_VERSION`；加载时任何更旧的版本都会被拒绝：在 v2 运行时读取 v1 版本的 JSON 会什么都读不回来，而不是按一份已经无法描述该记录的架构去解读它，从而引发不可预测的异常更改错误。

另外两个文件不受此把关。`run_manifest.json` 同样带有 `_version` 字段，但没有任何东西会把它读回来，因为这份清单是一份派生出来的摘要，每次样本被保存时都会重写一遍。`run.json` 则既不带标记也不受检查：它的加载方式是拿 `RunState` 自身的字段名去过滤这份 JSON，并丢弃一切无法识别的内容，因此由更旧版本写出的记录会带着它已有的那些字段被加载进来，其余字段保持默认值。

### 工作空间层级

```text
work/<pipeline_name>/<corpus_key>/
├── run.json             # 序列化的 `RunState`: 执行指标、流水线元数据、
│                        #   整个语料库层面的结论，以及本次运行的存活记录
├── pipeline.yaml        # 初始化期间流水线 YAML 配置的不可变快照
├── run_manifest.json    # 所有样本的宏观综合总览，由 `status` 和 `interactive` 读取
├── report/              # 可浏览的 HTML 报告，随结果产生而重建
└── samples/
    └── <sample_id>/     # 隔离的沙盒
        ├── state.json   # 序列化的 `SampleState`: 完整的 `StageOutput` 映射账本
        ├── context.md   # 通过 `engine/context.py` 生成的合成 LLM 上下文
        └── ...          # 处理器生成的特定产物
```

`RunState` 中有两部分值得在各项指标之外单独点名。`conclusion` 存放的是一条关于整个语料库、而非关于其中任何单个样本的发现：某个端点背后是哪个模型，一堆崩溃究竟代表多少个互不相同的缺陷，某个作用域是否配置正确。它由一个能看到全部样本的阶段通过 `ctx.conclude(...)` 写入，而对于答案全都是逐样本给出的众多流水线来说，它始终为空。与之并列的 `host`、`pid`、`pid_token` 和 `heartbeat_at` 记录的是谁在写这次运行：在其背后的进程能被核查之前，`running` 这个状态都只是一种主张，而被杀掉的运行永远没有机会自己撤回这个主张，因此正是这四个字段让另一个进程能把一次活着的运行与一次被遗弃的运行区分开来。

### 语料库作用域

`<corpus_key>` 这一段正是把经由同一条流水线处理的两个目标区分开来的东西。它由运行目标派生而来：目标的基本名，加上解析后绝对路径的一段短摘要，因此它既可读又无歧义。在 Windows 上会先对路径做大小写折叠，因为 `C:\Drivers` 和 `c:\drivers` 是同一个语料库。

没有这一段，把同一条流水线指向第二个语料库时，就会恢复到第一个语料库的样本存储里：那些在磁盘上已不再对应任何东西的样本会被当作已分析完毕，而这次运行会为一个它从未拿到过的语料库报告结果。有了这一段，每个语料库都有自己的状态、自己的清单和自己的报告，并各自独立恢复。

同一个解析后的路径始终映射到同一个键，因此重新运行会回到它中断的地方。这个目录下几乎一切都是派生出来的，删掉 `report/` 通常只需付出一次重建的代价，而不是一次重跑。

但有一个例外，而且它无法恢复。`report/marks.json` 存放的是审阅标记：对每个样本而言，读者是否核查过它、核查后认为结论成立还是不成立，外加一条备注。那是读者核查过的内容，任何阶段都无从知晓，因此它在运行状态里根本不存在。它之所以被存回报告旁边，正是为了让打开报告的任何人都能看到它渲染出来，而不是被困在某一个人的浏览器里，并且每次重建都会重新读取它。删除 `report/` 会毁掉它，`run --clean` 也一样，因为后者会在开始之前把整个语料库目录移除。

### `history` 账本

`SampleState.history` 字典严格地将处理器阶段名称映射到 `StageOutput` 实例。输出的数据结构被严格隔离并通过命名空间管理。如果下游处理器需要提取上游映射阶段的指标，可以查询：`history["upstream_processor"].data.get("metric")` (参阅 [构建自定义处理器]({{ '/zh-CN/extensibility/building-custom.html' | relative_url }}))。

这种基于命名空间的方法可永久防止不同启发式分析技术之间的字段冲突。

### 阶段输入指纹

每个 `StageOutput` 都有一个 `input_digest`：它根据下述控制项，对处理器、配置和被追踪的文件依赖计算指纹。指纹在阶段完成时记录，并在恢复运行时比较，以判断已保存的结果是否过期。

当两个摘要都存在且彼此不同时，存下来的那个结果所描述的输入，流水线已经不再拥有，因此它算作已过期而不是已完成，该阶段会重新运行。正是这一点让被恢复的运行能自己算出哪些结果依然成立，而不必由读者去回忆自己改过什么。当其中任何一个摘要为空时，这个问题就无从发问，而一个无法回答的问题不足以成为丢弃一份可能花了好几个小时才产出的工作成果的理由，因此在摘要被记录之前写下的结果会被信任，而不是重做。

指纹包含处理器源码、其配置递归引用的文件，以及处理器声明会读取的全局配置。更换模型会使 LLM 评估及其下游失效，同时保留内置非 LLM 阶段的工作，如反编译。上游结果失效时，下游状态和记录的产物也会清除。上游结果或成员变化时，下游归约阶段会重新计算整个相关样本组。

自定义处理器默认将所有全局配置计入指纹，可通过 `cache_global_keys` 声明更小的依赖范围（仅使用自身配置时为 `()`）。请在配置中列出所需文件。处理器内部直接读取的外部资源或环境变量不会被自动追踪；它们变化时请使用 `--redo <stage>`。

`cache_path_keys` 指定哪些顶层配置键会作为文件或目录依赖来读取（`None`：全部；`()`：不读取）。请用 `cache_files(pipeline_dir)` 明确列出分析脚本、版本元数据等依赖，避免对整个工具安装目录或输出、缓存目录计算指纹。

### 刷新已发现的语料库

恢复运行时默认使用已保存的发现快照。使用 `--refresh` 可重新发现同一路径中的新增或变更输入。发现元数据未变的样本保留缓存结果；变更样本及其下游结果会重新处理。已移除的样本及其产物会移到 `retired_samples/`，不再出现在当前结果中。内置流水线的 `--redo discover` 也会重新执行发现。检测范围取决于摄取处理器记录的元数据，并不会监控任意文件或网络变化。

对 git 仓库清单，还需在摄取阶段配置中设置 `refresh: true` 才会获取新的远程提交；仅使用 `--refresh` 会重新检查缓存的克隆。

```bash
deepzero run ./drivers -p pipelines/loldrivers/pipeline.yaml --refresh
```

每个流水线和语料库同一时间只允许一个写入进程。系统锁会在清理、重做或刷新之前拒绝并发的 `deepzero run`；进程退出时锁会释放，无需手动删除遗留的锁文件。
