<div align="center">
  <br>
  <img src=".github/banner.svg" alt="DeepZero" width="700">
  <br><br>
  <p><b>自动化漏洞研究流水线引擎</b></p>
  <p>使用 YAML 定义流水线。DeepZero 负责编排、并行计算、容错处理以及状态管理。</p>
  <p>
    <a href="https://github.com/416rehman/DeepZero/actions"><img src="https://img.shields.io/github/actions/workflow/status/416rehman/DeepZero/ci.yml?branch=main&style=flat-square" alt="CI"></a>
    <a href="https://github.com/416rehman/DeepZero/blob/main/LICENSE"><img src="https://img.shields.io/github/license/416rehman/DeepZero?style=flat-square" alt="License"></a>
    <img src="https://img.shields.io/badge/python-3.11+-blue?style=flat-square" alt="Python">
    <img src="https://img.shields.io/badge/platform-windows%20%7C%20linux-lightgrey?style=flat-square" alt="Platform">
  </p>
</div>

<br>

<div align="center">
  <img src=".github/terminal.svg" alt="DeepZero terminal dashboard" width="700">
</div>

<br>

<div align="center">
  <a href="README.md">English</a> | <b>简体中文</b> | <a href="README.fr.md">Français</a>
</div>

<br>

- 🔗 **基于 YAML 的流水线** - 声明式串联数据摄取、过滤、转换和 LLM 评估阶段
- ⚡ **并行执行** - 支持每个阶段可配置并发数的 ThreadPoolExecutor
- 💾 **可恢复的运行状态** - 将每个样本的原子状态保存在磁盘上；按 Ctrl+C 中断后，再次运行即可从中断处恢复
- 🤖 **LLM 集成** - 结合 Jinja2 提示词模板，通过 [LiteLLM](https://github.com/BerriAI/litellm) 支持任意大语言模型
- 🌐 **REST API (正在开发中)** - 通过 HTTP 查询运行状态和样本数据（目前处于实验阶段，尚未完成）
- 🧩 **高可扩展性** - 将自定义处理器编写为 Python 类，并在 YAML 中通过路径引用它们

---

## 📚 官方文档

DeepZero 提供了全面详细的文档，涵盖架构设计、流水线 Schema、命令行参考指南以及自定义处理器开发。

👉 **[点击阅读官方文档（英文）](https://416rehman.github.io/DeepZero/)**

---

## ⚡️ 快速开始

DeepZero 需要一个待分析的语料库文件目录，以及一份用于说明如何处理这些文件的流水线配置文件。

1. **克隆并安装 (要求 Python 3.11+)**
   ```bash
   git clone https://github.com/416rehman/DeepZero.git
   cd DeepZero
   pip install -e .
   ```

2. **配置环境**
   ```bash
   cp .env.example .env
   ```

3. **运行一条流水线**
   ```bash
   deepzero run C:\drivers -p .\pipelines\loldrivers\pipeline.yaml
   ```

有关详细的设置说明和示例语料库，请参阅[快速开始文档](https://416rehman.github.io/DeepZero/overview/quickstart.html)。

---

## 📁 仓库目录结构

```text
src/deepzero/
├── api/                 # REST API (starlette)
├── engine/              # 编排、状态持久化、流水线执行
└── stages/              # 内置处理器 (map, reduce, ingest)

processors/              # 外部处理器 (作为示例提供)
├── ghidra_decompile/    # ghidra 无头反编译器 (MapProcessor)
├── loldrivers_filter/   # loldrivers.io 哈希排除过滤器 (MapProcessor)
├── pe_ingest/           # PE 头部解析及驱动程序元数据提取器 (IngestProcessor)
└── semgrep_scanner/     # semgrep 批量扫描器 (BulkMapProcessor)

pipelines/
└── loldrivers/          # BYOVD 内核驱动程序漏洞研究流水线
    ├── pipeline.yaml
    ├── assessment.j2    # LLM 提示词模板
    └── rules/           # semgrep 规则

docs/                    # 基于 Jekyll 的 GitHub Pages 官方文档
tests/                   # pytest 测试套件
```

---

## 🤝 参与贡献

CI 会在 GitHub Actions 上通过 Python 3.11 和 3.12 运行。

提交代码之前，请运行代码格式化和安全检查：

```bash
ruff check . && ruff format --check . && bandit -ll -ii -c pyproject.toml -r .
```

在提交 Pull Request 之前，请阅读[贡献指南](CONTRIBUTING.md)和[行为准则](CODE_OF_CONDUCT.md)。

---

## 📄 开源协议

DeepZero 基于 [MIT 协议](LICENSE) 开源。
