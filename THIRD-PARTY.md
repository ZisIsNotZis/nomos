# 第三方数据与许可

本仓库随代码分发两份第三方 benchmark 数据：`data/bench/gsm8k.jsonl` 与 `data/bench/ifeval.jsonl`。两份都是原数据集的抽样冻结件，许可原文落 `licenses/`，本文是它们的署名与变更声明。来源、许可名与源文件 hash 同时记录在 `data/bench/sources.json`（程序读的那一份），本文不复制它的字段以外的内容。

## GSM8K（`data/bench/gsm8k.jsonl`）

- **数据集**：GSM8K（Grade School Math 8K），OpenAI，2021。
- **许可**：MIT。原文 `licenses/gsm8k-MIT.txt`（1062 字节，sha256 `86bbb73e855821d7c401912fd4bf82e34313e6e3b6fd6f909f2b6cc9e209a53b`），取自 <https://raw.githubusercontent.com/openai/grade-school-math/master/LICENSE>，版权行 `Copyright (c) 2021 OpenAI` 原样保留。
- **数据来源**：<https://raw.githubusercontent.com/openai/grade-school-math/master/grade_school_math/data/test.jsonl>（源文件 sha256 `3730d312f6e3440559ace48831e51066acaca737f6eabec99bccb9e4b3c39d14`）。
- **引用**：Cobbe et al., *Training Verifiers to Solve Math Word Problems*, arXiv:2110.14168，<https://arxiv.org/abs/2110.14168>。
- **改动**：从 test 划分里按 `sha256("0:"+id)` 升序取前 200 条；每条加 `id`（`gsm8k-test-<原索引>`），把原文 `answer` 里 `####` 之后的 gold 数抽成 `answer_number`，原文自然语言解法未随发放。题目正文未改。
- **冻结件**：200 条，sha256 `def2e3a03b1893d9bfddd792cf5e8eed7fa62db2a0ba3662882a5af0f986c1d3`。

## IFEval（`data/bench/ifeval.jsonl`）

- **数据集**：IFEval（Instruction-Following Eval），Google Research，2023。
- **许可**：Apache-2.0。原文 `licenses/Apache-2.0.txt`（11358 字节，sha256 `cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30`），取自 <https://www.apache.org/licenses/LICENSE-2.0.txt>；数据集卡 <https://huggingface.co/datasets/google/IFEval> 声明 `license: apache-2.0`。
- **数据来源**：<https://huggingface.co/datasets/google/IFEval> 的 `ifeval_input_data.jsonl`（源文件 sha256 `6a85310ca8ce15eff755aa08a3a4ff931c7e273e7515ebb3c492ea85fd8288f2`），上游代码库 <https://github.com/google-research/google-research/tree/master/instruction_following_eval>。
- **引用**：Zhou et al., *Instruction-Following Evaluation for Large Language Models*, arXiv:2311.07911，<https://arxiv.org/abs/2311.07911>。
- **改动**（按 Apache-2.0 §4(b) 声明）：541 条候选中只保留 295 条，判据是它携带的每种指令类型都能被 `scripts/bench_suites.py` 的检查器判定，246 条因此排除；每条加 `id`（`ifeval-<原 key>`），`prompt`、`instruction_id_list`、`kwargs` 原样保留。
- **NOTICE**：上游数据集没有 NOTICE 文件，故不另附；Apache-2.0 的署名与许可声明以本节加 `licenses/Apache-2.0.txt` 为准。
- **冻结件**：295 条，sha256 `0cc0fb5726c3aa6ec9053aec2bfc8615ed631150e54cee492c0f2f963dcdf71e`。

## Apache-2.0 的保留义务

再分发 IFEval 抽样件时，Apache-2.0 §4 要求随附本许可原文副本、保留版权与署名声明、并声明改动；本目录的 `licenses/Apache-2.0.txt` 与本文的「改动」一条是这两项义务的落点。GSM8K 的 MIT 要求版权声明与许可声明随所有副本或实质部分保留，`licenses/gsm8k-MIT.txt` 即该声明。

## 不含在本声明里的东西

- 基座模型 `Qwen/Qwen3.5-2B` 是 Apache-2.0，它的许可义务写在 [模型卡](docs/model-card.md)「许可」，不在本文件。
- 处境与回答来自法条作者本人的私有会话（脱敏后进仓库，见 [数据卡](docs/data-card.md)），DeepSeek 生成的内容受其服务条款约束。
- 本仓库自身的代码与文档是 AGPL-3.0-only（作者 2026-10-21 指定，见 [README](README.md) 的「许可」一节）；本文件的第三方数据许可与基座模型的 Apache-2.0 与它并行，不因它而改变。
