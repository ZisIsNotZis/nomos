# 数据质量

类型：结果。所有者：主代理。上游：[设计](../docs/method/design.md) 第 3 节。

## 结论

- 183 条生成的双答对里 **9 条不入账**：6 条两侧做的是同一个动作，3 条的工具调用没有收尾。留下 **174 条**，落 `data/pairs-filtered.jsonl`。
- 复读、回显各 **0 条**；判据与检测方式见下，检测跑过全部 366 条回答。
- 174 条处境各标 1–4 条可训练规则，共 **666 个标注**；175 条可训练规则里 **98 条零覆盖、26 条只被 1 条处境覆盖**。
- 零覆盖的两个来源用两次诊断分开：把每条处境的标注容量从 4 提到 8，零覆盖降到 66，即 **34 条规则只是排在第五名之后**；完全不设上限时 **175 条规则全部被至少一条处境提到**。所以零覆盖首先不是“处境里找不到可违反这条规则的地方”，而是容量与排名把它们挤出了前四条；但长尾仍然是真的稀薄——不设上限时也有 50 条规则各只被 2–3 条处境提到——这类规则治理的活动在这 51 个会话里本来就少，不靠加样本解决，清单当已知不足进训练。

## 判据

### 实质相同

归一化：删掉 Markdown 围栏标记行，连续空白压成一个空格，去首尾空白。词集：汉字按单字、ASCII 按 `[a-z0-9_]+` 取词并小写。以下任一条成立即判实质相同：

- **甲**：归一化后两串完全相等。
- **乙**：长度比 `min/max >= 0.85` 且词集 Jaccard `>= 0.85`。

阈值 0.85 落在这一批数据的空隙里，不凭感觉选：词集 Jaccard 从高到低是 1.00、0.94、0.93、0.89、0.89、0.88，下一条 0.80，再往下 0.74；长度比在这 6 条上分别是 1.00、0.86、0.92、0.91、1.00、0.95，都在 0.85 以上。全部 183 条的度量在 `evidence/data-quality/pair-metrics.jsonl`，改阈值可以直接复算。

这 6 条被判同动作的，差异都只是参数细节：`SIT075` 一条多搜了 `*.yaml`，`SIT081` 一条多一个关键词，`SIT132` 一条多 `timeout` 参数，`SIT133` 两条 glob 顺序不同，`SIT161` 一条 `head -20` 一条 `head -30`，`SIT003` 两条逐字相同。它们在法这一层没有偏好可学。

已知漏网，如实留下：`SIT167`（Jaccard 0.80，两条都是对同一批目标 `grep`）、`SIT150`（0.74）、`SIT086`（0.74）也是同型动作，但它们的度量与真正不同的 `SIT028`（0.72，两条命令查的是不同目录）同在一段，阈值再降就开始误丢。`SIT001` 两条是同一动作的中文与英文两个版本，文本重合度低，判据抓不到；留着当噪声。

### 截断

以下任一条成立：

- **甲**：`tool: name(...)` 的参数括号或引号不闭合，用 JSON 感知的扫描判（引号内的括号不计，反斜杠转义）。
- **乙**：最后一个非空白字符不是终止符（句号、问号、感叹号、右括号、引号、星号等）。
- **丙**：Markdown 围栏数为奇数。

三条都属甲。独立核对：`evidence/slice-contrast/answers.jsonl` 里 `finish_reason == "length"` 的正好是 `SIT144` 的带法回答与 `SIT177` 的不带法回答两条，与这儿判出的两条一致；`SIT120` 的带法回答是 `stop`，属于模型自己把 `write` 的 `content` 字符串写坏，末字是 `\` 转义的引号，缺少收尾引号，JSON 解析不出来。

### 复读

同一句（归一化后 ≥20 字）或同一行（≥20 字）在一条回答里出现 3 次以上；另加一个更宽的检查：8 个词的连续片段出现 3 次以上。两个检查在 366 条回答上都命中 0 条。`SIT111` 的两条回答里同一个文件路径出现 3 次，但那是同一条命令里的参数，不是复读。

### 回显

回答里没有任何工具调用，且与处境原文（整段，不只最后一轮）的最长连续重合 ≥40 字、占回答归一化长度 ≥60%，即回答只是把原文重复一遍而没有行动。366 条回答命中 0 条。`SIT017` 的 `tool: read(/tmp/mycar-handoff.md)` 从用户轮里抄了 22 字路径，但它是动作，且短于 40 字。

## 逐条丢弃

证据原文（含尾部引文）在 `evidence/data-quality/dropped.jsonl`。side 指被丢的哪一侧。

| 处境 | side | 原因 | 一句证据 |
|---|---|---|---|
| `SIT003` | 两侧 | 实质相同 | 归一化后两串完全相同：`tool: bg_result({"taskId": "<HEX>"})` |
| `SIT075` | 两侧 | 实质相同 | 长度比 0.86、词集 Jaccard 0.94；差别只是 `--include` 多一个 `*.yaml` |
| `SIT081` | 两侧 | 实质相同 | 长度比 0.92、Jaccard 0.93；差别只是多一个关键词 `upper` |
| `SIT132` | 两侧 | 实质相同 | 长度比 0.91、Jaccard 0.89；差别只是一侧多 `"timeout": 30` |
| `SIT133` | 两侧 | 实质相同 | 长度比 0.95、Jaccard 0.88；差别只是 glob 顺序与 `webm` |
| `SIT161` | 两侧 | 实质相同 | 长度比 1.00、Jaccard 0.89；差别只是 `head -20` 与 `head -30` |
| `SIT120` | chosen | 截断 | `write` 调用结尾是 `…按此处理而非删除。\"})`，字符串没闭合，JSON 解析失败 |
| `SIT144` | chosen | 截断 | 尾部是 `'\"'\"'\"'…` 的转义失控，`finish_reason` 为 `length` |
| `SIT177` | rejected | 截断 | 尾部停在 `# reject if any active danmaku in same lane still near`，`finish_reason` 为 `length` |

## 标注

- 候选集是 `constitution/nodes.json` 里 `trainable` 为真的 **175** 个叶子。其余 89 个不可训练（工具/宿主绑定、概念与定义），没有动作可训练，不作候选。
- 一次调用给模型 175 条 `dot path — 原文` 与一条处境，要求只从候选里选 1–4 条，选的是“如果被违反，下一个回合会走错”的那几条，按处境里真实出现的决策点选，不按关键词重合。模型 `deepseek-flash`，温度 0，thinking 关。
- 每条处境的输入哈希、原文回答、解析结果与 usage 在 `evidence/coverage/calls.jsonl`；运行的模型、温度、候选集哈希、系统消息哈希与筛后样本哈希在 `evidence/coverage/run-meta.json`（`pairs_sha256` 就是现在这份 `data/pairs-filtered.jsonl` 的哈希，标注绑定在这一版数据上）。脚本 `scripts/annotate_coverage.py` 读 `data/coverage.json` 跳过已标注的处境，可续跑，`--force` 重标。
- 结构校验在脚本里：路径必须来自候选集、去重后 1–4 条、覆盖若干处境。实际有 2 次输出写了不存在的 `dot path`（`attention.phases.discussion.conclusion_only`、`attention.communication.user_language`），被打回重写，`calls.jsonl` 里留着 `ok=false` 的两行。
- 174 条处境里有 **144 条用满 4 条**，其余 30 条用 3 条，没有一条用 1–2 条。也就是说这一版标注实际是在排前四名，不是在判“是否触发”。

## 覆盖分布

覆盖计数落 `data/coverage-counts.json`，由 `data/coverage.json` 重算而来，`situations` 174、`rules` 175、`tags` 666，分布相加等于 666。

| 覆盖的处境数 | 规则条数 |
|---|---|
| 0 | 98 |
| 1 | 26 |
| 2 | 18 |
| 3 | 4 |
| 4 | 4 |
| 5 | 7 |
| 6 | 1 |
| 7 | 1 |
| 9 | 2 |
| 10 | 2 |
| 11 | 1 |
| 12 | 1 |
| 17、24、26、39、46、49、54、56、63、93 各 1 条 | 10 |

标注集中在“下一步该不该做、该不该问”这一类：前 12 条规则占 490 个标注（74%），最多的是 `attention.phases.discussion.act_now` 93 条、`attention.phases.discussion.round` 63 条、`attention.phases.discussion.divergence` 56 条。按第一层节点分：attention 397、intent 143、change 39、proof 35、laws 19、resources 16、precedence 14、practice 3。

### 覆盖数为 0 的 98 条

- laws（3）：`laws.projection`、`laws.no_op`、`laws.top_down`
- intent（14）：`intent.objective.product_bar.surface`、`intent.objective.mechanism_triad`、`intent.objective.true_metric`、`intent.decisions.hold_the_goal`、`intent.decisions.fixed_milestones`、`intent.decisions.disclose_changes`、`intent.decisions.question_frontier`、`intent.roles.product_owner.align`、`intent.roles.worker`、`intent.roles.sub_owner`、`intent.risk.absorb_risk`、`intent.risk.secrets`、`intent.risk.covered_once`、`intent.risk.decide_as_user`
- resources（21）：`resources.efficiency.defect_surface`、`resources.efficiency.one_name`、`resources.split.logical_level`、`resources.split.logic_is_physical`、`resources.split.persist_split`、`resources.split.route_failure`、`resources.split.coverage_and_interfaces`、`resources.split.dispatch_identity`、`resources.split.dispatch_inheritance`、`resources.split.dispatch_grant`、`resources.split.preflight`、`resources.scheduling.start_early`、`resources.scheduling.overlap_waits`、`resources.effort.seriousness`、`resources.effort.earned_budget`、`resources.effort.budget`、`resources.effort.fresh_context`、`resources.environment.diagnose_network`、`resources.environment.structure_is_absolute`、`resources.environment.reproduce`、`resources.environment.readme_tested`
- attention（16）：`attention.phases.advance.unit_size`、`attention.phases.advance.silent_change`、`attention.phases.advance.few_milestones`、`attention.phases.advance.review_scope`、`attention.delivery.presentable`、`attention.delivery.readme`、`attention.delivery.poc`、`attention.delivery.ship_at_gate`、`attention.delivery.gates_hold`、`attention.communication.ask_the_gap`、`attention.communication.ignored_domains`、`attention.communication.tldr`、`attention.communication.report_only_effect`、`attention.communication.match_user`、`attention.communication.human_voice`、`attention.communication.multimodal_review`
- change（16）：`change.entries.fact_provenance`、`change.entries.assent`、`change.entries.no_mood_labels`、`change.entries.fabricated`、`change.entries.defined_terms`、`change.entries.no_manual_wrap`、`change.shape.granularity`、`change.upkeep.rule_form`、`change.upkeep.resolvable`、`change.upkeep.migrate`、`change.upkeep.archive`、`change.upkeep.render`、`change.upkeep.ops`、`change.upkeep.adopt`、`change.record.wind_down`、`change.record.keep_evidence`
- practice（12）：`practice.design.caller_complexity`、`practice.design.abstraction_cost`、`practice.design.dependency_isolation`、`practice.feature`、`practice.diagnosis.unavailable_repro`、`practice.diagnosis.diagnosis_closure`、`practice.refactor.caller_migration`、`practice.testing.test_scope`、`practice.testing.test_doubles`、`practice.research.primary_evidence`、`practice.research.evaluation_integrity`、`practice.research.experiment_record`
- proof（16）：`proof.execution.only_authorized`、`proof.execution.separate_preexisting`、`proof.execution.gate_probe`、`proof.execution.measurement.intrinsic_benchmark`、`proof.execution.measurement.operational_load`、`proof.review.falsify`、`proof.review.judgement_only`、`proof.review.scoped_review`、`proof.review.no_commit`、`proof.review.three_kinds`、`proof.review.unverified`、`proof.review.blocked`、`proof.review.report_incomplete`、`proof.process.baseline`、`proof.process.subagent_scope`、`proof.process.model_cost`

### 覆盖数为 1 的 26 条

- laws（1）：`laws.self_improvement.strongest_cure`
- precedence（2）：`precedence.trust_is_earned`、`precedence.watch_for_poison`
- intent（6）：`intent.scope.trace_requirements`、`intent.scope.commitment`、`intent.decisions.replan_lower`、`intent.decisions.substitute_design`、`intent.decisions.consequential`、`intent.risk.preserve_work`
- resources（4）：`resources.scheduling.finite_concurrency`、`resources.environment.local_config_first`、`resources.environment.artefacts_home`、`resources.environment.regeneration_cost`
- attention（5）：`attention.phases.discussion.consequential_only`、`attention.phases.discussion.announce_long`、`attention.delivery.protect_willingness`、`attention.delivery.milestone_list`、`attention.delivery.invent_no_gate`
- change（4）：`change.entries.split_authorship`、`change.entries.current_fact`、`change.record.durability`、`change.record.resume`
- practice（1）：`practice.diagnosis.reproduce_minimize`
- proof（3）：`proof.execution.bind_to_revision`、`proof.review.reviewer_contract`、`proof.process.change_hypothesis`

## 覆盖不足的诊断

两次诊断只改标注容量，模型、候选集、处境、温度都不变，所以差异归给容量：

| 标注方式 | 每条处境上限 | 标注总数 | 每条处境 | 零覆盖 |
|---|---|---|---|---|
| 交付用的标注 | 4 | 666 | 3.83 | 98 |
| 容量加大 | 8 | 1158 | 6.66 | 66 |
| 不设上限 | 175 | 2874 | 16.52 | 0 |

证据：`evidence/coverage/`、`evidence/coverage-cap8/`、`evidence/coverage-uncapped/`，各有 `coverage.json`、`coverage-counts.json`、`calls.jsonl`。

- **构造方式确实占一部分**：容量从 4 提到 8，34 条原本零覆盖的规则被标上（`resources.split.dispatch_identity`、`resources.split.preflight`、`change.upkeep.migrate`、`intent.decisions.fixed_milestones`、`proof.process.model_cost` 这一类），说明它们在这些处境的决策点里成立，只是排在第五名到第八名。反过来有 2 条在 8 条容量下掉出（`change.entries.split_authorship`、`change.record.resume`），这是同一模型换容量重标的出入，规模 ±2 条。
- **“本来就少”也成立**：不设上限时 175 条全部被提到，但这只证明每条规则至少与一条处境的决策点有关，不证明它们常见。不设上限的分布仍然极偏：最热 5 条各被 122–159 条处境提到，而 50 条规则各自只在 2–3 条处境里出现（`attention.delivery.poc`、`attention.communication.human_voice`、`attention.communication.multimodal_review`、`change.upkeep.archive`、`change.upkeep.adopt`、`resources.environment.readme_tested`、`practice.testing.test_doubles`、`proof.review.falsify` 等）。这 51 个会话是一名单用户的工程会话，发布、文档迁移与归档、子代理契约、评测与实验记录这些活动在其中的下一个回合里很少成为决策点。
- **处方**：不加样本。同一批会话里再切窗口，切出来还是同样的活动，零覆盖不会因此下降；样本量解决不了活动缺席。真要提升尾部规则的训练信号，只能改标注构造——按“会被违反的规则全标”会让每条处境涨到 16 条左右，其中大部分是每一步都适用的通用规则，训练信号被稀释；或者对低覆盖规则定向找处境，那是换语料而不是加样本，需要另立一项目标。当前构造接受分布不平衡，DPO 阶段应知道这 98 条没有偏好信号。

## 已知局限

- 实质相同的阈值有漏网：`SIT167` 这类同型动作、`SIT001` 这类跨语言同一动作仍留在数据里，见“判据·实质相同”。
- 复读与回显是词法判据：换一种说法复述处境，判据抓不到。回显 0 条只说明没有逐字回显。
- 标注是模型判断，单次、无第二评委；容量从 4 到 8 有 ±2 条规则进出，所以覆盖数只当分布看，不当精确计数。
- 标注只看处境，不看 chosen/rejected 两条回答；一条处境标上的规则说明这个决策点落在法里，不说明训练对能教会它。
- 覆盖不足是语料诊断，不是训练效果证据；尾部规则没有偏好信号这件事本身要在 DPO 之后的评测里另说。

## 复算

```bash
python3 scripts/filter_pairs.py
python3 scripts/annotate_coverage.py                     # 需要 DEEPSEEK_API_KEY；已标注的处境跳过
python3 scripts/annotate_coverage.py --max-tags 8 --tag-dir evidence/coverage-cap8
python3 scripts/annotate_coverage.py --max-tags 0 --tag-dir evidence/coverage-uncapped
```

覆盖计数与标注一致性的检查（不调 API）：

```bash
python3 - <<'PY'
import json
coverage = json.load(open('data/coverage.json'))
counts = json.load(open('data/coverage-counts.json'))
rules = [n['dot_path'] for n in json.load(open('constitution/nodes.json')) if n['trainable']]
per = {p: sum(p in v for v in coverage.values()) for p in rules}
assert per == counts['counts'] and counts['situations'] == len(coverage) == 174
assert counts['tags'] == sum(map(len, coverage.values())) == 666
assert counts['zero'] == [p for p in rules if per[p] == 0]
print('coverage.json / coverage-counts.json 一致：174 条处境，666 条标注，175 条规则')
PY
```

标注总共调用 550 次、花 ¥1.65（`evidence/*/calls.jsonl` 里逐次 usage 与单价）。
