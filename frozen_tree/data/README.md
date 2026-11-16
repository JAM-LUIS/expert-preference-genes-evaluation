# data/

> R1 中性版（2026-09-28）：由 v5 同名文件派生。改动：删去第 32–33 行关于一道 test 题的补充说明；许可一节删去机构名称；
> 其余逐字保留（下文的 `DECISIONS.md`、`RECORDS.md`、`EXCLUSIONS.md` 末节指 v5 的记录，原件在出处副本 `PROVENANCE/v5_pristine/`，不入库）。
> R1 的 `data/cases/*.jsonl` 与 `splits/*/SPLIT_LOCK.json` 是中性版：只把第 1 行 `_header.raw_path` 和 `cases_path` 改成相对路径（`cases_sha256` 随之更新），
> 题目记录（第 2 行起）和 dev/test 题号文件与 v5 逐字节相同。生成程序的解释器固定为 `$ORGENE_PY`（默认 `/opt/homebrew/bin/python3`），下文命令里的 `python3` 按此理解。

`raw/` 放下载的原始基准文件（不入库、不发布）；`cases/` 是 `orgene_cli.py cases` 生成的规范化案例；`splits/` 是冻结的 dev/test 划分；`smoke/` 是 3 题作者自写的冒烟案例（CC0，参考值已用 CBC 核实，只做冒烟，不是证据）。

## 下载与记录（每个来源都要在下表填一行，写进 RECORDS）

| 来源 | 获取方式 | 版本/commit | license | 数值参考率 | 记录日期 |
|---|---|---|---|---|---|
| mamo_complex_lp | `git clone --depth 1 https://github.com/FreedomIntelligence/Mamo` → `data/optimization/Complex_LP/mamo_complex_lp.jsonl` | commit `2c91069dee5c1e4db4b899eb176ec987d0251bb3`（2024-06-12）；文件 sha256 `07eb3db3d2af099871dfa4425b14887775179c158c38944fe4fe152b615bbfc3`；211 题 | CC-BY-SA-4.0（仓库 LICENSE） | 211/211 = 1.00 | 2026-09-05 |
| mamo_easy_lp | 同上 → `data/optimization/Easy_LP/mamo_easy_lp.jsonl`（可选，只用于扩 dev；652 题，未转换） | 同上 commit | CC-BY-SA-4.0 | 未转换 | 2026-09-05 |
| industryor | `curl -sL -o data/raw/industryor/IndustryOR.json https://huggingface.co/datasets/CardinalOperations/IndustryOR/resolve/<sha>/IndustryOR.json` | HF revision `b00811923f167cdf4ae1677c33cd61d4eea78f48`（lastModified 2026-05-03）；文件 sha256 `5b889e49d9aa64ae5b368bc80a05ee71a1daf20d126f54efc6207c98f9095f36`；100 题 | **CC-BY-NC-4.0**（数据卡 `license:` 字段已核实，2026-09-05） | 100/100 = 1.00 | 2026-09-05 |
| nl4opt（可选） | 用 LLMOPT / ORLM 发布的带参考值版本；记录来源与 license | 未做 | | | |

原始文件字段：MAMO 是 `id, Question, Answer, Category, Type`（`Type` 全为 `complex_lp`）；
IndustryOR 是 JSON **数组**（不是 JSONL），字段 `en_question, en_answer, difficulty, id`，
loader 的 `read_raw` 已能处理数组。两者的 `Answer` / `en_answer` 都是裸数值字符串。

## 转换与检查

```sh
python3 runtime/orgene_cli.py cases --source mamo_complex_lp --raw data/raw/Mamo/data/optimization/Complex_LP/mamo_complex_lp.jsonl --out data/cases/mamo_complex_lp.jsonl
python3 runtime/orgene_cli.py cases --source industryor --raw data/raw/industryor/IndustryOR.json --out data/cases/industryor.jsonl
head -1 data/cases/mamo_complex_lp.jsonl   # header: n, n_reference_numeric, question_key, answer_key
```

检查：
1. `n_reference_numeric / n` 应接近 1；非数值参考且不含 infeasible/unbounded 的题按 `DECISIONS.md` 剔除，id 写进 `data/EXCLUSIONS.md`。
2. 随机抽 10 题，人工确认 `reference.objective` 是最优目标值而不是某个决策变量的值（含句子的答案 loader 取最后一个数，可能取错）。
   2026-09-05 已做（种子 20260905，MAMO 5 题 + IndustryOR 5 题）：7 题独立建模用 CBC 复算，目标值与参考值**完全一致**
   （mamo 0022 / 0184，industryor 0014 / 0041 / 0061 / 0066 / 0094）；参考值确实是最优目标值，不是决策变量值。
   另外 3 题（mamo 0070 / 0149 / 0151）题面缺数据、无法复算，见 `EXCLUSIONS.md` 末节。
   （v5 原文此处还有一行关于某道 test 题整数性的补充说明，涉及具体 test 题，R1 中性版删去。）
3. 数据集自带类型字段（如 `Type`、`difficulty`）保留在 `extra` 里，分析时可分层。

## 冻结划分

```sh
python3 runtime/orgene_cli.py split --cases data/cases/mamo_complex_lp.jsonl --out data/splits/mamo_complex_lp --n-dev 60 --seed 20260905
python3 runtime/orgene_cli.py split --cases data/cases/industryor.jsonl --out data/splits/industryor --n-dev 25 --seed 20260905
```

`SPLIT_LOCK.json` 里的 `cases_sha256 / dev_sha256 / test_sha256` 写进 RECORDS。之后 `--force` 只允许在任何 test 运行发生之前使用，并记 RECORDS。

2026-09-05 已冻结：mamo_complex_lp 60 dev / 151 test，industryor 25 dev / 75 test，种子 20260905。hash 见 RECORDS。

## 许可与发布

- MAMO：CC BY-SA 4.0，可随代码发布转换后的案例文件，保留署名与相同方式共享声明。
- IndustryOR：license 为 **CC BY-NC 4.0**（2026-09-05 核实数据卡）。非商业条款——学术研究与论文发表属非商业使用，
  但为稳妥起见**不随发布包分发转换后的案例文件**；代码库只给上面那条下载命令与 id 映射，
  并在论文数据可得性声明里写明该数据集的 NC 条款。也不要把它和 CC BY-SA 的 MAMO 案例混进同一个打包文件。
- 冒烟案例：CC0。
