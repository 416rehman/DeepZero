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
- `ctx.global_config`: `TypedDict` 字典，包含流水线级别的 `settings` (设置), `knowledge` (知识), 已配置的 `model`，以及 `pipeline_dir`，即以字符串形式给出的、本流水线被加载自的那个目录。最后这个键之所以存在，是因为 `setup()` 只拿得到这份配置、拿不到上下文；若没有它，一个指名流水线自带文件的配置值就会改为相对工作目录来解析。`ctx.get_setting(key)` 和 `ctx.get_knowledge(key)` 是读取它的简便写法。
- `ctx.llm`: 一个通用代理实例 (实现了 `LLMProtocol`)，自带原生补偿/重试 (backoff/retry) 机制；当流水线没有配置模型时为 `None`。它驱动哪个后端，由流水线的 `model` 字符串解析决定，因此处理器调用 `ctx.llm.complete()` 时，面对 API 密钥和面对本地 agent CLI 的写法完全一样。参阅 [选择模型]({{ '/zh-CN/reference/pipeline-yaml.html' | relative_url }})。
- `ctx.log`: 已预先配置、带命名空间的 `logging.Logger`。
- `ctx.progress`: 进度上报钩子，`update(amount=, total=, description=)`，这样长时间运行的摄取阶段或批量阶段会在仪表盘上显示出进展，而不是看起来像卡住了。
- `ctx.shutdown_event`: 一个 `threading.Event`，在运行被中断时被置位。执行长时间工作的处理器应当检查它并提前返回，而不是在写入过程中被杀掉。
- `ctx.conclude(**fields)`: 记录一条关于整个语料库、而非关于其中任何单个样本的发现。有些问题只有在汇总之后才有答案：某个端点背后是哪个模型，一堆崩溃究竟代表多少个互不相同的缺陷。这些字段会被合并进本次运行的 `conclusion`，并且运行状态会立刻保存，因此被中断的运行依然带着它此前已经得出的结论。

引擎只会为 `reduce` 或 `bulk_map` 阶段把 `conclude` 接到真正的写入器上，因为只有这两类阶段能在一次调用中看到全部样本：

```python
class ModelFingerprint(ReduceProcessor):
    def process(self, ctx: ProcessorContext, entries: list[ProcessorEntry]) -> list[str]:
        ctx.conclude(headline="every probe answers as the same model family", probes=len(entries))
        return [e.sample_id for e in entries]
```

在 map 或 ingest 阶段中，这个调用会记录一条日志，说明 `ctx.conclude()` 只对 reduce 或 bulk_map 阶段可用、本次调用已被忽略，然后什么也不做。散布在线程池上的逐样本通道无法在不与自己竞争的前提下替整个语料库发言：最后完成的那个样本会胜出，而落败的那个永远不会知道自己已被覆盖。

### 执行钩子

处理器实现由引擎调用的特定生命周期钩子：

1. **`validate(ctx: ProcessorContext) -> list[str]`**: 在初始架构验证期间调用（通过 `deepzero validate` 或在执行前）。如果依赖项（例如，缺少二进制文件、无法解析的 YAML）失败，则返回包含错误字符串的列表。此处的上下文是一份精简版：`ctx.global_config` 只带有 `settings`、`knowledge` 和 `model`，没有 `pipeline_dir` 键，而 `ctx.llm` 为 `None`，因为此时还没有任何 provider 被构建出来。需要用到这两者中任意一个的检查，都会误读这条流水线。`ctx.pipeline_dir` 本身是有值的，因此请通过它来解析与流水线放在一起的文件。
2. **`setup(global_config: dict) -> None`**: 在线程池激活前精确执行一次。
3. **`process(...)`**: 核心操作。其函数签名随处理器类型 (ProcessorType) 而变化。
4. **`teardown() -> None`**: 在流水线完成或发生致命中断时执行。

对于单个样本开销很大的 Map 处理器，还有一个钩子值得覆写：

5. **`max_parallelism() -> int | None`**: 自动并发的上限。它只在阶段的 YAML 声明了 `parallel: 0` 时生效；任何大于零的 `parallel: N` 都会按原样采纳，并且在上限或 `max_workers` 设置被查阅之前就已生效。当每个样本都要付出一个 JVM、一个容器或几个 GB 内存的代价时，请返回一个整数，好让一个主动要求自动伸缩的阶段不至于每个核心都占一个工作线程。默认值 `None` 表示没有上限。不写 `parallel:` 和写 `parallel: 0` 并不是一回事：没有指名它的阶段会以 4 载入，而这算作一个显式数值，因此上限永远够不到它。

### 处理器实例自身携带的内容

`ctx` 描述的是本次运行。处理器对象自身携带的，则是属于这个阶段的东西：
- `self.config`: 解析后的 `Config` 数据类；当处理器没有声明 `Config` 时，则是原始的 YAML 字典。
- `self.spec`: 构建出这个实例所依据的 `StageSpec`，包含它的名称、config 配置块、`parallel`、`on_failure`、`max_retries` 和 `timeout`。
- `self.log`: 一个以阶段名为命名空间的日志器。
- `self.global_config`: 与 `ctx` 携带的那份 `GlobalConfig` 是同一个，由引擎在 `setup()` 运行之前设置。
- `self.processor_dir`: 存放本处理器自己那个 `.py` 文件的目录，用于放在它旁边一起分发的脚本、模板和规则文件。它不是 `ctx.pipeline_dir`：一条流水线可以指名一个位于完全另一处的处理器，这时两者指向的地方就不一样了。
- `self.cache_dir`: 位于 `./.cache/<stage name>` 的持久目录，首次访问时创建。引擎中没有任何东西会清理它，因此它会跨运行留存下来，适合放下载内容以及其他重复代价过高的工作成果。

### 定义处理器配置

用名为 `Config` 的内嵌 `@dataclass` 来声明处理器所接受的 YAML 配置。引擎会展开 [流水线 YAML]({{ '/zh-CN/reference/pipeline-yaml.html' | relative_url }}) 中的 `${VAR}` 和 `${VAR:-default}`，并通过标准 Python [`dataclasses`](https://docs.python.org/3/library/dataclasses.html) 用该阶段的 `config` 配置块实例化你的 `Config`。

声明这些字段并不等于强制执行它们。数据类没有声明的键会被记录为“本处理器不读取该键”，同时列出它确实接受的那些名称，随后被丢弃，运行照常继续；`limit` 由引擎自己读取，不在该警告之列。没有任何东西检查类型。未设置的 `${VAR}` 会展开成空字符串，而不是保留字面量，因此缺失的环境变量到手时是一个存在但为空的字段，而不是一个错误。请给每个字段都设默认值，并把真正的检查放进 `validate()`，它会在任何样本被碰到之前运行。

```python
import json
import math
from collections import Counter
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

        # entry.source_path 就是被分析的对象：摄取阶段为这个样本记录下来的
        # 那个东西，也是你能拿到的唯一入口
        entropy = self._shannon_entropy(entry.source_path.read_bytes())

        # ProcessorEntry 被绑定至每个样本隔离的沙盒中
        out_file = entry.sample_dir / "heuristics.json"
        out_file.write_text(json.dumps({"sha256": sha, "entropy": entropy}))

        # ProcessorResult 决定其路由去向
        if self.config.target_arch != "x86_64":
            return ProcessorResult.filter(reason="unsupported_arch")

        return ProcessorResult.ok(
            artifacts={"heuristics": "heuristics.json"},
            data={"analyzed": True, "entropy_ok": entropy <= self.config.max_entropy}
        )

    @staticmethod
    def _shannon_entropy(blob: bytes) -> float:
        counts = Counter(blob)
        return -sum(
            (n / len(blob)) * math.log2(n / len(blob)) for n in counts.values()
        ) if blob else 0.0
```

### 结果判定 (`ProcessorResult`)

Map/BulkMap 处理器必须返回有着严格格式的 `ProcessorResult`：
- **`.ok(data={...}, artifacts={...})`**: 标记执行结果为 `COMPLETED`。`data` 字典存放在该处理器历史记录的命名空间下。`artifacts` 会将键映射至相对文件路径。
- **`.filter(reason="...", data={...})`**: 静默终止样本处理。`SampleState.verdict` 状态更变为 `FILTERED`。
- **`.fail(error="...")`**: 由于发生了致命的意外错误而终止处理。`SampleState.verdict` 更变为 `FAILED`。
- **`.timed_out(budget)`**: 这份工作是耗尽了时间，而不是出了差错。`SampleState.verdict` 更变为 `TIMED_OUT`，并且预算会随之一起带走，好让报告能说明应该改给它多少。当处理器自己在执行某个预算时，请返回它；阶段级的 `timeout:` 则会自行产出这个结果。

Map 处理器还可以覆写 **`should_skip(ctx, entry) -> str | None`**，返回一条理由来声明这份工作已经做过了，通常是因为它自己的输出文件已经在磁盘上。被跳过的样本计为通过，并继续走向下游。这样做时请把那份输出记录为产物：`deepzero run --redo` 之所以要删除已记录的产物，正是为了让缓存下来的文件无法被重新采纳，而一个本次运行从未记录过的文件，会比描述它的那份状态活得更久。

除了路径之外，还要一并检查 `entry.cache_is_valid`，绝不要只看路径：

```python
def should_skip(self, ctx: ProcessorContext, entry: ProcessorEntry) -> str | None:
    if entry.cache_is_valid and (entry.sample_dir / "out.json").exists():
        return "cached"
    return None
```

当磁盘上那个文件产自一份此后已被改动的提示词、规则集或配置时，`cache_is_valid` 为 `False`：引擎会把针对上一次运行记录下来的输入摘要，与本阶段的输入此刻算出的摘要做比对。只检查 `.exists()` 的 `should_skip` 会重新采纳一份输出，而它回答的问题流水线已经不再问了。内置的 LLM 阶段和随附的 Semgrep 扫描器，在采纳既有文件的地方都加了这道防护。

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

### 一个条目携带的内容 (`ProcessorEntry`)

每个 map、bulk_map 和 reduce 处理器拿到的都是条目，而不是原始样本：
- `entry.sample_id`: 该样本的唯一标识符，也是其状态存放时所用的键。
- `entry.source_path`: 指向被分析对象的 `Path`，也就是摄取阶段为这个样本记录下来的那个东西。这是 map 处理器拿到其输入的唯一入口。
- `entry.filename`: 用于日志和报告中的显示名称。
- `entry.sample_dir`: 本样本隔离的工作目录，输出应当放在这里。
- `entry.cache_is_valid`: 已经躺在 `sample_dir` 里的输出，是否由本阶段当前的输入产出，如上文 `should_skip` 处所述。

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
