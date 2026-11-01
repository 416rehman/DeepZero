<div align="center">
  <br>
  <img src=".github/banner.svg" alt="DeepZero" width="700">
  <br><br>
  <p><b>自动化漏洞研究流水线引擎</b></p>
  <p>使用 YAML 定义流水线。DeepZero 负责编排、并行计算、容错处理以及状态管理。</p>
  <p>
    <a href="https://github.com/416rehman/DeepZero/actions"><img src="https://img.shields.io/github/actions/workflow/status/416rehman/DeepZero/ci.yml?branch=main&style=flat-square" alt="CI"></a>
    <a href="https://github.com/416rehman/DeepZero/blob/main/LICENSE"><img src="https://img.shields.io/github/license/416rehman/DeepZero?style=flat-square" alt="License"></a>
    <a href="https://blog.ahmadz.ai/DeepZero/zh-CN/"><img src="https://img.shields.io/badge/docs-DeepZero-orange?style=flat-square" alt="Docs"></a>
    <img src="https://img.shields.io/badge/python-3.11+-blue?style=flat-square" alt="Python">
    <img src="https://img.shields.io/badge/platform-windows%20%7C%20linux-lightgrey?style=flat-square" alt="Platform">
  </p>
</div>

<br>

<div align="center">
  <img src=".github/terminal.svg" alt="DeepZero 终端仪表板" width="700">
</div>

<br>

<table align="center">
  <tr>
    <td width="50%"><img src=".github/assets/report-source-audit.png" alt="源码审计的 DeepZero HTML 报告"></td>
    <td width="50%"><img src=".github/assets/report-loldrivers.png" alt="内核驱动审查的 DeepZero HTML 报告"></td>
  </tr>
</table>

<div align="center">
  <sub>同一个引擎，两个领域。报告的措辞来自流水线：同样的代码在左侧显示 <b>6 repositories</b> / <b>not exploitable</b>，在右侧显示 <b>6 drivers</b> / <b>clear</b>。图中为示意数据。</sub>
</div>

<br>

<div align="center">
  <a href="README.md">English</a> | <b>简体中文</b> | <a href="README.fr.md">Français</a>
</div>

<br>

- 🔗 **基于 YAML 的流水线** - 声明式串联数据摄取、过滤、转换和 LLM 评估阶段
- 🧭 **与领域无关** - 引擎本身对二进制文件、代码仓库或网络端点一无所知；领域知识由流水线提供，内置的两条流水线只是示例，而非引擎的用途所在
- ⚡ **并行执行** - 支持每个阶段可配置并发数的 ThreadPoolExecutor
- 💾 **可恢复的运行状态** - 将每个样本的原子状态按语料库分别保存在磁盘上；按 Ctrl+C 中断后，再次运行即可从中断处恢复
- 🔁 **自动识别过期结果** - 每个阶段都会为自己的输入生成指纹，因此修改提示词、规则集或配置后，只会重跑读取过它们的那些阶段，之前的阶段一概不动
- 🤖 **LLM 集成** - 结合 Jinja2 提示词模板，既可通过 [LiteLLM](https://github.com/BerriAI/litellm) 使用 API 密钥，也可完全不用 API 密钥，直接使用你的 Claude Code 订阅
- 📊 **可浏览的报告** - `deepzero report` 会依据运行状态生成一份自包含的 HTML 报告；每条流水线都用自己的词汇来称呼它的实体和裁决
- 🌐 **REST API (正在开发中)** - 通过 HTTP 查询运行状态和样本数据（目前处于实验阶段，尚未完成）
- 🧩 **高可扩展性** - 将自定义处理器编写为 Python 类，并在 YAML 中通过路径引用它们

---

## 📚 官方文档

DeepZero 提供了全面详细的文档，涵盖架构设计、流水线 Schema、命令行参考指南以及自定义处理器开发。

👉 **[点击阅读官方文档](https://blog.ahmadz.ai/DeepZero/zh-CN/)**

---

## ⚡️ 快速开始

DeepZero 需要一个待分析的目标语料库，以及一份用于说明如何处理它的流水线配置文件。

1. **克隆并安装 (要求 Python 3.11+)**
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

2. **配置环境**
   ```bash
   cp .env.example .env
   ```

   在 PowerShell 中请使用 `Copy-Item .env.example .env`。在 `.env` 中设置 `DEEPZERO_MODEL` 可覆盖两条内置流水线的后端和模型，或使用 `-m` 仅覆盖一次运行。例如，`DEEPZERO_MODEL=openai/gpt-4o` 需要设置你自己的 `OPENAI_API_KEY`。
   两条内置流水线默认使用 `claude-code`，即你自己的 Claude Code CLI 的默认模型。请先安装该 CLI 并登录。也可以通过 `DEEPZERO_MODEL` 或 `-m` 选择 LiteLLM 模型，并设置你自己的 API 密钥。

3. **运行一条流水线**
   ```bash
   # 磁盘上的内核驱动程序
   deepzero run ./drivers -p pipelines/loldrivers/pipeline.yaml --preflight

   # 或者源代码，来自一份仓库清单文件或一个存放检出目录的目录
   deepzero run repos.txt -p pipelines/source_audit/pipeline.yaml --preflight
   ```

   请将 `./drivers` 替换为你自己的驱动语料库路径，或创建每行一个仓库 URL 的 `repos.txt`。仓库中不包含这些示例输入。

   `deepzero validate pipelines/loldrivers/pipeline.yaml` / `deepzero validate pipelines/source_audit/pipeline.yaml`
   `--preflight` 会在昂贵的阶段开始之前先确认 LLM 后端已就绪，而不是等到几小时后跑到第一个评估阶段才发现问题。

4. **查看结果**
   ```bash
   deepzero report -p loldrivers --open
   ```
   运行过程中执行也是安全的。报告完全依据运行状态构建，因此随时可以删除后重建。`deepzero runs` 会列出磁盘上的所有运行记录，无论出自哪条流水线或哪个语料库；直接执行 `deepzero report` 而不带任何参数，它会自行判断你指的是哪一次运行。

有关详细的设置说明和示例语料库，请参阅[快速开始文档](https://blog.ahmadz.ai/DeepZero/zh-CN/overview/quickstart.html)。

---

## 📁 仓库目录结构

```text
src/deepzero/
├── cli.py               # click 命令组 (run, report, runs, status, validate, ...)
├── api/                 # REST API (starlette)
├── engine/              # 编排、状态持久化、流水线执行
└── stages/              # 内置处理器 (map, reduce, ingest)

processors/              # 外部处理器 (作为示例提供)
├── ghidra_decompile/    # ghidra 无头反编译器 (MapProcessor)
├── git_ingest/          # git 仓库发现与克隆 (IngestProcessor)
├── loldrivers_filter/   # loldrivers.io 哈希排除过滤器 (MapProcessor)
├── pe_ingest/           # PE 头部解析及驱动程序元数据提取器 (IngestProcessor)
└── semgrep_scanner/     # semgrep 批量扫描器 (BulkMapProcessor)

pipelines/
├── loldrivers/          # BYOVD 内核驱动程序漏洞研究流水线
│   ├── pipeline.yaml
│   ├── assessment.j2    # LLM 提示词模板
│   └── rules/           # semgrep 规则
└── source_audit/        # 针对 git 仓库的源代码审计
    ├── pipeline.yaml
    ├── assessment.j2    # LLM 提示词模板
    └── rules/           # 覆盖八种语言的 136 条 semgrep 规则

docs/                    # 基于 Jekyll 的 GitHub Pages 官方文档
tests/                   # pytest 测试套件
```

---

## 🤝 参与贡献

CI 会在 GitHub Actions 上针对每个受支持的解释器运行测试套件。

提交代码之前，请运行代码格式化和安全检查：

```bash
ruff check . && ruff format --check . && bandit -ll -ii -c pyproject.toml -r .
```

在提交 Pull Request 之前，请阅读[贡献指南](CONTRIBUTING.md)和[行为准则](CODE_OF_CONDUCT.md)。

---

## 📄 开源协议

DeepZero 基于 [MIT 协议](LICENSE) 开源。
