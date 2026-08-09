---
layout: default
title: 流水线 YAML
order: 2
---

## 流水线配置

DeepZero 中的 **流水线 (Pipeline)** 是一个声明式的执行图，定义了一个连续的、高弹性的数据转换过程。它将原始物理数据集转化为高信号的分析数据集。

流水线架构在 YAML 中有着严格定义。DeepZero 动态解析配置，原生支持 Shell 变量展开 (例如，`${VAR:-default}`)。

### 配置架构

```yaml
name: my_pipeline
description: 标准漏洞研究流水线
version: "1.0"
model: openai/gpt-4o  # 由 scheme 选择后端，详见下文

settings:
  work_dir: work
  max_workers: 8  # ThreadPoolExecutor 线程数的全局上限

stages:
  # 阶段 1: 必须是一个 IngestProcessor (摄取处理器)
  - name: discover
    processor: file_discovery
    config:
      extensions: ["*"]

  # 阶段 2: 同步过滤器
  - name: filter
    processor: metadata_filter
    config:
      require:
        is_executable: true

  # 阶段 3: 高延迟 Map 处理
  - name: decompile
    processor: ghidra_decompile/ghidra_decompile.py
    parallel: 4           # 将并行映射并发数限制为 4 个并发的 Ghidra JVM
    timeout: 300          # 强制通过 process.py 为每个样本设置 300 秒的严格终止倒计时
    on_failure: skip      # 发生异常时静默处理而不是终止 (skip, retry, abort)
    max_retries: 2        # 重试逻辑的执行限制
    config:
      ghidra_install_dir: ${GHIDRA_INSTALL_DIR}
```

### 阶段选项

定义在 `stages:` 数组下的每个阶段都接受以下属性：

| 字段 | 类型 | 默认值 | 描述 |
|-------|------|---------|-------------|
| `name` | 字符串 | `stage_N` | 流水线内的唯一阶段名称 |
| `processor` | 字符串 | 必须 | 处理器引用 (见下文) |
| `config` | 字典 | `{}` | 处理器特定配置 |
| `parallel` | 整数 | `4` | Map 处理器的并发数。`0` 表示自动缩放为 `os.cpu_count()` |
| `timeout` | 整数 | `0` | 每个样本的超时时间（秒，0 = 无超时） |
| `on_failure` | 字符串 | `skip` | 定义容错行为：`skip` (跳过), `retry` (重试), 或 `abort` (终止) |
| `max_retries` | 整数 | `0` | 当设置了 `on_failure: retry` 时的重试次数 |

### 顶层字段

| 字段 | 类型 | 默认值 | 描述 |
|-------|------|---------|-------------|
| `name` | 字符串 | 流水线目录的名称 | 为流水线命名，同时也为它的工作目录命名 |
| `description` | 字符串 | `""` | 自由文本 |
| `model` | 字符串 | `""` | 供每个 LLM 阶段使用的模型。没有 LLM 阶段的流水线无需设置；缺失时 `deepzero validate` 会给出警告 |
| `settings` | 字典 | `{}` | `work_dir` (默认 `work`) 和 `max_workers` (默认 `min(4, cpu_count)`) |
| `knowledge` | 字典 | `{}` | 任意的流水线级别取值，任何处理器都可通过 `ctx.get_knowledge(key)` 读取 |
| `report` | 字典 | `{}` | `deepzero report` 如何呈现这条流水线的结果，详见下文 |
| `stages` | 列表 | 必须 | 至少一个，且第一个必须是摄取处理器 |

`work_dir` 是根目录，而不是运行目录。一次运行落在 `<work_dir>/<pipeline name>/<corpus key>/` 下，其中语料库键由目标路径派生而来，因此经由同一条流水线处理的两个语料库绝不会互相冲突，各自独立恢复。参阅 [CLI 参考]({{ '/zh-CN/reference/cli.html' | relative_url }})。

### 选择模型

`model` 中第一个 `/` 之前的部分是一个 scheme，它决定使用哪个后端：

| 模型字符串 | 后端 |
|--------------|---------|
| `claude-code`, `claude-code/<model-id>` | 本机已安装并已登录的 Claude Code CLI |
| 其他任意值，例如 `openai/gpt-4o`, `gemini/...`, `gpt-4o` | LiteLLM，覆盖它所支持的每一个需要 API 密钥的端点 |

`claude-code` 让流水线跑在 Claude Code 订阅上，完全不需要 API 密钥。DeepZero 从不为它经手任何凭据：它调用的是你已经登录过的那个 CLI，并沿用该可执行文件已有的认证。斜杠之后的部分会作为模型原样传递，因此 `claude-code/claude-opus-5` 指定了一个具体模型，而单独的 `claude-code` 则让该 CLI 保持它的默认模型。两条内置流水线都声明了 `claude-code` 模型，`-m` 可以为单次运行覆盖它。

由于这些调用携带的是不可信内容，即反编译器的输出以及从陌生人仓库中拉取的源代码，调用该 CLI 时会禁用它的工具和 MCP 服务器。补全本身并不需要它们，而放任它们启用会让一段被注入的提示词得以触及 shell。

这个注册表是开放的：`register_backend()` 无需修改 DeepZero 即可添加一个 scheme，提供方、流水线和各阶段都不需要为新增后端做任何改动。任何没有后端认领的 scheme 都会回落到 LiteLLM。

无论选中哪个后端，在某个阶段真正需要它之前，系统都会先问它能否运行：对 LiteLLM 模型，`deepzero validate` 检查 API 密钥；对 agent CLI，则检查该可执行文件是否存在；而 [`deepzero run --preflight`]({{ '/zh-CN/reference/cli.html' | relative_url }}) 更进一步，确认该 CLI 确实已登录。

### 解析逻辑 (`engine/registry.py`)

`processor:` 取值的形态决定了它如何被解析，因此一个引用在外部文件和内置名称之间绝不会产生歧义：

| 引用 | 解析为 |
|-----------|-------------|
| 含有 `/` 或 `\`，例如 `ghidra_decompile/ghidra_decompile.py` | 工作目录下 `processors/` 中的一个文件。使用其中第一个 Processor 子类，基类本身会被忽略 |
| 同上，但追加了 `:ClassName` | 该文件中的那个特定类，一个文件定义了多个处理器时需要这样写 |
| 裸名称，例如 `metadata_filter` | 内部注册表，其内容在 `stages/__init__.py` 中填充 |
| 含有 `:` 的裸名称，例如 `my.python.module:MyClass` | `sys.path` 上的一个可导入模块，以及其中的一个类 |

其他任何形态都会报错并列出内置名称，而不是在运行到一半时才失败。注意外部路径是相对于工作目录解析的，而不是相对于流水线目录，这也正是内置流水线要从仓库根目录运行的原因。

### 动态展开

在架构验证绑定处理器之前，DeepZero 会遍历整个 YAML DOM 树，匹配 `\$\{([^}]+)\}` 正则表达式。环境变量决定了最终解析的运行时配置。这明确避免了在已提交的 `.yaml` 流水线中硬编码 API 密钥或安装目录。

### 提示词可用的取值

`config` 中带有 `prompt` 的阶段，会把那个文件当作 Jinja 模板来渲染。该取值可以是一个路径，也可以是与流水线放在一起的一个文件名；无论哪种形式，都是去加载那个文件，而绝不会把它本身当作提示词正文。

每一份提示词都可以使用下列取值：

| 取值 | 类型 | 描述 |
|-------|------|-------------|
| `sample_name` | 字符串 | 摄取阶段记录下来的样本文件名 |
| `sample_path` | 字符串 | 样本在磁盘上的绝对路径 |
| `history` | 字典 | 对每个已经运行过的阶段给出 `{stage_name: data}` |
| `config` | 字典 | 本阶段自己的 `config` 块 |

除此之外，提示词还可以使用它 **之前** 各阶段所记录的一切。每个处理器在自己的 `provides` 属性中声明这些名称，它们分为两类：

- **数据键**：处理器放进 `data` 的任何内容，例如 `device_name` 或 `finding_count`。既可以按该名称直接使用，也可以通过 `history` 访问。
- **产物**：处理器写出的文件，通过把它的路径分隔符和扩展名一并折进名称来引用。`decompiled/dispatch_ioctl.c` 会变成 `decompiled_dispatch_ioctl_c`。JSON 会被解析成对象；`.c`、`.h`、`.txt`、`.md`、`.py`、`.yaml` 和 `.yml` 会以文本形式送达。其他文件类型不会暴露出来。超出上下文预算的内容会被截断，而过大的 JSON 会被跳过并给出警告，而不是去解析它。

某个取值只对记录它的那个阶段 *之后* 的阶段可用，因此提示词无法触及它自己所在阶段的输出。

要查看某条流水线提供了哪些取值，执行：

```bash
deepzero validate <pipeline>
```

如果提示词引用了任何先前阶段都不产出的名称，会被报告为错误，并列出当时实际可用的名称；同一项检查在运行中被触及时也会让运行失败。这一点很重要，因为一个未知的名称本来会渲染成空：模型将被要求去评判一份空载荷，而给回来的裁决会显得自信却毫无意义。

### 报告块

`deepzero report` 建立在引擎所保证的东西之上，而这些东西对每条流水线都是相同的：每个阶段都记录 `data`、`artifacts` 和一个状态。不同的是词汇。一条内核驱动程序流水线、一次源代码审计和一次许可证排查，产出的结果形态相同，称呼却截然不同。

所以形态是固定的，而词汇是声明出来的：

```yaml
report:
  title: Source repository audit
  entity: repository
  entity_plural: repositories
  target_label: organisation
  classification_key: classification
  positive_when: [vulnerable]
  negative_when: [not exploitable]
  columns:
    - scan.finding_count
    - discover.primary_language
  findings_files: [findings.json]
```

每个字段都是可选的，而且每个默认值都复现了这个块出现之前流水线原本的行为。什么都不声明的流水线依然能得到一份可用的报告。

| 字段 | 类型 | 默认值 | 描述 |
|-------|------|---------|-------------|
| `title` | 字符串 | `<pipeline name> results` | `index.html` 的标题 |
| `entity` | 字符串 | `sample` | 界面中如何称呼单个结果 |
| `entity_plural` | 字符串 | `entity` + `s` | 仅在加 s 不正确时需要，例如 repository |
| `target_label` | 字符串 | `corpus` | 本次运行所指向的对象叫什么 |
| `classification_key` | 字符串 | `classification` | 存放结论的那个阶段 `data` 键 |
| `positive_when` | 列表 | `vulnerab`, `exploitab`, `confirmed` | 被计为“你要找的东西”的取值 |
| `negative_when` | 列表 | `safe`, `not vulnerab`, `benign`, `clean` | 被计为“未发现问题”的取值 |
| `columns` | 列表 | 自动挑选 | 在每个结果旁展示的 `stage.key` 取值 |
| `findings_files` | 列表 | `findings.json` | 样本目录中用于读取发现的文件名 |
| `lexicon` | 字典 | 见下文 | 各类结果所使用的词汇 |

`vulnerable_when` 和 `safe_when` 作为 `positive_when` 与 `negative_when` 的旧名称同样被接受，含义完全一致。两者都给出时以 `positive_when` 为准。

`target_label` 之所以值得存在，是因为默认值“corpus”预设了磁盘上的一堆文件。针对在线应用的运行有一个范围，针对某个组织仓库的运行有一个组织，把两者中的任何一个叫作语料库，在别人打开的报告里都会读起来像个错误。

#### 裁决如何匹配

`classification_key` 下记录的取值会被转成小写，先用 `positive_when` 中的子串去检验，再用 `negative_when` 中的。是子串而不是完整取值，因此 `vulnerab` 能同时覆盖 “vulnerable” 和 “vulnerability”。

先检验肯定项，正是默认值值得被覆盖的原因。若某条流水线的否定裁决是 `[NOT EXPLOITABLE]`，其中含有 `exploitab`，而它是一个默认的肯定项，于是它会被计为一次命中。把 `positive_when` 收窄为 `[vulnerable]` 正是内置的源代码审计所做的，而当一次运行自己的裁决与报告的计数对不上时，这也是首先该检查的地方。

两个列表都不匹配的裁决不会被悄悄丢弃。它会落到“裁决不明”一类，这与被判定为安全是完全不同的说法。

#### 列

`columns` 使用本流水线中的阶段名来指定 `stage.key` 取值，并把每一项放在每个结果旁边。请声明那些决定你接下来读什么的取值：一个发现究竟能不能被实际触发、实际扫描了多少代码、评判的是哪个修订版本。什么都不声明时，报告会从本次运行记录的内容中挑选至多六个数值型或名称值得关注的键。

为此无需给报告添加任何东西。只要某个处理器把一个键记进了 `data`，并且流水线在这里指定了它，它就可用了。

#### 发现

`findings_files` 指定每个样本目录内用于读取发现的文件。任何内容看起来像发现列表的 JSON 产物同样会被采纳，因此以其他名称写出的处理器无需配置也能显示出来。

#### 词汇表

报告有三个固定的分组：一个装你正在寻找的东西，一个装尚无定论的发现，还有一个装完整分析过、未标记任何问题的结果。这些是结构性的。只有它们的名称属于你：

| 字段 | 默认值 | 出现位置 |
|-------|---------|------------------|
| `discipline` | `vulnerability research` | 页眉中产品名旁边 |
| `positive` | `Vulnerable` | 该分组的标签及其筛选项 |
| `positive_help` | `an assessment stage concluded these are vulnerable` | 该标签旁展示的说明 |
| `positive_phrase` | `assessed as vulnerable` | 补全摘要行中的“12 repositories ...” |
| `nothing_positive` | `Nothing was confirmed vulnerable` | 本次运行没有找到任何可行动项时的大标题 |
| `unconfirmed` | `Needs assessment` | 存在发现，但没有评估对它们下过定论 |
| `negative` | `Clear` | 完整分析过，未标记任何问题 |

其余的结果类别由引擎命名，不可配置，因为它们描述的是引擎做了什么，而不是流水线在找什么：“Errored”、“Ran out of time”、“Unclear verdict” 和 “Filtered out”。

正是这一点让这个工具走出了漏洞研究的范围。一条审计依赖许可证的流水线有着同样的三类结果，却没有一个默认词汇适用于它，于是它自己说明它们是什么：

```yaml
report:
  entity: package
  target_label: dependency tree
  classification_key: licence_status
  positive_when: [incompatible]
  negative_when: [compatible]
  lexicon:
    discipline: licence compliance
    positive: Incompatible
    positive_help: the declared licence conflicts with this project's
    positive_phrase: carry an incompatible licence
    nothing_positive: No incompatible licences were found
    unconfirmed: Needs a decision
    negative: Compatible
```

其他一切都不变。报告依旧和为驱动程序狩猎时完全一样地排序、筛选、分组和导出，因为这些从来都不依赖于本次运行是关于什么的。

### 审阅标记

流水线记录的是它自己得出的结论。是否真的有人核查过这个结论，则是另一项主张，而且只有读者能作出，因此报告承载了他们在阅读时添加的标记。

在任意结果的页面上有三种标记：

| 标记 | 含义 |
|------|-------|
| **confirmed** | 核查过，并且成立 |
| **did not hold up** | 核查过，并且不成立。这是一件有确定答案的、已完成的工作 |
| **outstanding** | 看过了，但还有东西尚未证实 |

后两种会打开一个备注框，用于写下你运行了什么、针对什么运行的、结果如何，好让别人能重复这次尝试。什么算作 outstanding 由读者自行决定：复现一次崩溃、证明一个前置条件、读一份 diff，因为在报告这一侧它们都是同一种形态的未竟工作。

标记会显示在索引页每一行旁边，并且可以据此筛选，其中包括 **Unreviewed**，也就是还没有人看过的那些结果。摘要会分别统计它们，于是一次运行可以按“实际已知的内容”来读，而不只是按“被声称的内容”来读：一个没有站住脚的结果，绝不会被误当成没人查看过的结果。

报告是一个文件，所以标记存放在浏览器里。**Export marks** 会把它们导出为 `marks.json`；把该文件保存到 `index.html` 旁边，它们就成为报告的一部分：对任何打开报告的人都会渲染出来，并会以 `review` 和 `review_note` 两列进入 `inventory.csv`。标记是按流水线和目标而非按文件路径来索引的，因此对同一语料库重新运行会保留它们。
