# 根据明确任务类型调整组件内容

十个组件都支持明确的任务类型：`execution`（执行）、`reasoning`（推理）、`hybrid`（混合）。类型只来自调用方的声明、同一组合、上游组件或历史状态，不根据任务文字、机器人名称或 benchmark 名称猜测。

有两层适配：

1. **声明类型**：通过 `input.task.kind`，让 JSON 保留该类型和组件专属用途说明，让英文指导适合执行、推理或混合任务。仅声明类型不会删除观测、动作语义或历史执行证据。
2. **明确选择内容**：通过可选的 `request.task_variants`，为不同类型指定组件实际使用的输入字段或 focus。这一步发生在计算前，能改变真正的 JSON 结果，而不是只改变显示文字。

## 单组件调用

```python
from context_components import build_context
from context_components.render import render_context

request = {
    "schema_version": "context.v1",
    "scope": {
        "run_id": "example", "task_id": "review-execution",
        "epoch_id": "record-1", "turn_index": 0,
    },
    "input": {
        "task": {"kind": "reasoning"},
        "executions": [{
            "id": "attempt-1", "status": "interrupted",
            "submitted": {"items": 10}, "executed": {"items": 4},
        }],
    },
}
result = build_context("execution_feedback", request)
packet = render_context(result, {
    "receiver_id": "agent", "session_id": "example",
    "content_format": "text_json",
})
print(packet["blocks"][0]["text"])
```

这里是分析已有执行记录。结果仍包含实际执行的 4 项，不会因为类型是推理就把执行反馈删掉。英文说明指导 agent 分析中断结果和原因依据，不把失败记录当成重试指令。

`task_context` 仍需要完整的 `input.task.text` 与 `kind`；其他九个组件的共享任务字段只接收 `input.task = {"kind": ...}`，不复制任务文本、目标或计划。

## 让类型真正改变计算结果

[task-kind-spatial.json](examples/task-kind-spatial.json) 使用同一份明确提供的坐标数据，设置以下调用方选择：

| 类型 | 计算内容 |
| --- | --- |
| `execution` | 两个给定点之间的距离，结果为 0.5 米。 |
| `reasoning` | 给定点在指定坐标系中的位置，结果为 `[0.3, 0.4, 0]` 米。 |
| `hybrid` | 明确列出上述两个查询，同时生成两项结果。 |

这些查询是示例调用方选择的，不表示执行任务只能计算距离，或者推理任务只能变换坐标。所有数据均为合成输入，不对应真实机器人观测。

从组件项目根目录运行默认的推理版本：

```bash
python -B -m context_components spatial_context \
  --input tmp/examples/task-kind-spatial.json \
  --format text --content-format text_json
```

在 Python 中比较三种类型：

```python
from pathlib import Path
from context_components import build_context
from context_components.common import loads

request = loads(Path("tmp/examples/task-kind-spatial.json").read_bytes())
for kind in ("execution", "reasoning", "hybrid"):
    request["input"]["task"]["kind"] = kind
    result = build_context("spatial_context", request)
    print(kind, result["content"]["results"])
```

`task_variants` 的形式为：

```json
{
  "request": {
    "task_variants": {
      "execution": {"focus": ["geometry-reader"]},
      "reasoning": {"focus": ["record-reader"]},
      "hybrid": {"focus": ["geometry-reader", "record-reader"]}
    }
  }
}
```

上面是工具组件的请求选项片段，两个工具需由调用方预先注册。每个 variant 可以包含 `input` 或 `focus`，也可以同时包含。空间组件的完整可运行请求见链接文件。选择工具不会创建工具或扩大工具权限。

规则如下：

- `input` 是对基础输入的**顶层字段替换**。数组和嵌套对象整体替换，不拼接、不递归合并。基础输入本身必须满足组件格式要求。
- 未替换的字段保留基础输入值。没有对应类型的 variant 时，使用基础输入；`hybrid` 不自动合并另外两个分支。
- variant 不能修改 `input.task`，也不能修改 scope、历史、资料声明、工具接口或预算。全部基础资源仍由调用方明确提供。
- `focus` 沿用组件已有含义，例如工具 ID 选择或任务关注点；不会为原来不使用 focus 的组件创造隐式过滤逻辑。
- 所有分支都进行输入结构校验，实际选择的分支还接受正常的引用和组件语义检查。未选中的分支不会执行工具或计算。
- 提供 variants 却没有任何可用的任务类型声明时，返回 `invalid_request`，不会擅自选择一个分支。

每个组件仍保留自己的输入组织方式：任务目标、观测特征、空间查询、操作列表、执行记录、响应样本、资源与成本模型、资料读取查询、工具 focus、输出约定均由各自协议定义。variants 只统一选择方式，不统一或替换这些领域协议。

## 组合调用与上游传递

组合可以在顶层声明：

```json
{
  "schema_version": "context.compose.v1",
  "task": {"kind": "reasoning"},
  "scope": {"run_id": "example", "task_id": "analysis", "epoch_id": "one", "turn_index": 0},
  "nodes": [{
    "id": "budget", "component": "resource_context",
    "request": {
      "schema_version": "context.v1",
      "scope": {"run_id": "example", "task_id": "analysis", "epoch_id": "one", "turn_index": 0},
      "input": {"resources": []}
    }
  }]
}
```

这个最小组合没有提供资源余额，因此不会推断可用容量。也可以只在某个节点的 `input.task.kind` 声明类型，整个组合会使用该明确声明，包括在任务节点之前运行的观测节点以及独立分支。无需为了传播类型而倒置“观测 → 任务”的数据依赖。

单独调用组件时，省略本地类型可继承上游标准 JSON 中的 `task.kind`。旧版 `task_context` 结果中的任务 requirement.kind 也可识别。显式类型必须一致；组合顶层、节点、上游或历史中有冲突时返回 `task_kind_mismatch`，不会使用优先级静默覆盖。

组合会在调用任何信息处理工具前检查已声明类型、解析引用形式的外部上游类型，并校验全部 variant 的结构。外部上游读取失败仍是对应节点的错误，独立节点可以继续；依赖失败节点的下游不会使用它。

11 个 benchmark 适配器把已有 profile 解析出的类型传给每个选中组件，即使没有启用 task_context。显式 `profile.task_kind` 可以选择三种类型；省略时延续原有适配器默认规则，包括 VLABench 的 VLM 推理模式。

## JSON、显示形式与历史

有明确类型时，完整组件结果额外包含：

- `task.kind`：实际使用的类型。
- `guidance` 中 ID 为 `task_kind_usage` 的 recommendation：该组件在此类型下的用途。它是使用建议，不是世界事实或任务成功证据。
- 对于有历史状态的组件，`state_update.state.task.kind` 保存类型，供下一轮校验。

三种显示形式均保留这套语义：仅 JSON 不附英文段落；文字 + JSON 解释本次用途并展示数据；仅文字展示说明和数据列表。完整结果始终单独生成，作为组件间和历史交流媒介。渲染不改变计算结果或引用。

有类型的历史会在下一轮继续提供类型。新输入声明不同类型会报冲突；如果确实开始另一类任务，应建立相应的新任务/会话状态，或将经调用方明确公开的历史记录作为该新任务的证据输入，而不是混用旧状态。旧历史没有类型时仍可读取；旧 task_context 历史中保存的 task.kind 仍属于明确声明。

九个非任务组件在本地、组合、上游和历史都没有声明类型时保持通用模式。task_context 原本就要求 task.kind，这一要求保留；组合或上游的明确类型也可补齐它。

这是当前 v1 协议的可选字段扩展。旧输入仍可使用，但固定旧版本的严格 JSON 消费端需要同步升级协议定义，才能接收新增的 task 元数据。没有新增 task.kind 专用 CLI 参数；CLI 直接读取请求 JSON，与 Python API 行为一致。

说明和元数据都计入预算。超限仍会明确报错，不会删掉证据、隐藏裁剪或自动改成另一种显示形式。这里的兼容性验证是离线协议测试，不代表实际 benchmark 或机器人任务表现。
