# 定向破坏对：34 对全部由可判子级确定性复核

类型：结果。所有者：主代理。上游：[数据质量](data-quality.md)、[众数标注](modal-pairs.md)、[训练诊断](training-diagnosis.md)。证据：`evidence/corrupted/`。

## 结论

换了标签来源：chosen 是 DeepSeek 带整部法给出的真实回答，rejected 是让它只改坏一处、恰好违反**这条处境已被标注的**一条可训练规则。60 次尝试、每处最多 3 次重写，**34 对四项校验全过**，覆盖 **10 条规则**，其中 **8 条在交付标注里原本零覆盖**。校验不用模型投票：目标子项必须按预期方向翻转、其余七个可判子级的计数一个不许动、文本相似度 ≥ 0.75、finish_reason 为 stop 且无复读无回显。丢弃 26 次，丢弃率 43.3%。

关键性质：34 对里**目标子项是唯一变化的子项**（单因性 100%，构造如此要求）；在 39 次"目标子项确实翻转"的尝试中，有的还带动了别的子项（5 次），单因性 87.2%，这些被丢弃而不是收进数据。两侧动作签名**34/34 完全相同**——破坏落在判断层，没有改变工具调用，所以这对数据不是在教"该不该调工具"。

## 做法

1. 目标规则只从已有标注里取：`data/coverage.json`（容量 4 的交付标注）优先，某规则在交付标注里零覆盖时取 `evidence/coverage-uncapped/coverage.json`（不设上限的诊断标注）。计划按"零覆盖优先、标注处境数少的规则先去"排序，每条处境最多配一条规则。
2. 破坏目标必须落在**可判子级能看见**的地方。八个子级里只有三个存在"变坏"的单侧翻转，于是把可训练规则分成三族（`scripts/corrupt_pairs.py` 的 `FAMILIES`，27 条候选规则，逐条写了理由）：

| 族 | 子项 | 破坏方向 | 候选规则 | 选中并验过 |
| --- | --- | --- | --- | --- |
| INF | evidence.unlabeled_inferences | 0 → ≥1 | 12 | 11 对（6 条规则） |
| ENVQ | question.environment_questions | 0 → ≥1 | 8 | 23 对（4 条规则） |
| STOP | question.stops_before_gate | 1 → 0 | 7 | **0 对** |

3. 破坏指令：给 deepseek-flash 处境、原回答、目标规则的 dot path 与原文，要求只改与这条规则相关的一处判断、其余保持原样、输出完整回答正文。模型、温度 0、thinking 关、max_tokens 900 与前面各批一致。请求哈希、原文、改写、usage、成本逐条落 `evidence/corrupted/calls.jsonl`（158 次调用，¥0.155）。
4. 四项校验写在 `verification()`，只调用 `eval/judge.py` 的 `count_checks` 与 `action_class`，判据一个字没改：目标子项翻转；其余七个计数（含"不适用"）不变；`difflib` 相似度 ≥ 0.75 且长度比 0.6–1.6；finish_reason 为 stop、无 72 字符窗口重复 3 次以上、不回显指令。逐条结果落 `evidence/corrupted/verification.jsonl`，汇总落 `summary.json`。

## 结果

| 项 | 值 |
| --- | --- |
| 尝试（处境数） | 60 |
| 调用数 | 158（第一轮 60 + 重写 53 + 45） |
| 验过并收进数据 | **34** |
| 丢弃 | 26（43.3%） |
| 单因性（收进的对） | 34/34 = 100% |
| 单因性（目标翻转的尝试） | 34/39 = 87.2% |
| 相似度中位数 / 最小 | 0.926 / 0.788 |
| 两侧动作签名相同 | 34/34 |
| 覆盖规则 | 10（其中原零覆盖 8） |
| 花费 | ¥0.155（`evidence/corrupted/calls.jsonl` 全部调用求和；`summary.json` 的 `spend_cny` 只算每条处境最后一次尝试，故更小） |

目标规则分布（对数）：`attention.communication.ignored_domains` 10、`intent.decisions.question_frontier` 7、`attention.communication.ask_the_gap` 5、`intent.objective.true_metric` 2、`change.entries.fabricated` 2、`change.record.keep_evidence` 2、`proof.review.unverified` 2、`proof.execution.bind_to_revision` 2、`resources.environment.diagnose_network` 1、`attention.phases.discussion.consequential_only` 1。

翻转幅度：INF 11 对全是 0→1（未标注推断数 0 变 1），ENVQ 23 对全是 0→1（可自查问题数 0 变 1）。没有一对是"多翻转"。

## 丢弃原因

| 原因 | 次数 |
| --- | --- |
| 目标子项没翻转（改坏的那一句落不进计数器） | 16 |
| 改写与原回答逐字相同（模型没改） | 5 |
| 目标翻转但带动了其他子项 | 5 |
| 相似度或长度比不合格（重写而非最小改写） | 2 |

前两类是同一件事的两面：计数器只认它自己的判据——断言句要出现 说明/因为/所以/根本 这类词且不带路径与数字，自查问题要出现 状态/进度/文件/版本/有没有 这类字样且不带 要不要/你觉得。落在判据外的改写不算破坏，一律丢弃，不手动补标签。第三类是"破坏不单因"，也是丢弃：一对只能教一条规则。

STOP 族 0 对：全池 174 条处境里只有 32 条用户轮带门、其中原回答真正在门前停住的只有 9 条，叠上"该规则必须已被这条处境标注"就只剩 2 条，两次重写都没有把停顿改成直接动手（`question.stops_before_gate` 需要删掉停顿标记或加一个变更动作，后者会带动 4 个子项）。这一族本轮没有产出，不是数据够了，是仪器与处境池都不够。

## 局限

1. **三个子级可判，八个不可判。** 只有 `evidence.unlabeled_inferences`、`question.environment_questions`、`question.stops_before_gate` 能被破坏出确定性翻转；`delivery.checkable_artifacts`（92 条原回答已非零）与 `evidence.assert_before_prove`（20 条已非零）只有"改好"的方向，`phase.*`、`delivery.unrecorded_changes` 的破坏会同时带动 2–4 个子项，不单因。175 条可训练规则里因此只有 27 条可当目标，实测覆盖 10 条。
2. **破坏指令被指向了计数器的可观察形式。** 给模型的提示说明了断言词与自查字样，否则改写会落在判据外（16 次就是这样丢的）。这让"定向"更可靠，但也意味着 rejected 的坏法偏向计数器的词表，不等于规则违反的全部形态。
3. **翻转幅度都一样（0→1）。** 每对只注入一处违反，DPO 学到的偏好是"一句断言/一个自查问题"，不是"整段判断方式"。强度与真实 bare 回答的偏差不同量级，训练时要不要按族加权是下一步的问题。
4. **单一模型单次采样。** chosen 与 rejected 都来自 deepseek-flash，温差 0，每处只取一次成功改写（失败的才重试）。没有测"同一条破坏指令再抽一次是否给出同样的改写"，所以这 34 对的稳定性只在"过没过四项校验"这一层，不在"改写文本逐字可复现"这一层。
5. **动作签名相同是设计结果，不是覆盖。** 34 对全都不改工具调用，所以这批数据对"该调什么工具"没有信息量，只能与动作层的数据互补使用。

## 复现

```bash
python3 scripts/corrupt_pairs.py --plan    # 只打印 60 条 (处境, 规则) 计划
python3 scripts/corrupt_pairs.py --retry   # 生成 60 次 + 对失败处各重写两次，写全部落盘文件
```

重跑幂等：已生成过的处境跳过；`verification()` 与 `summary.json` 每次都从 `calls.jsonl` 重算，不调 API 也能复核任何一对。
