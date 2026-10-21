# 计划

类型：计划。所有者：主代理。上游：[设计](../method/design.md)。

全线是工作包，不是里程碑：没有用户确认点，一个工作包做完直接投入下一个，中间的检查由独立复核子代理做。DPO 备选见 [backlog](backlog.md)。

## 工作包：训练数据与质量

**产出**：`data/sft.jsonl`（处境原文作 prompt、带法回答作 target；同一处境按签名去重，同签名只留一条——动作签名非空时用动作类型串，为空时用「是否提问/是否停住等确认/是否下断言/是否有可核对产物」四位文字层签名，四位相同且 target 词集 Jaccard ≥ 0.9 才合并——再挡一层签名不同但 target 词集 Jaccard ≥ 0.9 的近重复）、`report/sft-data.md`。

**验收**：prompt 只含处境，运行时断言不含法条原文；每条带处境 id 与会话 id；坏件（截断、复读、回显）与同处境重复样本（逐字重复、动作签名相同、近重复）丢弃并计数；按会话切出验证集，同一会话不跨两侧；175 条可训练规则的覆盖数重算落盘。

**依赖**：无。数据在 `evidence/densify/answers.jsonl`（735 条带法回答）与 `mining/candidates.jsonl`。

**状态**：完成。`data/sft.jsonl` 366 条 = 训练 288 / 验证 78，735 条 law 回答丢弃 369 条（截断 3、逐字 94、同动作签名 244、同文字层决策 28、近重复 0）；按会话组切分 10 组、种子 20261020；覆盖 77/175（下界）；运行时断言与两个负控都通过。结果见 [SFT 数据](../../report/sft-data.md)。

## 工作包：SFT 训练

**产出**：`scripts/train_sft.py`、`report/sft-training.md`、适配器权重与哈希。

**验收**：4-bit QLoRA；只对 target 算 loss，掩码在运行时逐条断言；序列长度按实测 p95；至少 20 步、loss 有限；LoRA 参数收到非零梯度有断言；显存与耗时按实况记录。

**依赖**：训练数据与质量。

**状态**：完成。窄版适配器 `.tmp/sft/adapter-narrow/`（r=16、alpha=32、10 911 744 个可训练参数、43 675 104 字节、sha256 `5be6a2f3…`），3 epoch = 54 步、828.6 秒。宽版对照见 [挂宽 LoRA](../../report/sft-training-wide.md)：验证 PPL 6.0923 差于窄版 6.0325，后续测量用窄版。结果与显存实测见 [SFT 训练](../../report/sft-training.md)。

## 工作包：loss 与 PPL

**产出**：逐 epoch 的训练与验证 loss/PPL 曲线，落 `evidence/sft/log.jsonl`。

**验收**：曲线在收敛区间；训练集与验证集的差距报出来；要证明的是跑通并学到东西，不是学会法。

**依赖**：SFT 训练。

**状态**：完成。`evidence/sft/log.jsonl` 66 行（54 步 + 3 个 epoch 的验证）+ `evidence/sft/train-summary.json`：验证 PPL 11.34 → 6.03，训练 PPL 4.21，训练/验证 loss 差 0.1057 → 0.3596 且第三 epoch 验证侧只降 0.037——收敛在验证侧变平。曲线与读法见 [SFT 训练](../../report/sft-training.md)。

## 工作包：三点测量

**产出**：同一批处境上三个水平的动作一致率——带法 DeepSeek（定义上 100）、训练前 Qwen3.5-2B、训练后，落 `report/sft-measurement.md`。

**验收**：三水平同批处境、同采样协议、同解码参数；每处境多次抽样；报每处境的 `X = (qwen − base)/(100 − base)` 与区间；rubric 作为辅助照报不照判；同时报一个不依赖评委的可数对照。

**依赖**：SFT 训练。

**状态**：完成（终版）。三水平同批 242 条处境、同 prompt、同解码（0.7 / 0.95 / 320、每侧 3 条）；一致率 base 0.0023 → post 0.0968，Δ 0.0946 [0.0586, 0.1351]，n_pairs = 148/242；X = 0.0948 [0.0564, 0.1332]；可数对照（有可解析动作的比例）5.6% → 75.2%；格式/决策分解与两个并列口径同报。含同解码锚点（888 次调用、¥0.7115）：带法 0.3311、不带法 0.2815、差 0.0496 [−0.0068, 0.1059]，尺子量不出法的作用。见 [三点测量](../../report/sft-measurement.md)。

## 工作包：benchmark

**产出**：开源套件（先测 headroom，30–70% 才用）训练前后各一次，落 `report/sft-benchmark.md`。

**验收**：每个数带区间；掉出噪声才叫掉。

**依赖**：SFT 训练。

**状态**：完成本轮约定的一半。四格 base/adapter × GSM8K/IFEval 都跑了，但 n 从约定的 100 降到 20（单条 23.3–35.9 s，装不进 25 分钟预算）：GSM8K 75.0% → 65.0%（−10.0pp [−30.0, +10.0]，p 0.625）、IFEval 60.0% → 40.0%（−20.0pp [−40.0, 0.0]，p 0.219）。结论只写「没有可信的下降证据」，且这个 n 只看得见 ≳20pp；全量与 n=100 未跑，续跑命令在报告里。见 [benchmark](../../report/sft-benchmark.md)。

## 工作包：发布准备

**产出**：权重卡、数据卡、`docs/paper/draft.md`、README 的一条命令、`artifacts.tsv`。

**验收**：README 那条命令自己跑过并写下实测时间；preprint 每个数字能在 `report/` 找到；不外传，上传要用户授权。

**依赖**：三点测量与 benchmark。

**状态**：完成，未外传。[模型卡](../model-card.md)、[数据卡](../data-card.md)、[preprint 草稿](../paper/draft.md)、README 的「一条命令」自跑过并计时，读数就是下面这一条：命令 `python3 scripts/measure_actions.py --analyse`，环境 Python 3.12.3、12 核、纯 CPU、不联网、只用标准库，修订 `9048e62`；本机工作树两次 **3.28 s / 3.33 s**，全新 `git clone` 到 `/tmp` 后两次 **3.19 s / 3.33 s**（`/usr/bin/time -f '%e'` 计时，含解释器启动）；工作树每次跑完 `evidence/measure/summary.json` 的 sha256 仍是 `0e10e6f4…`、`git status --short` 空，clone 里同一命令只改 `models.*` 的绝对路径，所以 README 写「约 3.3 秒」并引用本条；`artifacts.tsv` 三条（DPO r16、SFT 窄版、SFT 宽版）的 sha256 校验通过，durable location 写明没有第二份、只留重生成命令。Zenodo / Hugging Face / GitHub release 上传都需要用户授权，一条都没做。

## 约束

- 显卡在 2026-10-31 之后是否可用未确认，机器上另有项目占用约 16 GB，重活按实时占用定，必要时 detached 跑并等。
- 处境池封死在 242 条、51 个会话；样本量靠多次抽样扩。
- 单模型单次抽样本身不确定，基线要多次抽样报区间。
