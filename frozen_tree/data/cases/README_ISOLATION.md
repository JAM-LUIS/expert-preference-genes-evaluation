# 隔离说明：哪些文件写 gene 的人不得打开

本文件本身不含任何题面、参考值或实例名，写 gene 的人可以读。

## 适用对象

- 写 gene 的人和会话（1C 的 gene 开发、gene 审阅），以及任何根据 dev 结果调提示或调 gene 的会话。
- 下文统称"写 gene 的人"。实施和协调的会话只要不写 gene 就不受此限，但也不在任何输出、日志、测试里打印这些文件的内容。

## 不得打开的文件

| 路径 | 内容 | 为什么 |
|---|---|---|
| `data/cases/*.jsonl` | 全部题面和参考值：MAMO、IndustryOR（含 test 题）、工程来源案例 `eng.jsonl` | test 题和工程来源题只在冻结后跑一次 |
| `data/eng/`（整个目录） | 工程来源案例的题面模板（`pglib_uc_render.py`）、MIPLIB-NL 拼接文字（`miplib_nl_convert.py`）、参考模型（`reference/`）、参考值（`reference_values.json`、`eng_hashes.json`）、选例记录（`selection.json`，含实例名）、来源清单（`sources/`） | 模板和参考模型等于题面和标准答案 |
| `data/raw/`（不入库） | 下载的原始基准文件和 CBC 日志 | 同上 |
| `data/reference_overrides/` | 参考答案覆盖（含 test 题号和更正后的参考值） | 主会话 2026-09-28 决定：写 gene 的会话只通过 score 使用 |

`data/ingest_eng.py` 里没有题面文字（只有来源地址、选例规则和流程），可以打开；它和 `analysis/check_test_isolation.py` 一样只打印题号、计数和哈希。

## 可以读的

- 题号：`data/splits/*/dev_ids.json`、`test_ids.json`、`eng_holdout_ids.json`，以及各 `SPLIT_LOCK.json`。
- dev 题的题面：只通过 dev 运行的请求和输出看（`experiments/*-dev-*`），不直接打开 cases 文件。

## 工程来源案例（E22）的额外规定

- 归属 `eng_holdout`（`data/splits/eng/`）：不属于 dev 也不属于 test。gene 开发、dev 调参、AlphaOPT 学习都不能用；冻结并登记后只跑一次，单独列表。
- 运行目录名用 `-eng_holdout-` 标明（例如 `<日期>-<模型>-eng-eng_holdout-<配置>`）；`check_test_isolation.py` 跳过这类目录，同时检查 dev 请求、gene 的 `devCaseIds` 和 `activation.devEvidence`、`conditions/`、`genes/` 里都没有这些题号。
- 请求、校验、打分三步都过 E21 的 test 闸门（`--split eng_holdout` 或题号在 `eng_holdout_ids.json` 里就触发）。
- PGLib-UC 的题面由模板脚本从实例数据确定性生成，不由人或模型撰写。**待办**：请一位不写 gene 的人通读这两道题面（只核对措辞与数据表是否清楚、一致，不改题面；如需改模板，改模板版本号并重新生成、重新登记哈希）。
