---
layout: default
title: 内置流水线
order: 3
---

## 内置流水线

DeepZero 自带两条完整的流水线。它们既是拿来直接运行的，也是拿来阅读的：当一份流水线定义真的在做实事时，它长什么样。

| 流水线 | 语料库 | 它在找什么 |
|----------|--------|-------------------|
| `pipelines/loldrivers` | 磁盘上的 Windows 内核驱动程序 | BYOVD 候选目标：无需硬件即可触及的 IOCTL 攻击面 |
| `pipelines/source_audit` | Git 仓库 | 可从不可信输入触及的源码级漏洞 |

两者都声明了 `model: claude-code/claude-opus-5`，因此它们跑在 Claude Code 订阅上，无需 API 密钥。用 `-m` 可以改用任意 LiteLLM 模型。参阅 [选择模型]({{ '/zh-CN/reference/pipeline-yaml.html' | relative_url }})。

---

## LOLDrivers 流水线

我们在 `pipelines/loldrivers/` 中维护了一个 BYOVD（自带易受攻击驱动程序，Bring Your Own Vulnerable Driver）参考流水线。

| 阶段 | 处理器 | 它做什么 |
|-------|-----------|--------------|
| `discover` | `pe_ingest/pe_ingest.py` | PE 文件摄取和 LIEF 头解析 |
| `kernel_filter` | `metadata_filter` | 约束为暴露了 IOCTL 攻击面的内核态驱动程序，并按哈希去重 |
| `loldrivers_filter` | `loldrivers_filter/loldrivers_filter.py` | 排除 loldrivers.io 目录中已知的实体 |
| `decompile` | `ghidra_decompile/ghidra_decompile.py` | 执行 Ghidra 无头反编译 |
| `semgrep_scanner` | `semgrep_scanner/semgrep_scanner.py` | 针对导出的 C 源码进行大规模静态分析 |
| `rank_by_findings` | `top_k` | 把每个存活下来的驱动程序按发现数量排序，最差的排在最前 |
| `assess` | `generic_llm` | 为每个驱动程序渲染 `assessment.j2` 并记录裁决 |

排序阶段保留全部样本 (`keep_top: 0`)，只改变顺序。这是刻意为之：只留下头部一档能省下评估调用，但那等于用发现数量来决定哪些驱动程序值得一读，而这恰恰是评估阶段存在的意义所在。按最差优先排序，同样让那些驱动程序最先被看到，却没有把其余的丢掉，而且提前停止的运行也已经把时间花在了噪音最大的驱动程序上。

排除类阶段放在反编译之前，理由反过来也是同一个：Ghidra 是迄今为止最昂贵的阶段，因此每一个被廉价的头部检查或哈希查询剔除掉的驱动程序，都是省下来的几分钟。

### 一个发现能否在没有硬件的情况下被触发

许多驱动程序只有在自己的硬件被枚举之后才会创建设备对象。在没有该设备的机器或虚拟机上，`\.\<name>` 永远打不开，驱动程序暴露的一切也就都触及不到，而仅凭报告本身，这与该驱动程序并不存在漏洞是无法区分的。

`decompile` 阶段会记录设备对象是在哪里创建的：

| 取值 | 含义 |
|-------|---------|
| `device_created_in` | 调用 `IoCreateDevice` 的那个函数 |
| `device_on_load_path` | 该函数是否为 `DriverEntry`，或者是被它调用的函数 |

`device_on_load_path: true` 表示只要机器会加载这个驱动程序，设备就会出现，因此针对它的发现今天就能确认。`false` 表示设备是在别处创建的，通常是 PnP 的 add-device 或 start-device 回调，要确认任何事情都需要物理设备。当根本找不到 `IoCreateDevice` 时，这两项都不会被记录，而不是去猜测。

内置流水线在 `report.columns` 下列出了 `decompile.device_on_load_path`，因此它会显示在每个驱动程序旁边。做到这一点只需如此：该取值在处理器的 `provides` 中声明，并由流水线指定，而报告始终不知道设备对象是什么。

### 反编译为每个驱动程序写出什么

`decompile` 阶段会写入每个样本的 `decompiled/` 目录：

| 文件 | 内容 |
|------|------|
| `dispatch_ioctl.c` | 分发例程，只记录一次 |
| `ioctls/0xXXXXXXXX.c` | 每个 IOCTL 码一个：该码解码后的含义，并指向上面那个例程 |
| `ghidra_result.json` | 元数据：设备名、符号链接、分发函数名，以及每个 IOCTL 码一条记录 |

一个驱动程序中的每个码都由同一个例程处理，因此该例程只存储一次并被引用，绝不会按码复制。`ioctl_handlers` 中的一条记录只保存该码及其解码后的字段 (`hex`, `device_type`, `function`, `method`, `access`)。

体积值得留意，因为这里的故障模式是无声的：输出看上去依然正确，只是变得极其庞大。作为参照，一个包含 1,388 个已反编译驱动程序的驱动包，其全部 `ghidra_result.json` 合计约为 **28 MB**。改为按码存储该例程，同一语料库会产生 **734 MB**，其中单个驱动程序达到 52 MB。若某次阶段运行的输出比这个量级高出许多，就说明它退化成了重复存放例程，而评估阶段在构造提示词时还会为每个驱动程序解析那份文档。

`tests/test_extract_dispatch.py` 直接守护着这些记录的形态。

### 前置条件

- Ghidra，并已设置 `GHIDRA_INSTALL_DIR`。如果存在 `JAVA_HOME` 也会被读取。
- PATH 上的 `semgrep`：`pip install semgrep`。

---

## 源代码审计流水线

这是一条针对 git 仓库的源代码审计流水线，位于 `pipelines/source_audit/`。每个仓库都取其某一个修订版本，用 semgrep 扫描，然后交给模型阅读，模型的任务是把真实漏洞与只是匹配上了代码形态的规则区分开。

| 阶段 | 处理器 | 它做什么 |
|-------|-----------|--------------|
| `discover` | `git_ingest/git_ingest.py` | 以深度 1 克隆每个仓库，或读取磁盘上已有的检出目录，并记录下游一切所评判的那个修订版本 |
| `size_filter` | `metadata_filter` | 丢弃其中没有源码的检出目录，以及大到不值得扫描的代码树；通过两个名称到达的同一个提交只扫描一次 |
| `scan` | `semgrep_scanner/semgrep_scanner.py` | 对每个检出目录运行 `rules/`。没有任何命中的仓库到此为止 |
| `rank` | `top_k` | 把每个存活下来的仓库按发现数量排序，最差的排在最前，一个也不丢弃 |
| `assess` | `generic_llm` | 为每个仓库渲染 `assessment.j2` 并记录裁决 |

这两半的先后顺序很重要。Semgrep 廉价，并且能找出每一个值得一看的地方；而其中几乎所有地方其实都没问题。评估阶段才是让一条发现要么获得一条从攻击者输入到危险汇点的路径，要么被指名道姓地判定为不可达的地方。

### 该把它指向什么

`deepzero run` 只接受一个目标，而摄取阶段两种形态都读得懂：

- **一个目录**，其中每个直接子目录都是一个检出。什么都不会被拉取，因此私有代码永远不必离开它已经所在的那台机器。若目录本身就是一个检出，则被当作单个仓库读取；没有 `.git` 的纯源码目录同样会被读取，只是它没有修订版本或来源可供报告。
- **一个文件**，被当作待克隆仓库的清单读取。可以是纯文本，每行一个，支持 `#` 注释；也可以是 YAML，形式为一个列表，或一个带 `repos:` 键的映射，其条目可以固定某个 ref。

```bash
# 审计清单文件中列出的仓库
deepzero run repos.txt -p pipelines/source_audit/pipeline.yaml

# 或者一个存放了已在磁盘上的检出目录的目录
deepzero run C:\code\vendor -p pipelines/source_audit/pipeline.yaml
```

克隆结果存放在摄取阶段自己的缓存目录中，而不是工作目录中，因此重新运行不产生网络开销，`--clean` 也不会把它们丢掉。

### 规则与语言

`rules/` 中有 136 条 semgrep 规则，覆盖 Python、JavaScript、TypeScript、Go、Java、Ruby、PHP 和 C#，并按它们要找的东西分组：注入、路径穿越与 SSRF、认证与授权、加密与密钥、反序列化，以及 XSS 与响应头。

有三个地方必须彼此一致：规则、`discover` 上的 `extensions` 列表，以及 `scan` 上与之相同的列表。它们的失效方向恰好相反。列表遗漏的扩展名既不会被计数也不会被扫描，于是该仓库看上去比实际更小、更干净。而列表中带有、却没有任何规则覆盖的扩展名，会被遍历、计数并送去参加一次永远不可能匹配的扫描。新增一门语言意味着三处都要改，`tests/test_source_audit_pipeline.py` 会在它们发生偏离时失败。

因此，一个用 `rules/` 未覆盖的语言编写的仓库，其源文件数会是零，并被 `size_filter` 丢弃。这读起来像是“没有源码”，而实际含义是“这里没有本流水线能审计的东西”，但它仍然是值得的结果：该代码树在克隆之后的下一个阶段就被丢弃，而不是被送去参加一次规则永远无法触发的扫描。

### 阅读它的报告

这条流水线声明了属于自己的词汇，因为一个仓库并不是磁盘上的一个文件：

```yaml
report:
  title: Source repository audit
  entity: repository
  entity_plural: repositories
  target_label: organisation
  vulnerable_when: [vulnerable]
  safe_when: [not exploitable]
```

`vulnerable_when` 被收窄是有一个值得知道的原因的。评估的回答是 `[VULNERABLE]` 或 `[NOT EXPLOITABLE]`，而默认的肯定项列表中含有 `exploitab`，否定裁决里恰好就有它。参阅 [裁决如何匹配]({{ '/zh-CN/reference/pipeline-yaml.html' | relative_url }})。

它的 `columns` 会在每个仓库旁边放上发现数量、已扫描文件数、源文件数、主要语言和修订版本。已扫描文件数值得占据一席之地：一个没有发现的仓库，和一个 semgrep 根本没打开过其文件的仓库，都显示为零发现，而其中只有一个算是结果。

### 前置条件

- PATH 上的 `git`，供 `discover` 阶段使用。
- PATH 上的 `semgrep`：`pip install semgrep`。

在投入一次长时间运行之前，对任一条流水线都可以把上述内容全部检查一遍：

```bash
deepzero validate pipelines/source_audit/pipeline.yaml
```
