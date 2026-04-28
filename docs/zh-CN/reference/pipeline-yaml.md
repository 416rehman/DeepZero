---
layout: default
title: 流水线 YAML
order: 2
---

## 流水线配置

DeepZero 中的 **流水线 (Pipeline)** 是一个声明式的执行图，定义了一个连续的、高弹性的数据转换过程。它将原始物理数据集转化为高信号的分析数据集。

流水线架构在 YAML 中有着严格定义。DeepZero 动态解析配置，原生支持 Shell 变量展开 (例如，`${VAR:-default}`)。

### 配置架构

```yaml
name: my_pipeline
description: 标准漏洞研究流水线
version: "1.0"
model: openai/gpt-4o  # 默认的 LiteLLM 集成目标

settings:
  work_dir: work
  max_workers: 8  # ThreadPoolExecutor 线程数的全局上限

stages:
  # 阶段 1: 必须是一个 IngestProcessor (摄取处理器)
  - name: discover
    processor: file_discovery
    config:
      extensions: ["*"]

  # 阶段 2: 同步过滤器
  - name: filter
    processor: metadata_filter
    config:
      require:
        is_executable: true

  # 阶段 3: 高延迟 Map 处理
  - name: decompile
    processor: ghidra_decompile/ghidra_decompile.py
    parallel: 4           # 将并行映射并发数限制为 4 个并发的 Ghidra JVM
    timeout: 300          # 强制通过 process.py 为每个样本设置 300 秒的严格终止倒计时
    on_failure: skip      # 发生异常时静默处理而不是终止 (skip, retry, abort)
    max_retries: 2        # 重试逻辑的执行限制
    config:
      ghidra_install_dir: ${GHIDRA_INSTALL_DIR}
```

### 阶段选项

定义在 `stages:` 数组下的每个阶段都接受以下属性：

| 字段 | 类型 | 默认值 | 描述 |
|-------|------|---------|-------------|
| `name` | 字符串 | `stage_N` | 流水线内的唯一阶段名称 |
| `processor` | 字符串 | 必须 | 处理器引用 (见下文) |
| `config` | 字典 | `{}` | 处理器特定配置 |
| `parallel` | 整数 | `4` | Map 处理器的并发数。`0` 表示自动缩放为 `os.cpu_count()` |
| `timeout` | 整数 | `0` | 每个样本的超时时间（秒，0 = 无超时） |
| `on_failure` | 字符串 | `skip` | 定义容错行为：`skip` (跳过), `retry` (重试), 或 `abort` (终止) |
| `max_retries` | 整数 | `0` | 当设置了 `on_failure: retry` 时的重试次数 |

### 解析逻辑 (`engine/pipeline.py`)

当通过 CLI 调用时，解析器会按严格的层级顺序尝试解析处理器：
1. **路径解析器:** 以 `.py` 结尾的直接文件路径 (例如，`processors/ghidra/ghidra.py:Decompiler`)。
2. **目录查找:** `pipeline/my_pipeline/processors/`。
3. **内部注册表:** 在 `stages/__init__.py` 中显式注册的系统内置组件。
4. **点分 Python 导入:** 动态计算的模块 (例如，`my.python.module:MyClass`)。

### 动态展开

在架构验证绑定处理器之前，DeepZero 会遍历整个 YAML DOM 树，匹配 `\$\{([^}]+)\}` 正则表达式。环境变量决定了最终解析的运行时配置。这明确避免了在已提交的 `.yaml` 流水线中硬编码 API 密钥或安装目录。
