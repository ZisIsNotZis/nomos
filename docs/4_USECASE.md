# 用例

## EXPLICIT

无。person 没有以用例形式给过要求；下面是从目标与验收线读出来的。

## CONFIRMED

无。

## INFERRED

### 1. 读者：一条命令验证主张

**谁**：拿到仓库的人（评审、读者、作者本人）。
**场景**：不装 torch、不联网、不碰 GPU，只想看主指标是不是真的。
**流程**：读 `README.md` 的「结果一行」→ 跑 `python3 scripts/measure_actions.py --analyse`（3.17–3.33 s）→
读出 `n_pairs 148/242`、`post_mean`、Δ 与区间 → 想深一层就读 `docs/2_GOAL.md` 的表和 `evidence/reports/`。
**验收**：重跑后 `git status` 干净；`evidence/measure/summary.json` 逐字节相同
（唯一会变的是 `models.*` 的绝对路径，从别处 clone 会看到那里的路径）。

### 2. 评审：把主张的每一句按到证据上

**谁**：独立复核者（fresh context、只读）。
**场景**：怀疑「−12.2pp」是自己那把尺子的产物，或怀疑某一句把没测的轴讲成了已测。
**流程**：跑 `python3 scripts/check_axes_claim.py`（退出码 0 才算主张面合规）→
跑 `python3 evidence/benchmark/official/grade_official.py`（热环境 7.5–13 s，重跑逐字节相同）→
对数字：`evidence/benchmark/paired-ifeval.json`、`evidence/benchmark/official/official-ifeval.json`、
`evidence/measure/summary.json`、`evidence/measure/seen-heldout.json`。
**验收**：每个量化主张都能在产物里找到同值字段；找不到就是缺陷，写成一条 reproduction。

### 3. person：判定交付物换不换

**谁**：person（决定交付物与验收线）。
**场景**：2-epoch 与 3-epoch 两个适配器在政策轴分不开，而 IFEval 掉幅差 4.4pp。
**流程**：读 `docs/2_GOAL.md` 的两轴表 → 读 `docs/5_PRODUCT.md`「要 person 判的那一件事」→
回答「换 / 不换」以及「文字层那 −3.55pp 算不算实质差别」。
**验收**：判定落进 `docs/5_PRODUCT.md`；换则重写引用面的当前读数，不换则把那条写进论文限制。

### 4. 本节点：跑下一包

**谁**：本节点（或派发的 worker）。
**场景**：要新读数（新适配器、新轴、新套件）。
**流程**：按 `docs/0_ROADMAP.md` 的工作包写预登记（假设、方法、继续/停止阈值、不做什么）→
跑（长跑必须 detached，driver 自己写完成信到 `inbox/`）→ 落地证据 → 按 `docs/9_IMPLEMENTATION.md` 记账 →
把当前读数更新进 `docs/2_GOAL.md`、把推导留在 `evidence/reports/`。
**验收**：预登记的阈值先写死再跑；跑完按阈值判，不按结果改阈值。

### 5. 作者：换一份法重跑

**谁**：法演进之后的作者。
**场景**：`agent-policy` 有了新版本，想把新法压进去。
**流程**：按 `docs/6_ARCHITECTURE.md` 的流水线重建数据 → 训练 → 政策测量 → 两条通用轴 → 更新
`constitution/` 的冻结件与 `docs/2_GOAL.md` 的当前读数。
**验收**：prompt 不含法条原文的断言仍通过；两侧上限与本轮一致；旧读数降为「前一次估计」而不是删掉。
