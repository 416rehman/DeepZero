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
└── stages/              # 标准库内置处理器

processors/              # 贡献的第三方和参考处理器
pipelines/               # 流水线声明与配置逻辑
tests/                   # Pytest 验证测试套件
```
