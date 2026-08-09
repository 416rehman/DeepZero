---
layout: default
title: 仓库结构
order: 2
---

## 仓库结构

```text
src/deepzero/
├── __init__.py          # 语义化版本号 (SemVer) 定义
├── __main__.py          # 模块入口点
├── cli.py               # Click 命令行应用程序接口
├── api/                 # Starlette REST 终端节点
├── engine/              # 核心执行与编排逻辑
│   ├── backends/        # 可插拔的 LLM 后端，按模型 scheme 解析
│   └── report.py        # 依据运行状态生成可浏览的报告
└── stages/              # 标准库内置处理器

processors/              # 贡献的第三方和参考处理器
├── ghidra_decompile/    # Ghidra 无头反编译器 (Map)
├── git_ingest/          # Git 仓库发现与克隆 (Ingest)
├── loldrivers_filter/   # loldrivers.io 哈希排除过滤器 (Map)
├── pe_ingest/           # PE 头部解析及驱动程序元数据提取器 (Ingest)
└── semgrep_scanner/     # Semgrep 批量扫描器 (BulkMap)

pipelines/               # 流水线声明与配置逻辑
├── loldrivers/          # BYOVD 内核驱动程序研究
└── source_audit/        # 针对 git 仓库的源代码审计

docs/                    # 基于 Jekyll 的 GitHub Pages 官方文档
tests/                   # Pytest 验证测试套件
```

每个流水线目录都存放着自己的 `pipeline.yaml`、其 LLM 阶段所渲染的 Jinja 提示词模板，以及其扫描阶段所加载的 semgrep 规则。新增一条流水线时，该目录之外的任何东西都不必改动，而这正是关键所在：`pipelines/` 和 `processors/` 是按路径读取的，而不是在代码中注册的。
