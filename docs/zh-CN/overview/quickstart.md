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
python -m pip install -e ".[full]"
```

请在克隆的仓库目录中运行以下命令。`full` 可选依赖包含用于 PE 解析的 LIEF 和用于 API 模型的 LiteLLM。仅安装引擎可使用 `python -m pip install -e .`。

运行示例流水线前，请在同一环境中安装外部工具：

- 两条流水线：PATH 中可用的 **Semgrep**（`python -m pip install semgrep`）和一个 LLM 后端。
- 源代码审计：PATH 中可用的 **Git**。
- 驱动分析：**Ghidra** 及该版本支持的 **JDK**，并在 `.env` 中将 `GHIDRA_INSTALL_DIR` 设置为你自己的安装目录。
- 默认 LLM：安装 **Claude Code CLI** 并登录你自己的账户。它使用 CLI 的默认模型，无需 API 密钥。也可以在下方配置 API 模型及密钥。

使用 WSL 时，请在 WSL 环境内安装并运行工具、Python 和 DeepZero。

### 2. 环境配置

如果集成了 AI 分析阶段，请通过创建 `.env` 文件来配置 API 密钥：

```bash
cp .env.example .env
```

在 PowerShell 中请使用 `Copy-Item .env.example .env`。在 `.env` 中设置 `DEEPZERO_MODEL` 可覆盖两条内置流水线的后端和模型，或使用 `-m` 仅覆盖一次运行。例如，`DEEPZERO_MODEL=openai/gpt-4o` 需要设置你自己的 `OPENAI_API_KEY`。

两条内置流水线都声明了 `claude-code` 模型，它驱动的是你本机上已登录的 Claude Code CLI，完全不需要 API 密钥。你也可以改用任意 [LiteLLM 模型]({{ '/zh-CN/reference/pipeline-yaml.html' | relative_url }})，通过流水线的 `model` 字段或命令行上的 `-m` 指定，上面那些 API 密钥正是为此准备的。

### 3. 在投入一次长时间运行之前先做检查

这些运行都很漫长。下面这条命令很廉价，它在几秒而不是几小时内就给出答案，而且它什么也不会启动：

```bash
# 解析每一个处理器，检查它的前置条件，并检查每一份提示词
deepzero validate pipelines/loldrivers/pipeline.yaml
```

报告出错误时它以 1 退出，因此它可以充当一个提交钩子或一个 CI 步骤，而不只是拿来看看。

### 4. 执行流水线

针对目标路径执行内置的 LOLDrivers 流水线：

```bash
deepzero run ./drivers -p pipelines/loldrivers/pipeline.yaml
```

请将 `./drivers` 替换为你自己的驱动语料库路径，或创建每行一个仓库 URL 的 `repos.txt`。仓库中不包含这些示例输入。

或者执行源代码审计，目标为一份仓库清单文件，或一个存放检出目录的目录：

```bash
deepzero run repos.txt -p pipelines/source_audit/pipeline.yaml
```

上面两条都接受 `--preflight`，它会发起一次极小的调用，确认 LLM 后端确实已登录。后端若尚未就绪，它会在几秒内停下；否则运行照常继续。因此它是一个加在你本来就要启动的运行上的标志，而不是一条单独敲出来的检查命令。不用它的另一种下场，是跑了好几个小时之后才在第一个评估阶段发现问题：

```bash
deepzero run ./drivers -p pipelines/loldrivers/pipeline.yaml --preflight
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

只写出流水线名时，会解析到它最近的那个语料库，并说明这条流水线还见过哪些别的语料库，因为最新的那次运行并不总是被问及的那一次。要改为查看 `work` 下的每一次运行，无论它由哪条流水线或哪个语料库产出，按从新到旧排列：

```bash
deepzero runs
```

它会列出每次运行的流水线、语料库、状态和样本数量，并打印出用于浏览其中某一次的 `deepzero report -w <dir>` 命令行。不带任何标志的 `deepzero report` 直接回答同一个问题：只有一次运行时就直接采用它，有多次时则变成一份供你挑选的列表。

报告完全依据运行状态生成，所以删除后可以重建；而它用什么词来称呼所发现的东西，则 [由流水线声明]({{ '/zh-CN/reference/pipeline-yaml.html' | relative_url }})。
