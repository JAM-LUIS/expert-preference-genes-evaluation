# EXCLUSIONS — 预注册剔除清单

> R1 中性版（2026-09-28）：由 v5 同名文件派生。规则一到规则三逐字保留 v5 原文；
> 最后一节（MAMO 欠定题）的 v5 原文逐题引用了 test 题，R1 工作树不收录，建 R1 时也没有打开，这里只留结论和机读文件的位置。
> v5 原件留在出处副本 `PROVENANCE/v5_pristine/data/EXCLUSIONS.md`（不入库），两边的 SHA-256 见 `PROVENANCE/v5_anchor_hashes.json`。
> 下文提到的 `DECISIONS.md`、`RECORDS.md` 指 v5 的文件（同样只在出处副本里）。R1 的剔除和分析集合由 E14 另建（`data/splits_r1/`、`data/exclusions_r1.json`）。

规则见 `DECISIONS.md` 的"预注册剔除规则"。本文件只列被剔除的 id 与理由；不剔除的观察写在 `RECORDS.md`。

## 规则一：参考答案无法数值化，且不含 infeasible / unbounded 字样

2026-09-05 核对结果：**无剔除**。

| 来源 | n | n_reference_numeric | 剔除 |
|---|---|---|---|
| mamo_complex_lp | 211 | 211 | 0 |
| industryor | 100 | 100 | 0 |

两个来源的 `Answer` / `en_answer` 字段全部是裸数值字符串（最长 18 字符，无句子、无第二个数字），
所以 loader "取最后一个数" 的启发式在这里不可能取错。

## 规则二：数据集自带类型字段标明非线性 → 保留但单独报告

- `mamo_complex_lp`：`Type` 字段 211 条全为 `complex_lp`，没有非线性标记，无法据此分层。
- `industryor`：只有 `difficulty`（Easy / Medium / Hard），没有题型字段。数据卡说覆盖 LP / IP / MIP / NLP / other，
  但这个信息没有进文件，因此**无法自动分层**；如需按题型报告只能事后按错误分类近似。

## 规则三：生成程序 60 s 超时 → 记为执行失败，四条件同等对待，不剔除

## MAMO ComplexLP 的欠定题 —— 已决定：**保留，不剔除**（作者 2026-09-05）

- 机读文件：`data/mamo_underspecified_ids.json`（关键词粗筛，规则 `mamo_underspec_keyword.v1`，是下界、不是核实过的标签）。
- 主表用全集；这个文件只供附录的 well-specified 子集次要分析使用（`analysis/paired_bootstrap.py --subset`）。
- v5 原文本节的逐题说明涉及 test 题，见上方说明，R1 不收录。

## R1：分析集合的剔除（E14，2026-09-28）

规则见 R1 的 `DECISIONS.md` R1-D6；机读文件是 `data/analysis_sets/analysis_sets.v2.json`、`data/splits_r1/*/removed_ids.json` 和（标注导入后）`data/exclusions_r1.json`。

- **MAMO 清洗删掉的 100 题**（LLM4OR 清洗版不保留的题）：dev 30 / test 70，不补题、不重抽，只从主分析子集里去掉，仍在全量敏感性分析里；
  题号见 `data/splits_r1/mamo_main_clean111/removed_ids.json`。
- **9 月 5 日核对参考答案时看过题面的 9 道 test 题**：从主分析和其他敏感性分析剔除，只进 `sens_incl0905`、`sens_full211_incl0905` 两个结果：
  `industryor-0014`、`industryor-0041`、`industryor-0061`、`industryor-0066`、`mamo_complex_lp-0022`、`mamo_complex_lp-0070`、`mamo_complex_lp-0149`、`mamo_complex_lp-0151`、`mamo_complex_lp-0184`
  （MAMO 清洗子集里只有 0022；另 4 道 MAMO 题已被清洗删掉）。
- **IndustryOR 的 NL_NOT_LINEARIZABLE 题**：保留但单独报告，不进主表，不计入 MDE 样本量；题号等两人独立标注和裁决后由 `data/ingest_annotations.py` 写入。
- **参考答案核对结论为 AMBIGUOUS、UNDERSPECIFIED 的题**：移出主分析，只留在全量敏感性分析里（R1-D5 的 Q3 规则）；题号同样由导入脚本写入。
