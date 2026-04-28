---
layout: default
title: 内置处理器
order: 1
---

## 内置处理器

| 标识符 | 类型 | 功能 |
| ---------- | ---- | ------------- |
| `file_discovery` | 摄取 (Ingest) | 递归文件系统遍历与加密哈希。 |
| `metadata_filter` | 映射 (Map) | 布尔约束检查与字段去重。 |
| `hash_exclude` | 映射 (Map) | 针对内联列表或纯文本文件的加密排除过滤。 |
| `generic_llm` | 映射 (Map) | Jinja2 模板渲染、LLM 调用与响应解析。 |
| `generic_command` | 映射 (Map) | 带有上下文变量替换的任意 Shell 执行。 |
| `top_k` | 归约 (Reduce) | 基于数值标量截断样本集。 |
| `sort` | 归约 (Reduce) | 在不减少数据集的情况下对样本进行确定性重新排序。 |
