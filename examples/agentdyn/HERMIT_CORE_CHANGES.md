# Hermit 核心修改说明（供上游汇报与合并）

分支：`feat/agentdyn-evosafe-integration`，相对 `main`。原则：**不改 Trainer 的训练循环**
（rollout → material → 一次 Evolver 调用 → check/commit），只在接口边上做小的、向后兼容的扩展。
EvoSafe 自己的搜索流程（Designer/Criticizer/Cascade/Analyzer）仍然完全在 Evolver 内部实现。

核心改动总量：7 个核心文件约 +70/−19 行，另有文档、CHANGELOG 和测试。没有删除或改变任何现有字段的含义。

## 修改 1：多指标 Judge（`JudgeResult.metrics` + `judge.aggregate`）

### 动机

Hermit 的 judge 只返回一个标量 `score`，Trainer/eval 只报告 `mean_score`。防御任务的目标不是逐条分数的均值：

- clean 任务看 utility，injected 任务看 attack success，两者**分母不同**；
- 目标是 `clean_utility − ASR`，同时还要报告 injected utility、secure completion；
- 执行失败的 episode 不能被算成“攻击成功”或“任务失败”，需要单独计数。

此前只能把两种含义硬塞进同一个标量（clean 用 utility，injected 用 `1−attack_success`），
`mean_score` 因此没有意义，真实指标全部在框架外的脚本（`report.py`、`compare.py`）里重算。

### 与上游的区别

| 项目 | 上游 `main` | 本分支 |
|---|---|---|
| `JudgeResult` | `score, feedback, extra` | 新增可选 `metrics: dict`（默认空） |
| judge 返回 dict | `score`/`feedback` 以外全部进 `extra` | `metrics` 键单独进 `metrics`，其余仍进 `extra` |
| 配置 | `judge.path`, `judge.name` | 新增可选 `judge.aggregate`（同一文件/模块中的函数名，默认 `null`） |
| 失败 episode 的 judge 字段 | `{"score": 0.0, "feedback": ...}` | 额外带 `"metrics": {}`，`score` 仍为 0.0 |
| 学习材料 `summary.json` / `index.jsonl` | mean score 等 | 配置 aggregate 时多一个 `metrics` 字段 |
| `steps.jsonl` 的 `rollout` | `mean_score, scores, ...` | 配置 aggregate 时多一个 `metrics` |
| `run_agent` 工具返回 | `{"results": [...]}` | 配置 aggregate 时多一个 `"metrics"` |
| `hermit eval` 的 `summary.json` | `mean_score, solved_once, ...` | 配置 aggregate 时多一个 `metrics`（所有 repeat 的记录） |
| `hermit check` | 加载 judge | 同时加载 aggregate，名字写错会在 check 阶段报出 |

**不变的部分**：`score` 仍是必填标量，`mean_score`、`solved_once`、预算、CARD 都照旧使用它；
不配置 `judge.aggregate` 时所有输出和行为与上游完全一致。

### 语义约定

- `aggregate(records)` 接收完整的运行记录（`id, input, status, output, judge{score, feedback, metrics, ...}`），
  **包括失败的运行**（`status != "ok"`、`metrics` 为空），由任务决定失败怎么计。
- aggregate 自身抛异常时记录为 `{"error": "..."}`，**不会中断训练或评测**（`hermit.task.summarise`）。
- 返回值必须是 dict。

### 涉及文件

| 文件 | 修改 |
|---|---|
| `hermit/task.py` | `JudgeResult.metrics`；`normalise_judge` 识别 `metrics`；新增 `load_aggregate()`、`summarise()` |
| `hermit/defaults.yaml` | `judge.aggregate: null` |
| `hermit/trainer/rollout.py` | 失败记录的 `judge` 带空 `metrics` |
| `hermit/trainer/material.py` | `write(..., metrics=None)`，写进 `summary.json` 和 `index.jsonl` |
| `hermit/trainer/trainer.py` | 加载 aggregate；step 记录、学习材料、`run_agent` 返回带 `metrics` |
| `hermit/evaluate.py` | eval summary 带 `metrics` |
| `hermit/settings_check.py` | check 时加载 aggregate |
| `docs/framework/task.md`、`docs/reference/config-fields.md`、`CHANGELOG.md` | 文档 |
| `tests/test_judge_metrics.py` | 新增测试 |

### 用法（AgentDyn 示例）

```yaml
judge:
  path: judge.py
  aggregate: summary
```

`hermit/integrations/agentdyn.py` 的 `score()` 返回
`metrics = {kind, utility, attack_success}`，`summary()` 计算 clean utility、ASR、injected utility、
secure completion、按类别的错误数；只有全部 episode 完成时才给出 `objective`，否则为 `None`
（部分完成的 objective 不是分数）。

## 修改 2（本分支更早的提交）：失败 episode 保留用量和日志

`hermit/trainer/rollout.py:run_one`：pipeline 抛出的异常对象若带有 `tokens`、`cost_usd`、`log` 属性，
失败记录会保留它们（类型不合法时仍为 `None`）。上游失败记录中这三项总是 `None`。
用途：victim 调用了模型但最后没有终态回答时，trajectory 和用量不会丢失，便于调试。
仅在异常对象主动提供这些属性时生效，对其他 pipeline 无影响。

## 修改 3（本分支更早的提交）：`hermit check` 遵守配置的沙箱设置

`hermit/settings_check.py`：上游 `check` 检查模板时使用进程默认的 `SANDBOX_ENFORCE`
（默认 required），与 `train` 实际使用的 `sandbox.enabled/enforce` 不一致，在禁用沙箱的配置下
`check` 会因 bwrap 不可用而误报。现在 check 期间临时设成与 Trainer 相同的值，结束后恢复。

## 未修改、仍由 Evolver 自行处理的部分

以下是我们评估过、但为了“不动训练循环”而**没有**改核心的地方，可以作为后续与上游讨论的议题：

1. 一个 step 内多轮候选（trial）的记录与归档：目前写在 Evolver 的 `output/`。
2. 重复评估与成对比较：`run_agent` 没有 `repeats` 参数，由 Evolver 循环调用。
3. 验证集确认与“是否采纳”的决定：由 Evolver 执行，Trainer 只负责 commit。
4. `run_agent` 对验证集任务不返回 log（防泄漏的设计），Analyzer 无法看验证失败的轨迹。
5. 沙箱关闭时 `agent.timeout_min` 不是强制的 episode 超时。

## 本分支非核心的新增（不需要上游合并）

- `hermit/algorithms/evolvers/evosafe/claude_code.py`：EvoSafe 角色可用 Claude Code CLI
  （`proposer: claude`），无工具（`--tools ""`）、无会话持久化、JSON Schema 结构化输出、
  可取消/超时，拒答时停止搜索而不自动重试。与 Codex 后端接口相同。
- `examples/agentdyn/nvidia-thirty-claude.yaml`：Claude Code 角色 + 30/30/30 数据的实验配置。
