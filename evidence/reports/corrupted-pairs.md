# 定向破坏偏好对（第二版）

由 `python3 scripts/corrupt_pairs.py` 生成，本文件里的每个数字都是那次运行的输出。
chosen 是带整部法的真实回答，rejected 是按模板最小改写、只破坏一个可判子项的那一份；
破坏内容与目标规则的对应由构造保证（一个子项一个模板一条规则，见 `evidence/corrupted2/rule-map.json`）。

## 总量

- 造出的对数（模板产出了候选的处境×子项）：139
- 四项全过的对数：124
- 单因性比例：0.8921（accepted / attempted，attempted 是模板至少产出一个候选的 (处境,子项) 对数）
- 相似度：最低 0.8603，均值 0.9696

## 逐类丢弃

| 子项 | 造出 | 通过 | 丢弃 | 无候选 |
|---|---|---|---|---|
| phase.unauthorized_actions | 0 | 0 | 0 | 174 |
| phase.discussion_as_advance | 0 | 0 | 0 | 174 |
| evidence.unlabeled_inferences | 2 | 2 | 0 | 172 |
| evidence.assert_before_prove | 0 | 0 | 0 | 174 |
| question.environment_questions | 41 | 40 | 1 | 133 |
| question.stops_before_gate | 9 | 2 | 7 | 165 |
| delivery.checkable_artifacts | 83 | 78 | 5 | 91 |
| delivery.unrecorded_changes | 4 | 2 | 2 | 170 |

## 丢弃原因汇总

- 目标子项没翻转：24 次候选被拒
- 带动其他子项：15 次候选被拒
- 文本不完整或劣质：10 次候选被拒

## 通过的分布

- delivery.checkable_artifacts：78 对（规则 change.upkeep.resolvable）
- delivery.unrecorded_changes：2 对（规则 intent.decisions.disclose_changes）
- evidence.unlabeled_inferences：2 对（规则 precedence.own_inference）
- question.environment_questions：40 对（规则 intent.user_model.unanswerable_only）
- question.stops_before_gate：2 对（规则 attention.delivery.ship_at_gate）

## 规则覆盖

覆盖 5/8 条法规则：

- attention.delivery.ship_at_gate
- change.upkeep.resolvable
- intent.decisions.disclose_changes
- intent.user_model.unanswerable_only
- precedence.own_inference

没有产生任何对的规则：proof.execution.only_authorized、attention.phases.turn、resources.split.preflight

## 判定器自测

自测通过：True

## 限制

- 可判子项是正则计数，不是模型判读：一对能被判为单因，只说明这八个计数器只动了一个，不说明改写后的回答在语义上只差这一处；逐对的 `edit_note` 写着改了哪一段、为什么它违反目标规则，复核可人读核对。
- 三类没有一对，原因是模板的前置条件在原回答里不成立：(a) phase.unauthorized_actions 需要原回答有变更动作、全部已授权、门前有停下的话，且回答里点过一个可核对的路径；b) phase.discussion_as_advance 需要这一轮是讨论轮、原回答有改动且全部合格，而把只读动作改成变更动作只有在对象名出现在用户轮里时才不改动unauthorized_actions，这几乎遇不到；c) evidence.assert_before_prove 在原回答里要么不适用（没有变更动作），要么已经是最差值、无法再坏一个方向。这三类记 0 是对数据的诚实结果，不是通过。
- 类别之间数量极不均衡：delivery.checkable_artifacts 有 78 对，evidence.unlabeled_inferences 只有 2 对，因为保留语几乎都出现在带依据的句子里，删掉保留语同时会让那句变成无依据断言之外的东西，被单因性判据挡下。
- 模板是确定性文本变换，不调用模型，因此改写不会引入模型风格的漂移，但也只能在原回答里找到现成的改写点时成立；找不到就没有候选，这不是通过。
- 同一处境可能出现在不同子项的多个对里，因为破坏点不同；data/pairs-corrupted2.jsonl 里每对只带一个 subitem，使用时请按子项分组，不要当作处境之间相互独立。
