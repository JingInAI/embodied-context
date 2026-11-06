# v1-1 通用证据与交付扩展

本分支以 `v1` 的 `289a721` 为基线。设计依据与经验映射见
[v1-1-design.md](v1-1-design.md)，实际离线验证见
[v1-1-validation.json](v1-1-validation.json)。以下接口均是可选扩展。

## 1. 为什么这样分工

一次任务迭代能暴露信息缺口，但不能提供通用的控制参数。可以迁移的是：
区分请求和实际结果；区分描述与预测；检查经验适用条件；保留中间证据；
区分任务评估与执行故障；给有效数据留出上下文空间。

| 组件/层 | 新信息 | 不承担的职责 |
| --- | --- | --- |
| `task_context` | 当前证据是否满足调用方建议/示例的显式条件 | 不编写策略、不生成操作、不自动重放示例、不认证成功 |
| `response_evidence` | 已执行样本的统计量和显式请求的逐记录比值 | 不把稀疏描述升级为预测，不放松联合支持检查 |
| `execution_feedback` | 外部报告的评估完成度、结果或故障分类 | 不根据退出码、自然语言日志或缺失结果推断任务失败 |
| renderer | 可选精简解释，完整交付数据和引用 | 不按预算删掉字段、事实、约束或历史 |

仍为十个组件。事实可信度及撤回归 `observation_context`；坐标计算归
`spatial_context`；操作语义、资源限制、工具能力和输出校验保留原所有权。
不新增信息重叠的“策略组件”或跨运行的隐式经验库。

## 2. 条件建议：task_context

在原 `input.task`、`goals` 等字段之外，调用方可传入 `input.decision_rules`。
未传此字段时，原输出和状态流程不变；空数组表示本次明确没有规则。

| 输入字段 | 类型/必需 | 含义 |
| --- | --- | --- |
| `id` | 非空字符串，必需，规则内唯一 | 本次规则标识 |
| `when` | 条件对象，必需 | 引用观测组件中的 claim ID，不解析自然语言事实 |
| `recommendation` | 非空字符串，必需 | 调用方已有的建议，只在规则适用时输出 |
| `evidence_refs` | 非空引用 ID 数组，必需 | 规则自身的来源；须在共同 `references` 中声明 |
| `max_age_turns` | 非负整数，可选，默认 `0` | 允许使用的谓词证据年龄；单位是轮次，不是秒 |
| `required_bindings` | 共同 bindings 对象，可选，默认 `{}` | 与本次请求配置比较，如 `config_version`；缺少所需键为未知，不相等为不适用 |
| `next_check` | 非空字符串，可选 | 条件未决时呈现的调用方检查建议，不自动执行 |
| `example_reference_id` | 已声明引用 ID，可选 | 条件适用时才输出的示例引用；示例内容不充当条件成立的证据 |

原有 `{"fact_id":"checked","equals":true}`、`all`、`any`、`not` 保留。
新增数值形式 `{"fact_id":"sample_count","operator":"ge","value":3}`，
`operator` 支持 `lt/le/gt/ge`，也可用在已有目标条件中。阈值由调用方明确提供。
不将字符串或布尔值转换成数值。条件支持三值逻辑：例如 false AND unknown
为 false，true OR unknown 为 true，NOT unknown 仍为 unknown。空 all/any 延续
已有逻辑恒真/恒假的语义；需要数据前提时应显式列出谓词，不能用空条件替代。

建议规则只读取上游 `observation_context` 中的 `entities/relations/events`。
谓词必须来自匹配的 task/run/epoch/perspective、非未来且在允许轮次年龄内；
只接纳带证据引用的 observed/derived claim。estimated、hypothesis、撤回或
相互冲突的同 ID 证据不能被选择性忽略后制造确定性。历史事件使用原始 scope，
不会因重新交付而变新。未注明 claim scope 的新特征沿用其观测 context scope，
因此发布方必须保留旧特征的真实来源轮次。scope 的年龄检查不代替物理时间检查。

输出增加 `content.decision_support[]`：

| 字段 | 语义 |
| --- | --- |
| `id` | 原规则 ID |
| `status` | `applicable`、`not_applicable` 或 `unresolved` |
| `condition_result` | 综合谓词和 required_bindings 后的 `true/false/null`，不是任务成功判定 |
| `evaluated_condition` | 原始条件表达式 |
| `max_age_turns`、`required_bindings` | 实际使用的规则时效与配置要求 |
| `evidence_refs` | 规则来源，以及本次检查过的上游 claim 指针；指针不是额外独立观测 |
| `recommendation`、`example_reference_id` | 仅适用时呈现，示例字段仍是可选项 |
| `next_check` | 仅未决且调用方提供时呈现 |
| `limitations` | 适用性不是权限、计划或成功认证；未建模条件没有检查 |

配置明确不匹配使规则不适用。缺少配置键时，除非已有明确不满足的谓词，否则
规则未决。组件成功完成规则检查时，外层可以为 `ready`，即使某条建议为
`unresolved`；必须读取每条规则状态。规则不写入任务历史，每次由调用方提供。
规则适用不代表推荐唯一、优先或无冲突；多条建议的取舍仍由调用方/agent 处理。

可运行示例将观测与任务连接成 DAG，纯推理场景检查报告候选的证据：

```bash
python -B -m context_components compose \
  --input tmp/examples/v1-1-conditional-review.json \
  --format bundle --content-format text_json --explanation-detail concise
```

相同机制也可表达“先核验已有进展再重试”等外部策略，但库没有默认绑定这一策略，
更不包含任何特定任务的操作步骤。

## 3. 稀疏记录描述：response_evidence

原查询 `support/estimate/compare_candidates` 保持原语义。新增
`input.query.kind="describe"`：对收到的、匹配当前身份/条件/配置且已执行的
记录作回顾性描述。单个样本可以描述，不能因此通过原有预测的联合支持检查。

输入继续使用原 `variables`、`records`、`conditions`。describe 要求每个变量
明确 `role=input|response` 和单位，数值分别位于记录的 `inputs/responses`。
记录仍需 `id/scope/bindings/conditions/executed/evidence_refs`。未执行、撤回、
不同运行/配置/条件及无证据的记录会排除，并列入 `support.excluded`。
只统计声明的变量；记录中其他变量不被自动选择。缺少某变量不补零、不插值。

| query 可选字段 | 约束 |
| --- | --- |
| `ratios[]` | 每项 `{id,input,response,min_abs_input}`；ID 唯一；input/response 指向角色匹配的已声明变量 |
| `min_abs_input` | 每个比值必需、严格正数，单位与对应 input 一致；由调用方指定，库无默认阈值 |
| `max_age_seconds` | 非负数；若提供，必须同时给 `now`，且记录必须有可比较的 time |
| `now` | 共同 TimePoint：clock_id、clock_epoch、unit、value；不读取隐藏时钟 |

describe 不接受拟合参数 `inputs/radius/distance_scale/candidates/half_life_seconds/
max_residual_rms`；`ratios` 也不允许传给其他查询类型。不可比时钟按既有时间合同
报错，缺时间/超龄/未来记录则列为排除。

输出保留 `support`、空 `estimates`、`limitations`，新增 `descriptive`：

| 字段 | 内容 |
| --- | --- |
| `statistics[]` | 每个有样本的变量：variable、role、unit、sample_count、minimum、maximum、mean、evidence_refs |
| `ratios[]` | 每个请求比值与每条有效记录：id、record_id、input、response、numerator_unit、denominator_unit、evidence_refs、status |
| 比值 `value/reason` | ready 时为有符号 response/input；unavailable 时只给 reason，不给数值零 |
| `missing_values[]` | record_id 和缺失的已声明 variable |
| `method` | `descriptive_executed_records` / `1` |
| `conditions` | 原显式匹配条件，不推断未观测条件 |
| `coverage_complete` | 有界内存是否仍保留收到的记录集合，不表示世界历史完整或统计代表性 |
| `limitations` | 回顾性、非因果、聚合与覆盖限制 |

分母绝对值小于阈值时比值不可用，等于阈值时可以计算。缺少成对值或计算超出
有限浮点范围时也不可用。每个统计量有独立样本数；`support.valid_samples` 是
选中的记录数，不能用它代替每个变量的 sample_count。

实现使用有限的 Python float 描述数值，采用归一化求和防止均值中间溢出。
不承诺保留超出浮点精度的低位、小量或精确十进制；原始 canonical 请求/记录
仍按原协议处理。超出有限 float 范围的样本明确报错。需要精确算术的分析应由
显式信息处理器提供，不能把这里的统计量当成精确数值合同。

缺变量/不可用比值但仍有统计量时为 `partial`，完全无统计量为 `unavailable`。
排除不符合条件的记录后，剩余记录足以完成所请求的描述时可以 `ready`；仍须检查
排除清单和覆盖限制。历史记录沿用既有修订、撤回、有界容量和来源引用规则。

```bash
python -B -m context_components response_evidence \
  --input tmp/examples/v1-1-sparse-response.json --format json
```

该示例是一次外部数据处理作业的已处理条数与耗时，不包含下一次作业的预测。
比值不恢复记录内部顺序、延迟或抵消的变化，也不等于控制增益或因果关系。

## 4. 外部结果分类：execution_feedback

每项 `input.executions[]` 可增加 `outcome`：

| 字段 | 约束与含义 |
| --- | --- |
| `category` | 必需：task_evaluation / execution_failure / infrastructure_failure / interruption / unknown |
| `evaluation_status` | 必需：complete / partial / not_run / unknown，描述任务评估的完成度 |
| `evidence_refs` | 必需非空数组，外部分类/评估的来源 |
| `reason` | 可选非空说明，原样保留，不据此推断分类 |
| `task_success` | 可选布尔值，仅 category=task_evaluation 且 evaluation_status=complete 时合法 |

输出增加 `content.outcomes[]`，每项复制上述字段并增加 `execution_id`。
原 `segments` 中的 submitted/accepted/executed 数量和执行状态独立保留。
`status=complete` 不等于完成任务评估；执行中断也不等于此前没有效果。
没有 outcome 的旧记录不会被自动补充；缺少 task_success 仍为未知，不是 false。
组件不计算跨运行分数、重试许可或故障率。

嵌套 outcome 的证据进入历史引用闭包。重新传入历史时，即使引用名称与当前
新资源相同但内容不同，旧评估仍绑定原证据；提高 revision 可更新/撤回记录。
每条执行只有一个可选 outcome；需同时记录多个独立评估时，由调用方分别发布
可区分的记录及关联 ID，不把本扩展当作完整多评估账本。

```bash
python -B -m context_components execution_feedback \
  --input tmp/examples/v1-1-external-outcomes.json \
  --format text --explanation-detail concise
```

示例包含已经独立评估失败的作业和未完成任务评估的基础设施故障，演示两者不能
简单混算成同一种失败。分类是外部报告的结论，组件不独立验证评估器的真实性。

## 5. 精简说明与交付预算

Python API：

```python
packet = render_context(result, {
    "receiver_id": "agent", "session_id": "conversation",
    "content_format": "text_json",  # json / text_json / text
    "explanation_detail": "concise",  # full（默认）/ concise
})
```

`concise` 用组件专属短说明代替完整教学段落和字段教程。十个组件都有自己的
职责和限制说明，仍保留当前 availability、源资料是数据的说明，以及所有实际
数据字段、issues、limitations、引用和资源。full 默认保持原说明行为；当新输出
字段出现时，full 会解释它们。`content_format=json` 不受解释长度影响。

该选项不是截断器。字节/token 预算针对完整交付包按原规则检查；若精简后仍装不下，
返回 `context_budget_insufficient`。不自动切换格式、丢弃历史、缩减图片或删除约束。
原始 result/state_update 不因渲染而修改。只有显式保留且匹配的旧包可以接收 delta；
full → concise 的变更通过原增量机制重建。

CLI 新增 `--explanation-detail full|concise`，仅配合 `--format text|bundle`。
CLI 的 `--format json` 始终是 canonical 输出，不能附加解释选项。仅输出 text
不包含完整资源表，需要资料交付时使用 bundle，并保留 canonical result 做组件
交换和历史保存。

## 6. 兼容性与验证边界

- 没有新增依赖、组件 ID、backend 调用、模型调用、自动策略或隐式跨运行学习。
- 原输入和旧状态继续有效；未请求扩展时不新增相应结果字段；默认完整说明不变。
- `context.v1`、payload/state 版本沿用现有扩展方式。严格旧消费方不能保证识别
  新可选字段，必须同步升级 schema；不声称旧版本可以接收本次新接口。
- 新建议规则每次重新提供；旧数值预测、资源、空间和工具接口的验证条件没有放宽。
- 新测试使用纯推理、外部数据处理和执行记录等合成输入，验证信息合同及兼容性。
  真实任务的一次成功是设计动机，不是本分支提升模型成功率的证据。

从仓库根目录运行 `python -B -m unittest discover -s tmp/tests -v`。
本次独立验证报告与旧 `validation-report.json` 分开，保留历史报告原始含义。

## 7. 本次测量

Python 3.12.14 上完整离线套件通过 105 项测试（基线 79 项，新增 26 项）。
另对 36 个 Python 文件作 Python 3.10 语法检查；这不是 3.10 运行时测试。
两个 schema 重新生成后逐字节相同，`git diff --check` 通过。

以下是三个合成示例的完整 `text_json` 交付包 UTF-8 字节数，包含引用资源：

| 示例 | full | concise | 减少 |
| --- | ---: | ---: | ---: |
| 条件审核组合 | 10,594 | 5,262 | 50.33% |
| 稀疏处理记录 | 4,931 | 2,757 | 44.09% |
| 外部结果分类 | 3,989 | 2,203 | 44.77% |

这些数字是具体示例的交付大小，不是 token、延迟或任务成功率测量。
测试日志、运行源码及测试摘要绑定在独立验证报告中。
