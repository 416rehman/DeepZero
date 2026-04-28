---
layout: default
title: 快速入门
order: 1
---

## 快速入门

DeepZero 需要一个待分析的目标文件语料库，以及一个详细说明如何处理这些文件的 [流水线配置]({{ '/zh-CN/reference/pipeline-yaml.html' | relative_url }})。我们提供了一个 [完整的示例流水线]({{ '/zh-CN/reference/included-pipeline.html' | relative_url }})，它旨在通过使用 [LOLDrivers 项目](https://www.loldrivers.io/) 显式过滤已知的哈希值，从而在原始二进制数据集 (例如，Snappy Driver Installer 语料库) 中寻找新的 BYOVD (自带易受攻击驱动程序) 候选目标。

### 1. 安装

DeepZero 要求使用 **Python 3.11+**。

```bash
git clone https://github.com/416rehman/DeepZero.git
cd DeepZero
pip install -e .
```

### 2. 环境配置

如果集成了 AI 分析阶段，请通过创建 `.env` 文件来配置 API 密钥：

```bash
cp .env.example .env
```

### 3. 执行流水线

针对目标路径执行内置的 LOLDrivers 流水线：

```bash
deepzero run C:\drivers -p .\pipelines\loldrivers\pipeline.yaml
```

<div class="callout">
    <p><strong>注意：</strong> DeepZero 会安全地对执行过程 <a href="{{ '/zh-CN/overview/architecture.html' | relative_url }}">进行并行化</a>，并缓存中间输出。如需优雅停止，请发送 SIGINT 信号 (<code>Ctrl+C</code>)。具有相同参数的后续执行将会从 <a href="{{ '/zh-CN/system/state-persistence.html' | relative_url }}">持久化的磁盘状态</a> 瞬间恢复运行。</p>
</div>
