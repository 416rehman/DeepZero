---
layout: default
title: CLI 参考
order: 1
---

## 命令行界面

`deepzero` CLI 是执行和管理流水线的主要交互入口。

```bash
# 标准执行
deepzero run ./targets -p pipelines/loldrivers/pipeline.yaml

# 携带状态清理功能执行 (全新运行)
deepzero run ./targets -p pipelines/loldrivers/pipeline.yaml --clean

# 检查执行状态
deepzero status -p loldrivers

# 启动交互式分析 REPL
deepzero interactive -w work/loldrivers

# 启动 Starlette REST API
deepzero serve -w work/loldrivers --port 8420

# 搭建新的自定义流水线
deepzero init my_custom_pipeline

# 仅验证架构 (不执行)
deepzero validate loldrivers

# 检查系统注册表
deepzero list-processors
```

### 核心命令

| 命令 | 描述 |
| --------- | ----------- |
| `run` | 针对目标执行流水线。如果状态存在则自动恢复。 |
| `status` | 显示当前流水线运行状态、裁决和阶段指标。 |
| `interactive` | 提供由 LLM 支持的、针对流水线结果进行对话的交互式分析 REPL。 |
| `serve` | 启动 REST API 服务器以向外部暴露流水线状态。 |
| `init` | 搭建一个新的流水线目录，并生成标准的 `pipeline.yaml` 样板文件。 |
| `validate` | 对流水线的架构和处理器导入进行预运行验证 (Dry-run)。 |
| `list-processors` | 列出所有内置以及动态注册的处理器类型。 |

### 执行标志 (`run`)
| 标志 | 描述 |
| --------- | ----------- |
| `TARGET` | 位置参数。分析语料库的路径（文件或目录）。 |
| `-p, --pipeline` | 标识符、目录名，或离散的 YAML 文件路径。 |
| `--clean` | 在执行之前清除现有的状态目录。 |

### REST API (`serve`)

> [!WARNING]
> **开发中 / 实验性功能**
> REST API 服务器目前尚未完成，极不稳定，**不应被使用**。提供它仅用于实验性的本地开发。

启动一个只读的 FastAPI/Starlette REST API 以供查询运行状态和样本数据。

| 终端节点 | 方法 | 描述 |
|----------|--------|-------------|
| `/api/health` | GET | 运行健康检查 |
| `/api/runs` | GET | 列出工作目录中可用的流水线运行实例 |
| `/api/run` | GET | 获取当前运行的全局状态和指标 |
| `/api/samples` | GET | 列出样本 (可通过 `?verdict=`, `?stage=`, `?status=` 进行过滤) |
| `/api/samples/{sample_id}` | GET | 获取包含历史流水线数据的完整样本状态 |
| `/api/samples/{sample_id}/artifacts/{name}` | GET | 读取由某个处理器生成的特定文件产物 |
