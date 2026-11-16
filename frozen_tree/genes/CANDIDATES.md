# CANDIDATES — 想写但暂不入库的 gene

> R1 中性版（2026-09-28）：由 v5 同名文件派生。改动只有三处：人名改为"作者"；gene 库文件名改为 R1 工作库 `genes.r1.jsonl`；
> 第 2 节删去 v5 原文顺带引用的一道 test 题（test 题的信息不进 gene 作者读的文档），相应改写了那两句。其余文字未改。
> v5 原件与本文件的 SHA-256 对应见 `PROVENANCE/v5_anchor_hashes.json`（出处目录不入库）。

入库门槛（作者 2026-09-06 定）：**触发 dev 案例 ≥ 3**，且写得出可执行谓词。达不到的写在这里，
留着等 dev 上出现更多触发案例、或等作者决定放宽。**本文件里的规则不进 gene 库（`genes.r1.jsonl`），不进合同，不影响任何实验。**

## 1. `orgene.constraints.cover_requirement_sentences` —— **不入库**（作者 2026-09-06 定）

规则：spec 里的约束条数应当 ≥ 题面中"要求句"的条数（含 at least / at most / exactly / must /
cannot / no more than / not exceed / minimum of / maximum of / up to / should be 等提示词的句子）。
动机：dev C0 的 48 道错题里 **missing_constraint 占 17 道**，是最大的一类。

谓词 `predicate.constraints_cover_requirements.v1` 已经写进 `runtime/orgene/genes.py` 并可调用，
但**没有对应的 gene 行**，所以它不在活跃集里、不参与任何实验。

**不入库的两条理由（作者拍板）：**
1. **精确率只有 0.60。** 在 dev C2（85 题、64 题答错）上，能凑够 3 例触发的最低设置是 `ratio = 1.5`，
   此时 3 次命中里有 2 次落在答对的题上；放到 `ratio = 2.0` 触发 12 例，精确率同样是 0.60。
   一条五次里错两次的检查，进了合同只会往修复消息里灌噪声。
2. **不在 dev 上扫阈值。** 按原本的写法（`ratio = 1.0`）只触发 1 例，低于 3 例门槛。
   把阈值调到 1.5 或 2.0 纯粹是为了够门槛，那是拿 dev 反复试出来的数，不是从失败里读出来的规则。
   这种调参一旦进了库，dev→test 的泛化就没有依据了。

要重新考虑这条规则，应当换一个**结构化**的判据（例如把每条约束对回题面的具体句子，检查是否有要求句没有被任何约束引用），
而不是继续调 `ratio`。

## 2. `orgene.variables.integrality_from_semantics`（dev 只触发 1 例，且那 1 例是基准自己的错）

规则：可数的东西（份数、台数、人数、趟数、整包）应当声明为整数变量。
dev 上唯一相关的案例是 `mamo_complex_lp-0189`，但它其实是**基准参考值本身有问题**：
参考值 19.0 既不等于连续松弛最优 19.2176，也不等于整数最优 22.0（两者都用 CBC 复算过）。
也就是说这条规则在 dev 上没有一个干净的触发案例，写进去反而会被一个错误的参考值牵着走。

v5 原文此处还拿另一道题作对照，说明 MAMO 内部对整数性没有一致约定；那道题属于 test，R1 版删去该例。
仅就 dev 而言，`-0189` 的参考值更接近连续解。
**在基准自己可能都不一致的情况下，任何整数性规则都可能把对的改成错的**，所以不入库。
现有种子 gene `orgene.variables.domain_consistent` 已经在检查 spec 与代码的整数性是否一致，
那是"自洽"检查，不是"该不该取整"的判断，保持现状。

## 3. 明确不写的规则

- **子回路消除（subtour elimination）**：dev 上 `-0087`/`-0097` 因为没排除自环 + 没消子回路而得到 0。
  但这是 TSP 这个**问题族专属**的规则，作者定的硬约束是"只写通用建模规则，不写任何案例或问题族专属文本"
  （旧稿 P2 的 C4 就是这么死的）。已入库的 `orgene.objective.aggregates_declared_variables` 和
  `orgene.code.sparse_index_guard` 从索引集一致性的角度覆盖了一部分同类失败，不再单独写 TSP 规则。
- **"最大流目标 = 源点净流出"** 没有写成 TSP/最大流专属条文，而是抽象成
  `orgene.objective.aggregates_declared_variables`：目标若是总量就必须对索引集聚合，不能只取家族里的一个元素。
  这条在 dev 上触发 8 例、精确率 1.00，且措辞里不出现任何问题族名称。
