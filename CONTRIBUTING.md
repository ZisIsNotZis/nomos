# 贡献

一句话：**能复现的数才是数**。这个仓库的每个数字都指向 `evidence/` 里落盘的原始输出，所以改代码、改数、改主张三件事必须一起走。

## 范围

- 有意义的改动：测量与分析的脚本、判分器、自检与门、证据目录里的复算脚本、文档里的事实更正。
- 需要先开的改动（issue 里先说清代价）：换参照物、换套件、扩处境池、动 LoRA 配置或切分。这些会改「主张能说什么」，不只是改代码。
- 不要提交：权重（`.tmp/` 是可删临时区）、新的 CI 配置（本仓库没有 CI，检查都是本机命令）、与法条作者私有会话未脱敏的原文。

## 跑什么检查

分析侧只要 Python 3.12.3 与标准库，不用装任何东西。动手之前，五条离线检查都要是 0：

```
python3 scripts/measure_actions.py --check
python3 scripts/measure_split.py --check
python3 scripts/bench_selftest.py
python3 scripts/check_axes_claim.py
python3 constitution/verify_gate.py
```

改到发布面（`README.md`、模型卡、论文、`docs/5_PRODUCT.md`）时，`check_axes_claim.py` 是必跑的：它逐句检查「没测的轴有没有被当已测讲」，含糊措辞会让它失败。

训练与生成要 GPU（单卡 4090、torch + transformers + peft + bitsandbytes），长跑必须挂在 `setsid` 的 driver 上，等它自己写完成信，不要用后台任务加 sleep：

```
python3 scripts/train_sft.py --epochs 3 --grad-accum 8 --lora-r 16 \
  --lora-alpha 32 --lora-targets narrow --adapter-dir .tmp/sft/adapter-narrow
```

## 提 PR 时

1. **带证据指针**：新增或改动的数要能在 `evidence/` 里找到落盘输出与重算命令；没有落盘输出的数不进正文。
2. **不覆盖冻结件**：`evidence/measure/summary.json`、`evidence/benchmark/paired-*.json` 是交付证据；试验跑用 `--tag` / `--adapter-tag` / `--out-tag` 另开名字。
3. **一个原子单元一个提交**，提交信息用现在这套中文 Conventional Commits（`docs:`、`chore:`、`fix:` 加一句人话结论）。
4. **同一个事实只有一个家**：当前数值只有 `docs/2_GOAL.md`，主张只在 `docs/5_PRODUCT.md`，推导在 `evidence/reports/`；改一处要顺着引用面全改完。
5. **工作区必须干净**：跑完 `git status --short` 要是空的（`evidence/measure/anchor-draws9/run.log` 与 `evidence/benchmark/logs-*/driver.*` 是跑的时候会追加的例外路径）。
6. **别动 `evidence/benchmark/official/vendor/`**：那是 upstream 的逐字节拷贝，程序每次运行时校验 sha256，改了会让运行失败而不是悄悄改数。

## issue

- 能复现的缺陷最有价值：给命令、给退出码、给 `evidence/` 里对应的文件。
- 质疑结论请直接攻击口径：区间、检出下限、参照物的自洽度、多重比较、用哪把尺子——这些都在正文里写着，比「我觉得不对」有用得多。
- 这个仓库只有一名作者维护，回复可能慢；授权、花费与验收线由作者判定，不在这张表里。

## 许可

贡献按 **AGPL-3.0-only** 授权；第三方数据与基座的许可见 [`THIRD-PARTY.md`](THIRD-PARTY.md) 与 README 的「许可」。
