# 计划

类型：计划。所有者：主代理。上游：[设计](../method/design.md)。

全线是工作包，不是里程碑：没有用户确认点，一个工作包做完直接投入下一个，中间的检查由独立复核子代理做。DPO 备选见 [backlog](backlog.md)。

## 工作包：训练数据与质量

**产出**：`data/sft.jsonl`（处境原文作 prompt、带法回答作 target；同一处境按动作签名去重，同签名只留一条，再挡一层 target 词集 Jaccard ≥ 0.9 的近重复）、`report/sft-data.md`。

**验收**：prompt 只含处境，运行时断言不含法条原文；每条带处境 id 与会话 id；坏件（截断、复读、回显）与同处境重复样本（逐字重复、动作签名相同、近重复）丢弃并计数；按会话切出验证集，同一会话不跨两侧；175 条可训练规则的覆盖数重算落盘。

**依赖**：无。数据在 `evidence/densify/answers.jsonl`（735 条带法回答）与 `mining/candidates.jsonl`。

## 工作包：SFT 训练

**产出**：`scripts/train_sft.py`、`report/sft-training.md`、适配器权重与哈希。

**验收**：4-bit QLoRA；只对 target 算 loss，掩码在运行时逐条断言；序列长度按实测 p95；至少 20 步、loss 有限；LoRA 参数收到非零梯度有断言；显存与耗时按实况记录。

**依赖**：训练数据与质量。

## 工作包：loss 与 PPL

**产出**：逐 epoch 的训练与验证 loss/PPL 曲线，落 `evidence/sft/log.jsonl`。

**验收**：曲线在收敛区间；训练集与验证集的差距报出来；要证明的是跑通并学到东西，不是学会法。

**依赖**：SFT 训练。

## 工作包：三点测量

**产出**：同一批处境上三个水平的动作一致率——带法 DeepSeek（定义上 100）、训练前 Qwen3.5-2B、训练后，落 `report/sft-measurement.md`。

**验收**：三水平同批处境、同采样协议、同解码参数；每处境多次抽样；报每处境的 `X = (qwen − base)/(100 − base)` 与区间；rubric 作为辅助照报不照判；同时报一个不依赖评委的可数对照。

**依赖**：SFT 训练。

## 工作包：benchmark

**产出**：开源套件（先测 headroom，30–70% 才用）训练前后各一次，落 `report/sft-benchmark.md`。

**验收**：每个数带区间；掉出噪声才叫掉。

**依赖**：SFT 训练。

## 工作包：发布准备

**产出**：权重卡、数据卡、`docs/paper/draft.md`、README 的一条命令、`artifacts.tsv`。

**验收**：README 那条命令自己跑过并写下实测时间；preprint 每个数字能在 `report/` 找到；不外传，上传要用户授权。

**依赖**：三点测量与 benchmark。

## 约束

- 显卡在 2026-10-31 之后是否可用未确认，机器上另有项目占用约 16 GB，重活按实时占用定，必要时 detached 跑并等。
- 处境池封死在 242 条、51 个会话；样本量靠多次抽样扩。
- 单模型单次抽样本身不确定，基线要多次抽样报区间。
