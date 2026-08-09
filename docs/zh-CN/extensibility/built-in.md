---
layout: default
title: 内置处理器
order: 1
---

## 内置处理器

通过裸名称引用。执行 `deepzero list-processors` 可以看到它们及其实现类。

| 标识符 | 类型 | 功能 |
| ---------- | ---- | ------------- |
| `file_discovery` | 摄取 (Ingest) | 递归文件系统遍历与加密哈希。 |
| `metadata_filter` | 映射 (Map) | 通过 `require:` 进行字段相等判断，通过任意 `min_<field>` / `max_<field>` 键进行数值阈值判断，并通过 `dedup_field` 去重。字段取自上游各阶段合并后的数据。 |
| `hash_exclude` | 映射 (Map) | 针对内联列表或纯文本文件的加密排除过滤。 |
| `generic_llm` | 映射 (Map) | Jinja2 模板渲染、LLM 调用与响应解析。 |
| `generic_command` | 映射 (Map) | 带有上下文变量替换的任意 Shell 执行。 |
| `top_k` | 归约 (Reduce) | 基于数值标量截断样本集。 |
| `sort` | 归约 (Reduce) | 在不减少数据集的情况下对样本进行确定性重新排序。 |

`min_<field>` 阈值会把上游任何阶段都未记录过的字段读作零，从而过滤掉该样本。对于确实不存在的字段这是正确答案，而对于被改了名的字段则是错误答案，因此当某个阶段突然在几秒内过滤掉整个语料库时，值得对照上游实际提供的名称检查一下。

## 内置的外部处理器

它们位于 `processors/` 中并通过路径引用，因此被当作普通的外部处理器读取，而不是享有特权的内置处理器。[内置流水线]({{ '/zh-CN/reference/included-pipeline.html' | relative_url }}) 使用的正是它们，每个处理器都在源码旁附有一份 README，说明其完整配置。

| 路径 | 类型 | 功能 |
| ---- | ---- | ------------- |
| `pe_ingest/pe_ingest.py` | 摄取 (Ingest) | 发现 PE 文件、解析头部并提取驱动程序元数据。 |
| `git_ingest/git_ingest.py` | 摄取 (Ingest) | 把 git 仓库变成样本，来源可以是一个存放检出目录的目录，也可以是一份 URL 清单。 |
| `loldrivers_filter/loldrivers_filter.py` | 映射 (Map) | 排除 SHA-256 命中 loldrivers.io 数据库中已知条目的样本。 |
| `ghidra_decompile/ghidra_decompile.py` | 映射 (Map) | Ghidra 无头反编译，后处理脚本可配置。 |
| `semgrep_scanner/semgrep_scanner.py` | 批量映射 (BulkMap) | 对当前活动样本进行批量 semgrep 扫描。 |

### `git_ingest`

一个样本就是一个仓库，它的 `source_path` 是检出目录的根，而这正是源码扫描器希望被指向的位置。CLI 目标始终是一个真实路径，因此两种输入形态都能让恢复和语料库作用域继续正常工作：目录会被读作检出目录的容器，什么都不会被拉取；文件则会被读作清单，其中每一条都会被克隆。

`sample_id` 派生自仓库自身的身份而非路径，因此同一个仓库无论是经由清单还是经由目录抵达，都是同一个样本，重新运行也会保留它的结果。

### `semgrep_scanner`

有两个配置项决定扫描什么，它们也正是让同一个扫描器能服务于两条内置流水线的原因：

| 字段 | 默认值 | 含义 |
|-------|---------|---------|
| `target_dir` | `decompiled` | 样本自身工作目录下要扫描的子目录。把它设为 `""`，则改为扫描样本自身的路径。 |
| `extensions` | `.c`, `.h`, `.cpp`, `.py` | 哪些文件会被交给 semgrep。 |

默认值适合先反编译、再在每个样本旁写出 C 代码的流水线。若某条流水线的样本本身就是源码，例如一个仓库检出，则应设置 `target_dir: ""`，并把 `extensions` 放宽到它实际摄取的那些扩展名。

`extensions` 必须与规则保持一致。扩展名未被列出的文件永远不会被交给 semgrep，无论有多少条规则本可以匹配它，而且这种失效是无声的：扫描报告零发现，这与一棵干净的代码树无法区分。这正是源代码审计流水线要在 `finding_count` 之外一并记录 `files_scanned` 的原因。

样本是分批扫描的 (`batch_size`，默认 200)，而不是一次性扫完，这样某一批超时或返回无法读取的结果时，只会赔上它自己那些样本，而不是在工作已经做完之后丢弃整个语料库的结果。
