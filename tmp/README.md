# 开发与维护资料

这里集中存放不参与组件正常运行的文件。实际代码仍位于 `../context_components/`，安装配置和使用说明仍位于 `scripts_v1/` 根目录。

| 内容 | 用途 |
| --- | --- |
| `research/` | 上游代码、配置和网页快照，用来追查设计和目录依据；不作为 agent 的运行输入。 |
| `pipeline/` | 执行流程图和绘图脚本。 |
| `examples/` | 文档演示及测试使用的合成输入。 |
| `tests/` | 全部离线测试，包括组件、适配器、集成，以及英文说明和三种显示形式；渲染测试已从项目根目录的 `tests/` 移入。 |
| `build_catalogs.py` | 从固定资料提取任务目录，更新运行包中的适配目录及本目录的目录证据。 |
| `finalize_schemas.py` | 维护运行包中的领域输入输出与状态规则。 |
| `verify_release.py` | 运行测试、核查来源和原 scripts，生成当前验收报告及日志。 |
| `catalog-evidence.json` | 当前任务目录对应的来源路径和内容摘要。 |
| `test-migration.json` | 旧版测试到新版行为的映射；其中旧路径用于说明历史，不是当前执行入口。 |
| `validation-report.json`、`validation-*.log` | 当前目录布局下实际运行的验证结果。 |
| `history/` | 迁移前的报告和目录证据，保留原始字节；其中路径属于历史布局。 |
| `relocation.json` | 文件的新旧位置、移动前摘要和运行文件摘要，便于检查迁移范围。 |

从 `scripts_v1/` 根目录运行：

```bash
PYTHONPATH=. python -B -m context_components task_context \
  --input tmp/examples/minimal-task.json --format json

PYTHONPATH=. python -B -m unittest discover -s tmp/tests -v

python -B tmp/verify_release.py
```

若在上一层 `context_modules/`，使用 `python -B scripts_v1/tmp/verify_release.py`。维护脚本按自身位置寻找运行包，不依赖终端当前目录；测试中的样例也按测试文件的位置查找。

完整验收和目录重建仍需 `context_modules/docs/` 中保留的设计来源和原 `scripts/` 基线。它们是开发时的依赖，不是安装包的运行依赖。生成工具会写入运行包，只有维护目录或格式规则时才需要执行。

迁移不改动运行代码、格式规则、适配目录或安装配置。README 的路径、测试入口和维护脚本的文件定位已同步调整；迁移前的历史报告不代表新布局已经通过测试，以当前 `validation-report.json` 为准。

当前 `v1` 分支将 `tmp/` 纳入版本控制，全部测试统一从 `tmp/tests/` 运行。这些文件不参与组件正常运行，也不包含在安装包中。

## v1-1 增量资料

- `v1-1-design.md`：迭代经验、组件所有权、兼容性与验证决策。
- `v1-1-usage.md`：新增输入输出参数、语义边界与可执行示例。
- `examples/v1-1-*.json`：通用报告审核、稀疏处理记录、外部结果分类三个示例。
- `tests/test_v11_components.py`：本次新增接口及历史/交付回归测试。
- `v1-1-validation.json`、`v1-1-tests.log`：本分支独立离线验证证据。

`v1-1` 从 `v1` 的 `289a721` 创建；旧验收文件继续保留，不用于证明本次更新。
