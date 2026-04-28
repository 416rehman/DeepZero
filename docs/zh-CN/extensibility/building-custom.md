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
- `ctx.global_config`: `TypedDict` 字典，包含流水线级别的 `settings` (设置), `knowledge` (知识), 和已配置的 `model`。
- `ctx.llm`: 一个通用代理实例 (实现了 `LLMProtocol` 并绑定至 [LiteLLM](https://github.com/BerriAI/litellm))，对带有原生补偿/重试 (backoff/retry) 机制的提供商 API 进行了抽象。
- `ctx.log`: 已预先配置、带命名空间的 `logging.Logger`。

### 执行钩子

处理器实现由引擎调用的特定生命周期钩子：

1. **`validate(ctx: ProcessorContext) -> list[str]`**: 在初始架构验证期间调用（通过 `deepzero validate` 或在执行前）。如果依赖项（例如，缺少二进制文件、无法解析的 YAML）失败，则返回包含错误字符串的列表。
2. **`setup(global_config: dict) -> None`**: 在线程池激活前精确执行一次。
3. **`process(...)`**: 核心操作。其函数签名随处理器类型 (ProcessorType) 而变化。
4. **`teardown() -> None`**: 在流水线完成或发生致命中断时执行。

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

### 访问上游数据

处理器本质上依赖于前辈处理器所生成的工件和数据。`ProcessorEntry` 门面暴露了一些带有惰性加载的助手方法，可无缝获取这些数据：

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
