# 首版接入记录与待办（8e731a5，历史状态）

2026-11-01 更新：三场景固定案例、多角色 EvoSafe 搜索、结构化 hook SDK 与同模型
分类器的接入及验收见 [EXPANDED_ACCEPTANCE.md](EXPANDED_ACCEPTANCE.md)。

2026-10-30 更新：已增加 NVIDIA OpenAI-compatible victim、api3.py 安全读取、
Codex `--yolo` 提案后端和真实 smoke 实验。最新结果及新发现的上游评分问题见
[NVIDIA_SMOKE_RESULTS.md](NVIDIA_SMOKE_RESULTS.md)。以下记录保留首版时的验证范围，
其中“未调用真实模型”“无 victim token 计量”等状态已被后续工作部分解决。

分支：`feat/agentdyn-evosafe-integration`。此次修改在 Hermit 仓库内，未修改
`../EvoSafeHarness` 或把第三方 AgentDyn 源码复制进仓库。

## 已实现

| 部分 | 实现与边界 |
|---|---|
| Adapter | 内置 `evosafe@1.0`；可修改 ADAPTER.md、defense.py、BUNDLE.md；固定规格检查和接口说明 |
| Hook bridge | 每个 episode 新建 Defense；支持同步/异步 prompt transform、pre/post hook；pre 可改参数或返回阻止理由，post 处理实际序列化工具结果 |
| 原生执行 | 保留 AgentDyn 的 agent pipeline、工具执行器、环境初始化和原生 judge；只替换工具执行器的 runtime facade |
| 错误处理 | 防御加载/执行异常向上传播；没有终态回答则判运行失败；不降级成无防御成功结果 |
| 固定数据 | 从已有 trace 导入或读固定 JSONL；去重、补正常任务、按用户任务分组划分、记录数据哈希；不生成攻击 |
| Evolver | 用 Hermit 的 llm 工具提出一个防御候选；父版本和候选在相同固定集合上评估；按 utility−ASR 和 utility 下限选优 |
| 状态与版本 | 当前 adapter 始终是已接受版本；候选、选择报告和试验历史分别写入 output/state，由 Trainer 管理版本 |
| 报表 | 分开统计 clean utility、injected utility、ASR、错误和覆盖情况；不使用普通均分代替防御目标 |
| 来源记录 | 记录参考 commit、模型、任务内容和防御内容哈希；episode 目录独立，不复用旧候选缓存 |

这里移植的是 EvoSafeHarness 的“双表面防御 + 反馈选优”思路。现有 DTAP bundle
依赖 DTAP 类型，不能未经修改直接加载；没有声称完整复现原方法。

## 实际验证

参考 AgentDyn commit：`5353cf7615b135cace8d07c8f12dac53a16b6db3`。
已在仓库外的临时环境安装 Hermit 和该 AgentDyn，并成功导入 Shopping suite：
20 个用户任务、9 个注入目标、28 个注入向量。

- 离线单元测试：hook 阻止与参数修改、异步 hook、输出过滤、异常传播、实例隔离、
  模板校验、评分方向、分组划分、接受/拒绝/失败回退。
- 原生集成：用脚本模型执行 Shopping 的真实工具和环境；无防御 bridge 与原生
  utility 一致；初始模板可以加载；无害标记通过真实 injection vector 进入工具
  返回后被 post-hook 处理，验证挂接顺序。
- Trainer 集成：用确定性任务与提案替身，跑完整 rollout → material → proposal →
  check → validation → acceptance → Git 记录流程；确认验证集合不包含 test ID。

这些测试没有调用真实模型，也没有执行真实攻击载荷。

执行结果：新增测试文件 15 项通过；与已有 training、agent tool gate 测试一起运行
共 35 项通过。最后的终态判定与候选文件回退调整后，新增 15 项再次通过。
示例配置可由 Config.load 加载，`git diff --check` 无格式错误。

另外实际导入了参考仓库 `runs/google_gemini-2.5-flash/shopping` 的已有日志，
仅在仓库外生成数据，没有执行其载荷。得到 20 个用户任务组、200 个 episode，
train/val/test 分别为 120/40/40（用户任务组 12/4/4）。这验证了日志导入路径，
不代表该组合已通过有效配对审查或可以作为最终论文实验协议。按此验证集规模，
每次候选选择需要 80 个 episode（父版本 40、候选 40），还未计入训练 rollout。

## 当前不能完成或尚未验证

| 项目 | 当前状态 / 原因 | 后续完成条件 |
|---|---|---|
| 严格沙箱运行 | 本机 bubblewrap 返回 `loopback: Failed RTM_NEWADDR: Operation not permitted`；默认强制沙箱会阻止训练启动 | 在允许相关命名空间的主机运行；保留强制隔离并复测 |
| 真正模型训练和 held-out 结果 | 未调用模型；尚未确定 victim/proposer、预算和固定用例来源 | 配置模型、凭据和用例，先 smoke 再做三个防御版本对照 |
| 官方协议复现 | 当前划分是自定义的固定 replay 协议；不是官方全集实验 | 明确有效 task/goal 配对及原始实验设置，冻结清单并检查覆盖 |
| 原 EvoSafeHarness bundle | DTAP 的类型、metadata、工具名与此接口不同 | 逐个移植 seed，写相同行为的回归用例；不可直接宣称 baseline 等价 |
| 完整搜索方法 | 当前单提案、单阶段验证；没有独立 critic/analyzer、分层 cascade、多种 seed 搜索 | 在最小实验有效后补充防御审查和分阶段评估 |
| Victim token/美元计量 | AgentDyn 当前执行路径未提供统一 usage；返回 None，不能冒充 0 | 接入 provider usage/meter，再验证预算包含全部调用 |
| 噪声与最优选择 | 每轮重测父候选，严格比较单次均值；小验证集易波动 | 加重复评估、置信区间及稳定接受阈值；不把暂时提升当显著改善 |
| 更多场景、模型与外部基线 | 参数允许其他 AgentDyn suite，但仅对 Shopping 做了离线原生集成测试 | 分别复测；当前未整合原生 CaMeL/DRIFT/Progent runtime |
| Hook 的能力安全隔离 | 防御 Python 与原生运行/判分同处 rollout 进程；不是独立权限隔离 | 需要更强威胁模型时，将防御服务和 judge 分进程、缩小资源授权 |
| 运行时评分语义 | 保留原生 judge；部分 judge 可能基于模型请求轨迹，而不只看实际执行 | 审计选用 case 的 trace-based 判分；阻止工具不等于自动证明攻击被阻止 |
| 内置模型注册 | 使用 AgentDyn model registry，未支持任意 Hermit backend 到 victim 的自动绑定 | 增加明确的 provider bridge 与端点测试 |

## 接入时确认的关键细节

1. `BaseInjectionTask.security()` 返回 True 代表注入目标成功；在本集成中记为
   `attack_success=True`。正常任务返回的第二个值没有这个意义，统一记为 None。
2. 注入发生在原生环境初始化阶段；post-hook 接收工具从该环境读取后的序列化内容。
3. pre-hook 返回 block 才是可恢复拒绝；意外异常属于执行错误，不计作安全成功。
4. 传给 hook 的上下文不包含 task ID、注入标签或完整环境。固定 bridge 在可演化
   adapter 外；但 Python 进程内隔离不构成对恶意候选的强安全保证。
5. validation 是调参集合。所有同一用户任务的变体必须放同一 split，held-out
   结果不能回流到候选选择。
6. AgentDyn 包名仍为 agentdojo；建议将两个项目同时交给依赖解析器，否则单独
   安装 AgentDyn 可能升级 Hermit 固定的 MCP 版本。此次同时解析后成功安装。
7. `reference_revision` 是已验证的参考版本，不是对实际安装 checkout 的自动验证。
8. 固定 replay 未保证跨模型仍触发同样的攻击路径；报告须同时展示任务完成率、
   测试覆盖和失败情况，不能仅展示 ASR。
