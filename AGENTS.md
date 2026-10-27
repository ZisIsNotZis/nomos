# nomos

这个节点拥有 `nomos` 的路线图：把一份个人操作法（`agent-policy` 里 264 个叶子的法）用 242 条真实处境筛出的
288 条样本压进一个 2B 模型的权重，并测量它到底有没有进去、代价是不是通用能力。尺子这一端已经能分开
（同一批 148 条处境、每处境每侧 9 条抽样，带法减不带法的差是 0.0593 [0.0263, 0.0923]，不含 0），
所以留给本节点的问题不是「尺子能不能量」，而是「量出来的东西到哪里为止」。

## 入口

- **当前事实与路线**：`docs/0_ROADMAP.md`（里程碑 M1–M6、工作包、闸与开销）。
- **一句话状态**：`docs/2_GOAL.md` 的读数表；**主张与边界**：`docs/5_PRODUCT.md`。
- **要 person 判的**：`docs/5_PRODUCT.md`「要 person 判的那一件事」。
- **仓库怎么跑**：`docs/9_IMPLEMENTATION.md`（命令、环境、记账、证据指针）。
- 往上一层：`mail/` 是和 root / person 的往来信原件（授权的边界、¥10 口径、验收线的原话都在那里，**不删**）；
  `inbox/` 是工作收件，读过的信落地即删。

## 与通用约定不一样的地方（覆盖）

- `inbox/` 里没有 `README.md`，也不该有——信的四个头行是 `kind:`（resource / cost / direction / contract / report）、
  `from:`、`spend:`、`id:`（写它答的是哪一封），文件名 `inbox/YYYY-MM-DD-<slug>.md`，正文一句结论开头、末尾写 effort；
  不写 `to:`。读信先落地（事实进 `docs/`、命令执行、答不了的转投上一层 `inbox/` 并带上 `id:`）再删文件，
  删信与落地同一次提交，`inbox/` 跟着仓库进版本控制。
- **`evidence/reports/` 是证明，不是层文档**：那里是每次运行的推导与逐条明细；当前数值只在 `docs/2_GOAL.md`，
  主张只在 `docs/5_PRODUCT.md`。`evidence/reports/plan-historical.md` 是项目早期的工作包状态快照，别当路线图读、也别回填它。
- `evidence/reports/measurements.md` 的花费表只增行、不改旧行；本机 GPU 墙钟单列在「本机 GPU（不计钱）」。
- 许可原文按「字节数 + sha256 + 取回 URL」登记在 `README.md` 的「许可」与 `THIRD-PARTY.md`。
- `scripts/measure_anchor.py --analyse` 每跑一次会往 `evidence/measure/anchor-draws9/run.log` **追加**一行 `cmd:`，
  所以那个文件不标 hash，是允许脏着出现在 `git status` 里的路径之一。另一处是 `evidence/benchmark/logs-*/` 的
  `driver.log`、`driver.out` 与逐格日志：跑的时候它们一直在长，脏着就是「跑着」，不是漂移。
- 没有上一层的话**不推**：提交可以只留在本机（发布本身已获授权，最后一次推是 `74793ff`）。
- 长期运行只能 detached 在 `setsid` 的 driver 上，等待靠 driver 自己写完成信到 `inbox/`；
  不能用后台任务加「结束 turn 等通知」，也不能 `sleep`。
- `evidence/benchmark/official/vendor/**` 是逐字节的第三方源码与 README（Apache-2.0，未改一字），
  不按本仓库的文档规则改写。
