---
layout: default
title: 快速入门
order: 1
---

## 快速入门

DeepZero 需要一个待分析的目标语料库，以及一个详细说明如何处理它的 [流水线配置]({{ '/zh-CN/reference/pipeline-yaml.html' | relative_url }})。它自带两条 [完整的流水线]({{ '/zh-CN/reference/included-pipeline.html' | relative_url }})：一条在原始二进制数据集 (例如，Snappy Driver Installer 语料库) 中寻找新的 BYOVD (自带易受攻击驱动程序) 候选目标，并通过 [LOLDrivers 项目](https://www.loldrivers.io/) 显式过滤掉已知的哈希值；另一条则针对 git 仓库审计源代码。

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

两条内置流水线都声明了 `claude-code` 模型，它驱动的是你本机上已登录的 Claude Code CLI，完全不需要 API 密钥。你也可以改用任意 [LiteLLM 模型]({{ '/zh-CN/reference/pipeline-yaml.html' | relative_url }})，通过流水线的 `model` 字段或命令行上的 `-m` 指定，上面那些 API 密钥正是为此准备的。

### 3. 在投入一次长时间运行之前先做检查

这些运行都很漫长。下面两条命令都很廉价，而且失败只需几秒，而不是几小时：

```bash
# 解析每一个处理器，检查它的前置条件，并检查每一份提示词
deepzero validate pipelines/loldrivers/pipeline.yaml
```

报告出错误时它以 1 退出，因此它可以充当一个提交钩子或一个 CI 步骤，而不只是拿来看看。

```bash
# 发起一次极小的调用，确认 LLM 后端确实已登录
deepzero run C:\drivers -p .\pipelines\loldrivers\pipeline.yaml --preflight
```

### 4. 执行流水线

针对目标路径执行内置的 LOLDrivers 流水线：

```bash
deepzero run C:\drivers -p .\pipelines\loldrivers\pipeline.yaml
```

或者执行源代码审计，目标为一份仓库清单文件，或一个存放检出目录的目录：

```bash
deepzero run repos.txt -p .\pipelines\source_audit\pipeline.yaml
```

<div class="callout">
    <p><strong>注意：</strong> DeepZero 会安全地对执行过程 <a href="{{ '/zh-CN/overview/architecture.html' | relative_url }}">进行并行化</a>，并缓存中间输出。如需优雅停止，请发送 SIGINT 信号 (<code>Ctrl+C</code>)。具有相同参数的后续执行将会从 <a href="{{ '/zh-CN/system/state-persistence.html' | relative_url }}">持久化的磁盘状态</a> 瞬间恢复运行。</p>
</div>

每个语料库都有属于自己的工作目录，因此把同一条流水线指向第二个目标时，会开启一次新的运行，而不是恢复到第一次运行的结果里。两者都仍然可以恢复。

### 5. 查看结果

运行会在第一个阶段之前打印出一个报告 URL，并在结果陆续产生时保持该报告最新，因此运行期间就可以打开它一边看一边等。要随时重新生成报告，包括针对仍在进行中的运行：

```bash
deepzero report -p loldrivers --open
```

报告完全依据运行状态生成，所以删除后可以重建；而它用什么词来称呼所发现的东西，则 [由流水线声明]({{ '/zh-CN/reference/pipeline-yaml.html' | relative_url }})。
