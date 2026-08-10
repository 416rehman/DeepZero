---
layout: default
title: 构建处理器
order: 2
---

## 构建自定义处理器

通过对 `deepzero.engine.stage` 提供的具有类型的抽象类进行子类化，可以将自定义逻辑注入到 DeepZero 中。有关这些阶段如何映射到执行阶段的说明，请参阅 [核心架构]({{ '/zh-CN/overview/architecture.html' | relative_url }})。

### 处理器上下文 (`ProcessorContext`)

注入到每个生命周期钩子中的 `ctx` 对象，提供了系统级的上下文和实用工具：
- `ctx.pipeline_dir`: 所调用流水线的根目录，对于解析本地模板或规则集十分有用。
- `ctx.global_config`: `TypedDict` 字典，包含流水线级别的 `settings` (设置), `knowledge` (知识), 和已配置的 `model`。`ctx.get_setting(key)` 和 `ctx.get_knowledge(key)` 是读取它的简便写法。
- `ctx.llm`: 一个通用代理实例 (实现了 `LLMProtocol`)，自带原生补偿/重试 (backoff/retry) 机制；当流水线没有配置模型时为 `None`。它驱动哪个后端，由流水线的 `model` 字符串解析决定，因此处理器调用 `ctx.llm.complete()` 时，面对 API 密钥和面对本地 agent CLI 的写法完全一样。参阅 [选择模型]({{ '/zh-CN/reference/pipeline-yaml.html' | relative_url }})。
- `ctx.log`: 已预先配置、带命名空间的 `logging.Logger`。
- `ctx.progress`: 进度上报钩子，`update(amount=, total=, description=)`，这样长时间运行的摄取阶段或批量阶段会在仪表盘上显示出进展，而不是看起来像卡住了。
- `ctx.shutdown_event`: 一个 `threading.Event`，在运行被中断时被置位。执行长时间工作的处理器应当检查它并提前返回，而不是在写入过程中被杀掉。

### 执行钩子

处理器实现由引擎调用的特定生命周期钩子：

1. **`validate(ctx: ProcessorContext) -> list[str]`**: 在初始架构验证期间调用（通过 `deepzero validate` 或在执行前）。如果依赖项（例如，缺少二进制文件、无法解析的 YAML）失败，则返回包含错误字符串的列表。
2. **`setup(global_config: dict) -> None`**: 在线程池激活前精确执行一次。
3. **`process(...)`**: 核心操作。其函数签名随处理器类型 (ProcessorType) 而变化。
4. **`teardown() -> None`**: 在流水线完成或发生致命中断时执行。

对于单个样本开销很大的 Map 处理器，还有一个钩子值得覆写：

5. **`max_parallelism() -> int | None`**: 自动并发的上限。它只在阶段声明了 `parallel: 0` 时生效；显式写出的 `parallel: N` 始终按原样采纳。当每个样本都要付出一个 JVM、一个容器或几个 GB 内存的代价时，请返回一个整数，好让保持默认设置的流水线不至于把机器榨干。默认值 `None` 表示没有上限。

### 定义处理器配置

利用名为 `Config` 的内嵌 `@dataclass` 来严格定义并验证被接受的 YAML 配置。引擎会解析 [流水线 YAML]({{ '/zh-CN/reference/pipeline-yaml.html' | relative_url }}) 字典并实例化你的 `Config` 对象，通过标准 Python [`dataclasses`](https://docs.python.org/3/library/dataclasses.html) 自动对 `${ENV_VARS}` 环境变量进行展开。

```python
from dataclasses import dataclass
from deepzero.engine.stage import MapProcessor, ProcessorContext, ProcessorEntry, ProcessorResult

class BinaryAnalyzer(MapProcessor):
    description = "Static heuristics extraction"

    @dataclass
    class Config:
        target_arch: str = "x86_64"
        max_entropy: float = 7.5

    def process(self, ctx: ProcessorContext, entry: ProcessorEntry) -> ProcessorResult:
        # 获取由上游 IngestProcessor 输出的数据
        sha = entry.upstream_data("discover", "sha256", default="UNKNOWN")
        
        # ProcessorEntry 被绑定至每个样本隔离的沙盒中
        out_file = entry.sample_dir / "heuristics.json"
        out_file.write_text('{"entropy": 7.1}')
        
        # ProcessorResult 决定其路由去向
        if self.config.target_arch != "x86_64":
            return ProcessorResult.filter(reason="unsupported_arch")
            
        return ProcessorResult.ok(
            artifacts={"heuristics": "heuristics.json"},
            data={"analyzed": True, "entropy_ok": True}
        )
```

### 结果判定 (`ProcessorResult`)

Map/BulkMap 处理器必须返回有着严格格式的 `ProcessorResult`：
- **`.ok(data={...}, artifacts={...})`**: 标记执行结果为 `COMPLETED`。`data` 字典存放在该处理器历史记录的命名空间下。`artifacts` 会将键映射至相对文件路径。
- **`.filter(reason="...", data={...})`**: 静默终止样本处理。`SampleState.verdict` 状态更变为 `FILTERED`。
- **`.fail(error="...")`**: 由于发生了致命的意外错误而终止处理。`SampleState.verdict` 更变为 `FAILED`。
- **`.timed_out(budget)`**: 这份工作是耗尽了时间，而不是出了差错。`SampleState.verdict` 更变为 `TIMED_OUT`，并且预算会随之一起带走，好让报告能说明应该改给它多少。当处理器自己在执行某个预算时，请返回它；阶段级的 `timeout:` 则会自行产出这个结果。

Map 处理器还可以覆写 **`should_skip(ctx, entry) -> str | None`**，返回一条理由来声明这份工作已经做过了，通常是因为它自己的输出文件已经在磁盘上。被跳过的样本计为通过，并继续走向下游。这样做时请把那份输出记录为产物：`deepzero run --redo` 之所以要删除已记录的产物，正是为了让缓存下来的文件无法被重新采纳，而一个本次运行从未记录过的文件，会比描述它的那份状态活得更久。

### 声明后续阶段可以使用的内容

处理器的 `data` 键和产物，会成为它之后运行的那些阶段的提示词可用的内容。请在 `provides` 中声明这些名称，这样 `deepzero validate` 就能在运行之前检查提示词，而不是任由一个未知的名称渲染成空：

```python
class Decompiler(MapProcessor):
    description = "Static heuristics extraction"
    provides = (
        "device_name",                    # 本处理器放进 data 的一个键
        "decompiled_dispatch_ioctl_c",    # 产物 decompiled/dispatch_ioctl.c
    )
```

产物的名称由它的路径把分隔符和扩展名一并折进去而得；`engine/stage.py` 中的 `template_key_for_artifact` 是渲染和验证共同使用的唯一规则。只是偶尔才会记录的名称也请列出来，提示词应当容忍它们缺席。关于提示词会收到什么，参阅 [提示词可用的取值]({{ '/zh-CN/reference/pipeline-yaml.html' | relative_url }})。

### 访问上游数据

处理器本质上依赖于前辈处理器所生成的产物和数据。`ProcessorEntry` 门面暴露了一些带有惰性加载的助手方法，可无缝获取这些数据：

```python
# 获取特定字段的简便写法（带有缺省回调值）
sha = entry.upstream_data("discover", "sha256", default="")

# 完整提取上一阶段的 StageOutput 对象
output = entry.upstream("scan")
findings = output.data.get("finding_count", 0)
json_file = output.artifacts.get("findings_file")
```

### 基类

根据你的流水线拓扑要求，去扩展相应的基类：

| 基类 | 处理器类型 | `process()` 签名 |
|-----------|---------------|----------------------|
| `IngestProcessor` | `ingest` | `(ctx, target: Path) → list[Sample]` |
| `MapProcessor` | `map` | `(ctx, entry: ProcessorEntry) → ProcessorResult` |
| `BulkMapProcessor` | `bulk_map` | `(ctx, entries: list[ProcessorEntry]) → list[ProcessorResult]` |
| `ReduceProcessor` | `reduce` | `(ctx, entries: list[ProcessorEntry]) → list[str]` |
