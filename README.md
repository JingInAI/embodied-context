# 给具身智能 agent 准备任务上下文

这套工具帮助 agent 弄清楚：**现在要完成什么、已有资料说明了什么、之前实际做过什么、还缺什么信息，以及答案应满足哪些要求。** 它把这些内容整理成后续程序能继续处理的数据，也可以生成供语言模型或多模态模型使用的文字和媒体清单。

这里的“上下文”（context），就是交给 agent、帮助它完成当前任务的信息。任务可以是机器人操作，也可以是看图、理解视频、回答具身推理问题；不要求每个任务都带机器人或仿真器。

新版提供 **10 个可以单独使用的组件**，以及 **11 项具身评测的数据转换工具**。需要哪个组件就调用哪个。例如，只检查答案格式时可以只用“答案要求”；计算相机投影时可以只用“位置与空间”，无需先运行其他九个组件。

它负责准备信息。连接机器人或仿真环境、执行动作、调用任务策略、运行评测和给 agent 发送消息，由接入它的外部系统负责。本文将这个外部系统简称为“调用方”。组件可以调用由调用方明确提供的信息处理工具，但不直接与机器人或仿真环境通信。

**项目根目录约定**

本文的“项目根目录”是包含 `pyproject.toml`、`README.md` 和 `context_components/` 的组件仓库根目录。在当前工作区中，它是：

```bash
cd /root/rivermind-data/project/AgentTest-An/tmp/context_modules/scripts_v1
```

它不是上一层 `context_modules/`，也不是 `AgentTest-An/`。如果从 GitHub 克隆，根目录通常名为 `embodied-context/`。除首次克隆和进入目录外，后文所有命令、Python 示例和相对文件路径均以这个根目录为基准。

**安装**

需要 Python 3.10 或更新版本。核心依赖只有 `jsonschema` 和 `referencing`，安装时由 pip 处理；不需要先安装机器人仿真器、模型或 GPU 依赖。

如果还没有仓库，先在准备存放项目的位置克隆，并进入仓库根目录；已有当前工作区时跳过这一步：

```bash
git clone --branch master https://github.com/JingInAI/embodied-context.git
cd embodied-context
```

在根目录创建并激活 Python 环境。已有运行调用方的 Conda 或虚拟环境时，直接激活那个环境即可，不必再创建一个：

```bash
python3 -m venv .venv
source .venv/bin/activate
```

随后安装根目录中的项目：

```bash
python -m pip install .
```

如果需要修改源码并立即使用修改后的版本，可以改用可编辑安装：

```bash
python -m pip install -e .
```

两种安装方式任选一种。组件需要安装到**调用它的程序使用的同一个 Python 环境**；例如由宿主机上的 AgentTest 调用，就安装到宿主机的 AgentTest 环境中。

验证安装和命令入口：

```bash
python -m pip show embodied-context-components
python -B -c 'import sys, context_components; print(sys.executable); print(context_components.__file__)'
python -B -m context_components --help
embodied-context --help
```

安装后无需设置 `PYTHONPATH`。在源码根目录执行 `python -m context_components` 时，Python 会优先使用当前目录的源码；因此，导入位置可能指向本项目，而不是 `site-packages`，这是正常现象。`pip show` 用于确认当前环境确实存在安装记录。

如果只想将 GitHub `master` 作为其他程序的依赖，也可以直接安装远端来源，无需另存源码仓库：

```bash
python -m pip install --upgrade --force-reinstall \
  "embodied-context-components @ git+https://github.com/JingInAI/embodied-context.git@master"
```

此方式还需要 Git 和访问 GitHub、包源的网络连接。`--force-reinstall` 确保同版本的旧本地安装也被替换。远端安装只能获得已经推送到 GitHub 的内容；验证本地尚未推送的改动应使用 `python -m pip install .` 或可编辑安装。远端分支会变化，复现实验时应记录实际提交号：

```bash
python -B -c 'from importlib.metadata import distribution; print(distribution("embodied-context-components").read_text("direct_url.json"))'
```

通过 Git URL 安装时，该记录包含仓库地址、请求的 `master` 分支和实际 `commit_id`；本地安装时记录的是本地来源。

**目录怎么分工**

| 位置 | 用途 |
| --- | --- |
| `context_components/` | 实际运行的组件代码、输入输出规则和已生成的评测目录。 |
| `pyproject.toml` | 安装配置；安装包不包含研究资料、测试或样例。 |
| `README.md` | 使用说明。 |
| `tmp/tests/` | 组件、适配器、集成和渲染功能的全部离线回归测试。 |
| `tmp/` | `v1` 分支中的开发与维护资料，包括研究快照、流程图、样例、测试和历史验收记录；当前 `master` 不包含该目录。 |

正常安装和下面的入门示例均不依赖 `tmp/`。历史资料可在 [v1 分支](https://github.com/JingInAI/embodied-context/tree/v1/tmp) 查看，包括 [执行流程图 PNG](https://github.com/JingInAI/embodied-context/blob/v1/tmp/pipeline/scripts_v1_execution_flow.png)、[SVG](https://github.com/JingInAI/embodied-context/blob/v1/tmp/pipeline/scripts_v1_execution_flow.svg) 和 [维护资料说明](https://github.com/JingInAI/embodied-context/blob/v1/tmp/README.md)。`v1` 已合入本次 `master` 更新；其中的历史报告仍只对应报告生成时的代码。

**先运行一个例子**

以下示例直接从标准输入读取请求，无需准备示例文件。从项目根目录执行，即可生成一份完整的任务上下文 JSON：

```bash
python -B -m context_components task_context --format json <<'JSON'
{
  "schema_version": "context.v1",
  "scope": {
    "run_id": "example", "task_id": "custom-task",
    "epoch_id": "scene-1", "turn_index": 0
  },
  "input": {
    "task": {"text": "Explain the order of the observed events.", "kind": "reasoning"}
  }
}
JSON
```

再看一个几何示例：计算同一坐标系中两个点的距离，输出英文说明和 JSON：

```bash
python -B -m context_components spatial_context \
  --format text --content-format text_json <<'JSON'
{
  "schema_version": "context.v1",
  "scope": {
    "run_id": "example", "task_id": "distance-question",
    "epoch_id": "scene-1", "turn_index": 0
  },
  "input": {
    "frames": [{"id": "map", "length_unit": "m", "handedness": "right"}],
    "queries": [{
      "id": "separation", "kind": "distance", "frame_id": "map",
      "point_a": [0, 0, 0], "point_b": [3, 4, 0]
    }]
  }
}
JSON
```

距离结果为 `5.0 m`。这些示例不调用模型、机器人或仿真器。安装后的 `embodied-context` 与 `python -m context_components` 是同一入口。

使用文件输入时，`--input request.json` 表示根目录下的 `request.json`，不是 `scripts_v1/request.json`；输出文件路径也遵循同一规则。不要在根目录运行命令时再添加 `scripts_v1/` 前缀。需要在其他目录调用时，应传入相对于那个目录的路径或绝对路径。

**十个组件分别有什么用**

下表中的英文名称是实际调用时使用的组件名。中文名称解释用途。

| 想了解什么 | 使用哪个组件 | 需要提供什么 | 能得到什么 |
| --- | --- | --- | --- |
| 任务要做什么、进展到哪里 | 任务与进度 `task_context` | 原任务，可选目标、完成条件、当前事实 | 任务要求、目标依赖、进度依据和当前关注点 |
| 当前有哪些线索、之前发生过什么 | 观测与记忆 `observation_context` | 文字或媒体记录、已提取的线索、事件，可选历史 | 整理后的线索、事件修订、撤销和已接收事件的计数 |
| 位置、距离、相机画面之间怎样对应 | 位置与空间 `spatial_context` | 坐标、单位、相机参数、坐标转换关系和具体问题 | 投影、反投影、坐标转换、距离和有限几何计算结果 |
| 操作参数是什么意思、有哪些限制 | 操作说明 `interaction_contract` | 外部接口对操作、参数、单位、顺序和范围的定义 | 一份可供 agent 使用的操作说明 |
| 提交的操作究竟执行了多少 | 执行结果 `execution_feedback` | 提交、接受和执行记录，可选执行前后测量 | 各阶段的差别、失败或中断情况、可计算的测量变化 |
| 过去类似操作有什么效果 | 经验与预测 `response_evidence` | 已执行的数值记录、适用条件、变量单位和查询 | 可用证据数量、有限范围内的效果估计、已有候选的比较 |
| 剩余资源还能支持多少工作 | 资源余量 `resource_context` | 余额或期限，可选单位工作成本和待完成工作量 | 可支持的工作量、资源缺口、最小执行窗口是否够用 |
| 有哪些资料、是否真的能读到 | 资料与来源 `evidence_context` | 允许访问的资料清单，可选读取检查 | 资料索引、定位信息及读取验证结果 |
| 有哪些处理工具、上次调用怎样了 | 工具与反馈 `tool_context` | 工具说明，可选调用记录和结果引用 | 工具能力、输入输出要求、成功或失败信息 |
| 答案该怎么写、是否符合要求 | 答案要求 `output_contract` | 外部给出的答案规则，可选待检查答案 | 交付要求，以及每项规则的检查结果 |

**任务与进度：依据已有事实判断，不替调用方编造目标。** 简单任务只需一段说明。复杂任务可以提供子目标、先后依赖、完成条件和循环结束条件。例如，“先打开柜门，再取出杯子”：只有提供的事实支持“柜门已打开”，才会将对应完成条件标为有依据。缺少证据时保留未知；上游撤销旧事实后，重新判断进度。它不自动生成动作序列，也不凭一次“已经尝试”认定任务完成。

**观测与记忆：整理输入线索，并处理重复、修订和撤销。** 可以直接提供文字、已有的识别结果，或图片、视频等媒体的引用。外部 UTF-8 文本可以按原文读取，包括中文和换行。图片不会自动变成识别结果：需要调用方提供感知工具；没有工具时会说明能力缺失，同时保留媒体引用。工具推断得到的线索标为“估计”，并保留方法和依据。重复收到同一事件不会重复计数；有新版本时可以更新或撤销旧记录。计数只说明“收到的事件里有多少个”，不保证整个真实世界没有漏报。历史超出容量时会标记记录不完整。

**位置与空间：回答明确的几何问题。** 例如，“这个三维点落在图像哪里”“这个像素对应哪条空间射线”“两个点相距多少”。内置支持无畸变针孔相机、刚体坐标转换，以及点或球体相对球体、平面、轴对齐长方体的间隙计算。只有像素而没有深度或指定平面时，可以得到射线，不能凭空得到唯一的三维点。不同单位、坐标轴方向、旋转表示和采样时间要明确提供；不匹配时返回具体问题。鱼眼等其他相机模型可接入外部处理工具。几何结果不等于机器人一定能到达，也不证明整段运动不会碰撞。

**操作说明：把当前接口的真实含义交给 agent。** 例如，某个数值是关节角还是末端位置、单位是度还是弧度、左右臂的参数如何排列。组件保留调用方提供的定义，不根据数组长度猜测机器人类型，不默认七维控制或固定夹爪，也不调用这些操作。这类信息无需跨轮维护内部状态。

**执行结果：区分“发出了”“收到了”和“做完了”。** 例如，提交 50 项操作，系统接受 50 项，但实际只执行 20 项，就应保留这三种数量，而不是将接受数量当作执行数量。实际数量未知时会明确说明。执行记录可以修订、撤销并在后续轮次继续使用。计算执行前后变化时，测量必须具有明确的对象、单位、所属任务和时间；只有可以对应的测量才有比较意义。

**经验与预测：仅在已有数据支持的范围内估计。** 输入的是实际执行过的操作与对应响应。例如，若干次相似设置下的输入量和实际位移，可以用于估计附近输入量可能对应的位移。组件会检查任务和条件是否匹配、样本是否足够、查询是否落在样本共同支持的范围内；可进一步指定过期时间、旧样本权重和允许的拟合误差。它支持查看证据、估计效果、比较调用方已经给出的候选，不搜索或生成新动作。当前轮次可以没有新记录而复用合法历史；没有足够依据时返回不可用或部分结果，不向数据范围外强行预测。

**资源余量：根据明确成本算“够不够”。** 例如，剩余 10 秒、每项工作需要 3 秒，则最多支持 3 项；如果还要完成 4 项，就报告缺少 1 项的余量。多个资源同时限制工作时，以已能计算的资源中最紧的一个为限。没有成本证据的资源不能据此获得保证。截止时间需要可比较的时钟；秒、次数、内存等不同资源不会自动换算。调用方也可以声明一次工作允许的最大数量和最低数量。组件只计算，不扣账、不调整预算、不安排执行。

**资料与来源：区分“清单里有”和“已经验证能读取”。** 默认输出允许访问的资料索引；只有明确请求读取检查时，才尝试读取并核对。文件内容的大小和摘要会被检查，变化了的内容不能冒充原资料。它不负责理解图片或代替其他组件分析资料。

**工具与反馈：说明工具能做什么，而不是授予执行权限。** 可以列出工具用途、参数要求、返回内容、限制以及已有调用结果。调用记录中的输入和输出资料会随结果保留引用，便于后续追查。可以通过 `request.focus` 指定要展示的工具 ID。真正的信息工具由调用方另外提供；组件内部需要使用工具时，不必先启用这个说明组件。

**答案要求：检查规则，但不替换答案。** 不提供候选答案时，只整理交付要求；提供候选后，可以按 JSON Schema 检查结构、比较解析后的数据是否相等，或比较两个资源的原始字节是否完全相同。结果分为通过、失败、未执行检查，分别对应 `passed`、`failed`、`not_evaluated`。它不会自动填默认值、修补答案或安排重试。布尔 schema `true` 允许任意值，`false` 拒绝任意值。电子邮件等 `format` 检查需要明确启用；无法执行的规则和外部校验报告不会被当作已通过。答案格式正确也不代表任务已经成功。

**一次调用需要什么，会返回什么**

所有组件共用一个小的请求外壳，具体任务数据放在 `input` 中。可以把外壳理解为“这是谁的任务、现在是哪一轮、可以用哪些资料”，把 `input` 理解为“这次要处理什么”。

| 请求字段 | 含义与使用时机 |
| --- | --- |
| `schema_version` | 数据格式版本，目前为 `context.v1`。用于避免不同格式混用。 |
| `scope` | 运行、任务、独立场景和轮次标识。必需 `run_id`、`task_id`、`epoch_id`、`turn_index`；可用 `perspective_id` 区分不同观察范围。 |
| `input` | 当前组件需要的数据，例如任务说明、几何查询或执行记录。 |
| `references` | 本次允许使用的资料清单。可以直接带小段数据，也可以给出由调用方解析的文件或媒体地址。 |
| `history` | 当前组件上一轮已保存的状态；其他组件的结果通过 `upstream` 提供。 |
| `upstream` | 前面组件生成的结果，可直接提供，也可通过资料引用提供。 |
| `bindings` | 本次依赖的配置标识，例如相机标定或控制设置。相关配置变了，旧记录不能直接照用。 |
| `tools` | 本次声明的信息处理工具说明。只有说明而没有调用方提供的实际工具时，不能执行。 |
| `request` | 可选关注点、可用资料范围和长度预算等要求；具体支持方式见下文。 |
| `extensions` | 可选扩展数据。遇到无法识别、但声明为必需的扩展时，会拒绝处理。 |

`epoch_id` 用来区分独立的一次场景或题目。它不要求环境必须有机器人 episode：视频问答可以每题一个标识；机器人重置后换一个标识。`turn_index` 表示对话轮次，不代替真实时间。时间信息另带时钟和单位，不把不同来源的时钟直接相减。

请求会严格检查格式：重复 JSON 键、非有限数值、错误字段和缺失引用会报错；布尔值不当作数字使用。JSON 小数按精确十进制读取，避免输入解析时丢失精度；几何和拟合等数值计算仍有各自的计算精度。输入对象不会被原地修改。

返回结果中的 `content` 是组件整理出的内容，`component` 说明来自哪个组件，`context_id` 标识这份结果，`scope` 说明它属于哪个任务。结果还可能带资料 `references`、问题说明 `issues`、配置标识 `bindings` 和待保存记录 `state_update`。

读取结果时要同时看 `status` 和具体内容：`ready` 表示组件结果已生成，`partial` 表示只有部分内容可用，`unavailable` 表示无法提供所需结果，`not_applicable` 表示不适用。它们都不是任务成功率或答案正确性的评分；例如答案检查组件可以正常生成结果，但其中某项规则检查失败。

**在 Python 中调用**

安装后可以直接运行下面的代码。它先生成任务上下文，再把结果整理成只含文字的交付包；不会调用模型。

```python
from context_components import build_context
from context_components.render import render_context

request = {
    "schema_version": "context.v1",
    "scope": {
        "run_id": "run-1", "task_id": "question-1",
        "epoch_id": "item-1", "turn_index": 0,
    },
    "input": {
        "task": {"text": "解释给定观测中的先后关系。", "kind": "reasoning"}
    },
}
result = build_context("task_context", request)
packet = render_context(result, {
    "receiver_id": "agent", "session_id": "conversation-1",
    "audience": {"modalities": ["text"]},
})
print(packet["blocks"][0]["text"])
```

统一入口是 `build_context(component, request, *, services=None, resolver=None, dispatcher=None)`。每个组件也有自己的入口，例如 `context_components.components.task_context.build_context(request)`，两种用法等价。需要注入工具、资源读取或预算时，可以传入 `Services`；它与单独的 `resolver` / `dispatcher` 参数二选一。

**从文件读取、使用工具，以及限制处理成本**

资源不会因为写了一个路径就自动被读取。调用方需要提供 `FileResolver`，明确允许的根目录和“资源名称 → 根目录内相对路径”的对应关系。读取会拒绝越界路径、符号链接、目录、特殊文件、超出大小限制的文件和读取期间发生变化的文件。URI 资源读取后绑定内容摘要和大小；普通 UTF-8 文本保留原文，JSON 资源支持按 JSON Pointer 读取指定位置。比较原始字节时必须提供字节资源，不能将内联 JSON 冒充文件原文。

信息处理工具通过 `Services.tools` 提供，每个实际工具是 `InformationTool`。请求中的工具 ID、声明能力和实际提供的工具要对应。允许的能力是读取已发布资料、处理数据和写入临时处理产物；不提供机器人或环境通信能力。输入中的字符串不会被当作模块名动态导入或当作代码执行。

观测识别通过 `input.extractors` 选择工具；空间扩展通过 `input.processors={query_id: tool_id}` 为具体查询选择处理器。特殊相机模型还可以用 `parameters_schema_reference_id` 指定参数的格式规则。工具计算的结果要说明方法和依据；视觉推断等估计不冒充直接观测。缺工具、格式错误或超时都会留下可识别的问题。

`Services` 可以设置历史容量 `max_records`、工具调用数 `max_calls`、工具处理字节预算 `max_tool_bytes`、单次工具超时 `timeout_seconds`，以及计数文本长度的 `tokenizers`。一次组合中的工具调用数和处理字节数累计计算；并发调用应各用自己的 Services，或由调用方协调共享计数。超时返回的工具结果会被丢弃，但实际停止进程、限制工具权限和隔离环境，仍由调用方负责；普通 Python 回调本身不是隔离环境。

`request.budget` 可限制组件结果的字节数或 token 数。token 限额必须指明 `tokenizer_id` 并提供对应计数器，因为不同模型的计数规则可能不同。超出预算会明确报错，不偷偷删除任务条件或未知项。渲染阶段还有独立的交付预算：字节限额检查整个交付包，token 限额检查文字块，不估算模型的图像或视频 token 开销。

关注点的作用取决于组件：任务组件用它标明当前关注内容，工具组件用它筛选工具，观测处理器可接收它作为提取提示。它不是一条会自动过滤所有数据的通用搜索指令。`request.language` 等语言字段也不意味着内置自动翻译；当前文字交付主要是可读的结构化内容，不会额外调用模型重写。

**接入十一项评测的数据**

数据适配器的作用是把不同评测的数据整理成上述标准请求。它检查对应版本、任务身份和公开字段，不下载模型、不启动评测环境，也不替调用方采集现场数据。

| 评测与调用名称 | 当前固定目录 | 为这些数据差异做了什么处理 |
| --- | --- | --- |
| LIBERO：`libero` | 5 个套件，共 130 个任务 | 保留套件、任务、相机视角和机器人状态；任务与套件不匹配会拒绝。 |
| LIBERO-Plus：`libero_plus` | 10,030 个变体 | 区分 7 类变化，保留套件内整数编号；标定和实际设置由输入提供，不沿用原版常量。 |
| LIBERO-Pro：`libero_pro` | 967 条任务映射 | 区分 5 类变化及组合，检查对应开关；同名任务在不同映射行仍是不同身份。 |
| Meta-World：`metaworld` | 50 个环境类型 | 支持 8 个 MT/ML 模式、39 维观测；隐藏目标的模式不能夹带未遮蔽的目标坐标。 |
| RoboTwin 2.0：`robotwin2` | 50 个任务模块 | 区分关节和末端控制、多臂参数及可选观测；`joint_action` 按实际状态处理，不当作执行证明。 |
| RoboCasa365：`robocasa365` | 365 个任务导入候选 | 区分原生数组、Gym 字典和 LeRobot 数组的接口身份；365 项任务目录与 317 项数据登记分开。 |
| RoboDojo：`robodojo` | 54 个仿真任务 + 18 个带机器人身份的真机任务 | 保留 5 类能力场景和真机描述，避免不同机器人中的同名任务混用。 |
| RoboCerebra：`robocerebra` | 6 类、共 60 个任务目录 | 使用已公开的任务文字和当前分段，核对类别；不读取后续私有任务文件补全信息。 |
| RoboMME：`robomme` | 16 个任务 | 区分 4 种操作接口和训练/验证/测试划分；保留帧列表、示范标记和公开选项，不伪造相机参数。 |
| NVIDIA Isaac Lab Arena：`isaac_lab_arena` | 20 个代码定义 + 85 个 YAML 环境规格 | 区分固定臂、人形、移动操作和顺序任务；记录来源及生效设置，不执行环境创建函数。 |
| VLABench：`vlabench` | 96 个注册任务 | 区分 6 条策略评测轨道和 6 类视觉语言理解维度；保留公开图像掩码和示例，不转发本题私有答案。 |

这些数字合计 **11,941 条目录身份**，但有的代表任务，有的代表变体、映射行或环境规格，不能当作同粒度任务数或实际运行次数。固定版本、合法模式和目录见 [profiles.json](context_components/adapters/profiles.json)，54 个历史合成模式样例见 [v1 分支中的 adapter-examples.json](https://github.com/JingInAI/embodied-context/blob/v1/tmp/examples/adapter-examples.json)。

下面的代码在项目根目录直接构造一份最小 LIBERO 合成数据，仅演示任务适配，不依赖 `tmp/` 或真实环境。示例从内置目录选择合法身份；真实接入时应使用实际任务和版本，不要为通过检查而替换身份。

```python
from context_components import compose
from context_components.adapters.core import adapt, ExportPolicy, profiles

profile = next(item for item in profiles() if item["adapter"] == "libero")
task_id = next(item for item in profile["catalog"]["task_ids"]
               if item.startswith("libero_object:"))
export = {
    "schema_version": "context.export.v1",
    "scope": {"run_id": "example", "task_id": task_id,
              "epoch_id": "episode-0", "turn_index": 0},
    "profile": {
        "benchmark_revision": profile["benchmark_revision"],
        "export_schema_version": "published-native.v1",
        "wrapper_revision": "example-exporter-v1",
        "resolved_configuration_id": "example-config-v1",
        "mode": "object",
        "task_id": task_id,
    },
    "native": {"instruction": "Inspect the supplied observation before acting."},
    "references": [],
}

# 允许读取哪些字段，由调用方明确决定，不能由待处理数据自己扩大。
policy = ExportPolicy(public_paths=("/instruction",))
adapted = adapt("libero", export, policy=policy, components=["task_context"])
if adapted["issues"]:
    raise ValueError(adapted["issues"])

# 适配只生成计划，调用方再明确执行所选组件。
result = compose(adapted["compose"])
print(result["status"])
```

适配器也有独立入口，例如 `context_components.adapters.robomme.adapt`。默认选择任务和观测两个组件；需要其他组件时通过 `components` 指定。默认计划不会自动建立两个组件的依赖关系，要让任务组件使用观测结果，需要调用方明确添加依赖。

真实接入时，需要先由外部程序导出 `context.export.v1` 格式的数据：

| 字段 | 要说明什么 |
| --- | --- |
| `scope` | 当前是哪次运行、哪个任务、哪个独立场景和哪一轮。 |
| `profile` | 数据来自哪个版本、哪个模式和任务，以及实际使用的设置。 |
| `native` | 已允许公开的任务数据；尽量保留原评测的相机、状态等组织方式。 |
| `references` | 图片、视频、文件等资源如何定位。 |
| `supplements` | 额外组件需要的数据，例如操作定义、现场标定、执行记录、资源和答案规则。 |
| `history` / `request` | 各组件的历史状态及本轮关注点、预算等要求，按需提供。 |

`profile` 必需字段为 `benchmark_revision`、`export_schema_version`、`wrapper_revision`、`resolved_configuration_id`、`mode`、`task_id`，分别说明评测版本、导出格式、导出程序版本、生效设置、模式和任务。这里的导出格式固定为 `published-native.v1`：它是本包约定的数据快照格式，不表示任意原生 Python 对象都能直接传入。任务文字通常放在 `instruction`，RoboCerebra 使用 `desc`；数组和媒体字节由调用方先导出，运行包不导入各评测的仿真或机器学习库。

补充数据要由调用方允许 `/supplements/<组件名>`，且不能覆盖适配器已经映射的原任务或观测字段。缺少必要输入时，适配结果中的 `issues` 会列出缺口；调用方必须检查，不能只拿计划继续执行后便认为所有需求已满足。组件运行后的状态和问题还需另行检查。

外部合作方的 Arena 环境包或其他自定义目录，可通过 `ExportPolicy.catalog` 提供已核实的任务清单，需要明确 `catalog_id`、`benchmark_revision`、`complete` 和 `task_ids`。工具不会自动发现未来版本或把未知版本当作已验证版本。

两处来源差异保留原貌：VLABench 的 `PhysicalLaw` 与 `PhysicsLaw` 均有上游依据，接收时保留实际拼写；RoboCerebra 的数据目录固定到 `4e386b9aa266f05b199739d7b58950252244ea21`。详细来源、提取方式和异常见 v1 分支的 [目录证据](https://github.com/JingInAI/embodied-context/blob/v1/tmp/catalog-evidence.json) 与 [检索记录](https://github.com/JingInAI/embodied-context/blob/v1/tmp/research/lookup.json)。

**按执行、推理或混合任务调整组件**

十个组件现在都支持明确的任务类型。单独调用时，在输入中提供 `"task": {"kind": "execution"}`、`reasoning` 或 `hybrid`；`task_context` 还需要任务 `text`，其他组件只接收共享的 `kind`。组件会在完整 JSON 中记录 `task.kind` 和自己的用途建议，并据此调整英文指导。未声明类型的非任务组件继续使用通用行为，不根据任务文字猜测。

要让类型改变实际计算内容，可以配置 `request.task_variants`。每种类型可提供 `input` 的顶层字段替换和可选 `focus`，例如为执行和推理分别指定空间查询，或者选择不同的已注册工具。组件先选择调用方给出的输入，再计算结果；数组和嵌套对象整体替换，`hybrid` 不自动拼接另外两个分支。仅声明类型不会删除事实或历史执行记录，推理任务仍可用它们分析发生了什么。

组合调用支持顶层 `task.kind`，也能从节点中的明确声明统一传播给全部节点，包括先运行的观测节点。单独调用可从上游结果或历史状态继承类型。类型冲突会返回 `task_kind_mismatch`；配置 variants 却没有可确定的类型会返回 `invalid_request`。11 个适配器会把已有 profile 中的任务类型传给每个选中组件，不要求同时启用任务组件。

可运行的示例和完整规则见 [任务类型使用说明](tmp/task-kind-usage.md) 与 [空间查询示例](tmp/examples/task-kind-spatial.json)。从项目根目录运行：

```bash
python -B -m context_components spatial_context \
  --input tmp/examples/task-kind-spatial.json \
  --format text --content-format text_json
```

标准 JSON 和历史状态中的类型元数据始终保留，和 `json` / `text_json` / `text` 显示形式独立。旧输入继续兼容；固定旧版的严格 JSON 消费端需要同步升级协议，才能接收新增的可选 `task` 元数据。这些新增字段和说明同样计入预算。

**让多个组件合作，并在下一轮继续使用已有记录**

`compose` 接收调用方明确列出的节点和依赖。例如，让“观测与记忆”先整理事实，再让“任务与进度”据此判断完成条件：在后一个节点的 `upstream_nodes` 中写入前一个节点 ID 即可。系统会先检查所有节点的输入格式、身份和依赖是否存在循环，再按依赖顺序串行运行，把上游结果放入下游请求的 `upstream`。

某节点报错或完全不可用时，依赖它的节点会报告上游不可用；独立分支仍可继续。部分可用的上游结果可以继续传递，下游需要按实际内容判断。组合结果保留每个节点的结果或错误，而不是只给一个含糊的成功标志。

需要历史的组件会返回 `state_update`，不会自行写数据库。调用方使用 `common.cas(current, update)` 检查“更新依据的旧状态是否仍是当前状态”，然后在自己的锁或事务中保存返回的新状态。其他过程已修改旧状态时，会报告冲突；调用方应读取最新记录，重新计算受影响的分支。相同状态 ID 不能对应两份不同内容；跨任务、跨场景或来自未来轮次的历史不能混用。

下一轮将已保存的状态放进 `history`。记录包含必要资料引用，资料重名但内容不同时会区分身份。事件按来源、运行、场景、事件 ID 和版本处理重复与修改；超过容量会标记不完整。同一组合若对相同组件和范围产生不同状态更新，会被拒绝。组合不提供“一次性保存全部节点”的事务，保存顺序和冲突后的重算由调用方处理。

还有几个辅助功能专门处理常见的数据边界，位于 [adapters/transitions.py](context_components/adapters/transitions.py)：它可以根据明确的自动重置模式，分开“上一段结束时的观测”和“下一段开始时的观测”；仅重置的响应不计为执行了操作。RLDS 数据整理会排除末步不应作为有效执行证据的动作、奖励和折扣字段，并标记记录是否可用于响应分析。同时处理多个环境时，可检查它们没有共用同一个历史身份。

深度数值可通过 `decode_depth_sample` 按明确编码解释：支持 ROS 的毫米整数和米制浮点表示，以及 RoboMME 的毫米整数表示。零值、无穷值或缺少有效性依据的值会分别标为无效、超量程或未知，不直接充当正常深度。这些辅助函数要由调用方显式调用，不会连接环境。

**把结果交给纯语言或多模态 agent**

`render_context` 接收单组件或组合结果，将它们整理为文字块、资源表和可选媒体块。调用方通过 `audience.modalities` 声明接收方能使用文字、图像、视频或音频中的哪些类型。它不依赖某一家模型 SDK，也不把图片自动翻译成文字描述；纯语言模型需要相应的文字线索或处理工具。

调用方用 `content_format` 选择 agent 看到的内容，十个组件均支持：

| `content_format` | agent 收到的文字块 |
| --- | --- |
| `json` | 仅 JSON，保留原先的组件视图，适合自己编排提示词的调用方。 |
| `text_json`（默认） | 组件专属的英文使用说明 + JSON 数据。 |
| `text` | 英文使用说明 + 当前数据的分层文字列表，不附 JSON 对象；数值、单位、标识、顺序、空值、问题和限制仍会保留。 |

说明按各组件职责编写，并根据本次结果选择相关内容。每个组件还附带当前字段的英文解释，覆盖关键参数的含义、单位、适用范围和结果限制；未出现的可选字段不附加对应说明。调用方自定义的字段和值原样展示，不擅自赋予机器人或 benchmark 特定含义。例如，空间组件解释像素、射线与空间点的区别；执行反馈区分提交、接受和执行；资源组件区分可执行数量与答案长度；答案组件区分通过、失败和未检查。说明不包含固定机器人、benchmark 或操作步骤，也不会把缺少的事实补成猜测。生成的说明统一为英文；调用方提供的任务文字、证据原文和字段值保留原内容，不自动翻译。

英文说明同时回答“如何使用这些信息推进任务”和“这些字段是什么意思”。它按当前结果选择指导，不根据 benchmark 名字猜测机器人或流程。下面是各组件负责的指导范围：

| 组件 | 如何帮助 agent 使用本次结果 |
| --- | --- |
| `task_context` | 明确任务要求与完成依据，制定或更新简洁计划，检查前置条件、受阻目标、失败后的调整与完成判断；分别处理执行、推理和混合任务。 |
| `observation_context` | 选择相关观测，核对来源、场景与时间，区分事实、估计和假设，处理矛盾、撤回与不完整事件记录。 |
| `spatial_context` | 将计算结果对应到具体问题，比较前确认坐标系、单位和物理参考点，识别投影、深度与几何假设的适用范围。 |
| `interaction_contract` | 将意图对应到已声明的操作，检查参数、分组和执行语义；兼容查询、回答及调用方自定义的控制类型。 |
| `execution_feedback` | 区分请求与实际执行，对照请求和执行记录更新进展，中断后先核对已产生的效果，避免重复执行。 |
| `response_evidence` | 检查估计的条件、样本和局部适用范围，按相同变量比较有证据支持的候选，避免外推或将预测当作观测。 |
| `resource_context` | 分别核对资源余额、成本与上限，处理不足、过期和不可中断窗口，避免重复扣减或把容量当成必须用完的额度。 |
| `evidence_context` | 选择有关的资料和定位信息，通过匹配的接口读取，区分登记、可读取与语义理解，并保留来源。 |
| `tool_context` | 根据缺少的信息选择工具，检查输入输出，判断历史结果能否复用，按现有策略处理失败；工具描述不创建接口或权限。 |
| `output_contract` | 整理完整候选，遵守精确保留规则，定位检查失败并重新验证；区分格式合规、答案正确和任务成功。 |

例如，无目标拆分时，任务组件会建议建立临时计划；出现 `blocked` 时才追加受阻目标的处理建议；纯推理任务不会被要求执行机器人操作。只有结果确实含有 `state_update` 时，任务说明才提醒调用方保存该状态，而且会明确指出它并不自动记录 agent 随后的决定。工具失败后的建议不会被添加到只有成功记录的结果中。这些指导不会替调用方增加动作接口、重试权限或固定保存格式。

说明增强后，`text_json` 和 `text` 会占用更多上下文空间。调用方应按实际交付包检查预算，并只启用当前需要的组件；`json` 仍可用于自行编排说明。组件不会为了满足预算而悄悄裁剪关键说明或数据。逐组件的审查依据与验证范围见 [说明审查记录](tmp/guidance-review.md)。

**三种形式都先生成完整的组件 JSON。** `build_context` / `compose` 的结果始终用于上游下游传递和历史状态保存；`render_context` 只生成给 agent 看的表示，不修改结果中的 `content`、`references`、`bindings` 或 `state_update`。展示形式不能代替组件协议，文字输出也不应被重新解析为历史状态。生成 JSON 不等于自动保存文件，保存仍由调用方负责。

```python
from context_components import build_context
from context_components.common import dumps
from context_components.render import render_context

request = {
    "schema_version": "context.v1",
    "scope": {"run_id": "example", "task_id": "custom-task",
              "epoch_id": "scene-1", "turn_index": 0},
    "input": {"task": {"text": "Explain the order of the observed events.",
                       "kind": "reasoning"}},
}
result = build_context("task_context", request)  # Always generates the full JSON data.
canonical_json = dumps(result)                 # Retain this for component exchange.
packet = render_context(result, {
    "receiver_id": "agent", "session_id": "session-1",
    "content_format": "text",                 # Or "json" / "text_json".
    "audience": {"modalities": ["text"]},
})
agent_text = "\n".join(b["text"] for b in packet["blocks"] if b["kind"] == "text")
```

兼容性说明：默认文字块从原来的 JSON 文本变为“英文说明 + JSON”。已有代码若需要对 `block["text"]` 直接解析 JSON，请显式指定 `content_format="json"`；CLI 默认的 `--format json` 仍返回完整原始结果。`language` 如显式提供，仅支持 `en`。新增说明也计入交付的字节或 token 预算，超出预算会报错，不会暗中丢弃关键数据。切换显示形式时，增量交付会更新对应文字块，原始 JSON 和状态不受影响。

默认返回完整包 `full`。只有调用方明确请求增量、提供接收方实际保留的旧包 `retained`，且接收方、会话和任务范围匹配，并声明 `reconstructs_context=true` 时，才会生成只描述变化的 `delta`。接收侧用 `apply_delta` 校验并重建新的完整包；旧包不会被原地改写。缺少有效保留基准时使用完整包；损坏或格式非法的基准仍可能报错，不保证所有错误都会自动回退。

`ReceiverState` 是可选的内存辅助，用来检查提交顺序、拒绝迟到的旧结果并记录接受的包。实际发送失败或超时时，不应调用 `accept` 冒充成功接收。历史状态保存和消息接收确认是两件事；从 JSON 中删掉旧事实，也不会自动删除模型此前收到的消息，调用方需要构建正确的当前上下文。

不同组件可以使用相同的本地资料名称，交付包会用别名区分，并保留它来自哪个结果、原资料叫什么。单独渲染引用了上游内容的结果时，通过 `sources={context_id: context}` 提供对应上游；渲染组合结果时会自动使用包内节点。上游尚有包外依赖时，仍需提供来源。

**命令行输入输出选项**

| 选项 | 使用方法 |
| --- | --- |
| `--input PATH` | 从文件读取请求；`-` 表示从标准输入读取，也是默认值。 |
| `--output PATH` | 写入一个新文件；`-` 表示输出到终端，也是默认值。已有文件不会被覆盖。 |
| `--format json` | 输出完整结构化结果，便于后续程序继续处理。 |
| `--format text` | 只输出交付包中的文字块，内容由 `--content-format` 选择；需要完整资源表时使用 bundle。 |
| `--format bundle` | 输出文字块、资源表和适用的媒体块，供外部接入层使用。 |
| `--content-format json\|text_json\|text` | 选择 agent 文字块的内容，默认 `text_json`；配合 `--format text` 或 `--format bundle` 使用。 |
| `--canonical-output PATH` | 另外保存未经渲染的完整结果；不能与主输出使用相同路径。 |
| `--resource-root`、`--resource-map` | 一起提供，指定允许读取的文件根目录和资源名称到相对路径的 JSON 映射。 |
| `--receiver-id`、`--session-id` | 标明交付给谁、属于哪个会话。 |
| `adapt --benchmark … --public-paths …` | 选择评测并从调用方提供的 JSON 文件读取允许公开的字段路径；只输出计划，不自动执行组件。 |
| `--components`、`--catalog` | 适配时选择组件，或从文件提供额外的冻结目录。 |

例如，只向 agent 输出英文说明，同时保存供组件间和历史轮次使用的完整 JSON（输出路径必须尚不存在）：

```bash
python -B -m context_components task_context \
  --format text --content-format text \
  --output agent-context.txt --canonical-output component-result.json <<'JSON'
{"schema_version":"context.v1","scope":{"run_id":"example","task_id":"custom-task","epoch_id":"scene-1","turn_index":0},"input":{"task":{"text":"Explain the order of the observed events.","kind":"reasoning"}}}
JSON
```

将 `--content-format text` 换为 `json` 或 `text_json`，只改变 agent 的文字文件；完整 JSON 仍由 `--canonical-output` 单独保存。`--format bundle` 的外层始终为 JSON 交付协议，选择“仅文字”指其中发送给 agent 的文字块，不会把交付协议也变成散文。

CLI 不会根据请求中的工具名字自动加载执行代码；要注入实际处理器，使用 Python API。高级增量交付通过 Python API 使用，CLI 的 text/bundle 路径默认生成完整包。命令行写文件采用“创建新文件”的方式避免覆盖；同时输出多个文件时不保证它们全部一起成功。遇到处理错误时输出 `context.error.v1` 并退出码 2，错误说明包含原因及可定位的位置。

**验证结果和继续查阅**

全部离线测试统一放在 `tmp/tests/`，其中 `test_render_presentation.py` 覆盖字段解释和三种显示形式，`test_guidance_workflows.py` 检查各组件的任务指导及状态切换，`test_task_modes.py` 检查类型传播、内容选择、冲突和历史兼容性。从包含该目录的 `v1` 项目根目录运行：

```bash
python -B -m unittest discover -s tmp/tests -v
```

测试覆盖十个组件、三种显示形式、完整 JSON 的保留、上下游传递、历史状态、媒体引用、增量交付、精度和预算。`v1` 分支中的历史验收报告不代表本次改动已完成模型或机器人评测。

历史 [验证报告](https://github.com/JingInAI/embodied-context/blob/v1/tmp/validation-report.json) 记录了当时 Python 3.10.22、3.11.15、3.12.3 各通过 35 项测试，以及全部目录身份的适配检查。报告绑定当时的代码摘要，不能作为后来改动的验证证明。

测试使用合成输入、固定目录、临时文件和模拟的信息处理器，验证格式转换、引用、状态、数学计算、文件读取和交付行为。没有进行真实模型、仿真或真机评测，因此不证明任务成功率或实际效率已经提升。

下面是**可选的历史维护命令**，不是安装或普通调用步骤。仅在原始 `context_modules/scripts_v1/` 工作区中，且已经具备完整的 `tmp/`、`../docs/`、`../scripts/` 及维护工具要求的来源文件时使用；独立克隆当前 `master` 后不能直接运行这些命令。路径仍以组件项目根目录为基准：

```bash
# 运行原工作区的验收工具并更新报告；需要历史资料及相邻设计目录。
python -B tmp/verify_release.py

# 检查原工作区的设计文档、来源和原组件完整性。
python -B ../docs/verify_documents.py --implementation
```

精确接入字段见 [输入输出与状态规则](context_components/schemas/)。原工作区还保留 `../docs/implementation.md`、`../docs/spec.md`、`../docs/plan.md` 和旧版 `../scripts/`；它们不属于独立组件仓库的安装内容。

历史维护工具包括 [finalize_schemas.py](https://github.com/JingInAI/embodied-context/blob/v1/tmp/finalize_schemas.py) 和 [build_catalogs.py](https://github.com/JingInAI/embodied-context/blob/v1/tmp/build_catalogs.py)。旧版测试的保留、调整与退役记录见 [test-migration.json](https://github.com/JingInAI/embodied-context/blob/v1/tmp/test-migration.json)。这些资料不作为安装后的运行依赖，也不会将各评测的模型和仿真依赖装入核心组件。
