# 隔离提示 / ISOLATION NOTICE

## 写 gene 的人和 agent 不得打开本目录和 hidden 目录。
## People and agents who write genes must not open this directory or the hidden directory.

- 本目录：`stage1/annotation_agent/`，参考答案核对与 IndustryOR 题型标注的"盲包"。里面有 125 道题的题面（MAMO ComplexLP 25 题 + IndustryOR 100 题，其中 test 题 93 道），**没有参考答案**。
- hidden 目录：`stage1/annotation_agent_hidden/`，放参考答案、题面来源文件，以及之后的比对结果、裁决表和导入文件。
- "写 gene 的人和 agent"包括：起草、修改、审阅 gene 的人和会话，调提示词、做 dev 错误分类的人和会话。这条规则在 test 运行之前一直有效。

## 谁可以打开什么

| 人 / agent | 本目录 | hidden 目录 |
|---|---|---|
| 复算 agent（A 批 8 个、B 批 8 个） | 只读写分给自己的那一组目录 `batch_<批>/<组>/`，其他一律不读 | 不得打开 |
| 协调人（主会话；不写、不审 gene） | 运行 `scripts/` 下的脚本；不必打开题面文件 | 只通过脚本处理；脚本只打印题号、计数和哈希 |
| 裁决人（代号 C，Qi Deng；不参与 gene） | 不需要 | 只打开协调人发给他的 `adjudication/` |
| 写或审阅 gene、调提示、做 dev 错误分类的人和 agent | **不得打开** | **不得打开** |

## 哪些文件有题面、哪些有答案

| 文件 | 题面 | 参考答案 |
|---|---|---|
| `batch_*/*/<题号>.txt` | **有**（含 test） | 没有 |
| `batch_*/*/results.jsonl`、`batch_*/*/models/`（复算 agent 生成） | 可能引用 | 没有（是复算值，不是参考答案） |
| `batch_*/*/REDERIVATION_INSTRUCTIONS.md`、`REDERIVATION_INSTRUCTIONS.md` | 没有（示例是自拟小题） | 没有 |
| `case_set.json`、`groups.json` | 没有（题号、划分、分组、题面哈希） | 没有 |
| `README_ISOLATION.md`、`BUILD_NOTES.md`、`INGEST_E13_E14.md`、`scripts/` | 没有 | 没有 |
| `MANIFEST.sha256`（每个目录一份） | 没有（文件哈希） | 没有 |
| hidden `references.json` | 没有 | **有**（含旧版本答案） |
| hidden `source_cases/` | **有** | **有**（R1 中性版 cases 文件的只读副本） |
| hidden `comparison/`（compare.py 生成） | 没有 | **有**（和两批复算值） |
| hidden `adjudication/`（make_adjudication.py 生成，交裁决人） | **有** | **有** |
| hidden `ingest/`（export_for_ingest.py 生成，交 R1 导入） | 没有 | **有**（`ref_check.csv` 里的原值和更正值；只有题号、结论、数值） |
| hidden `selfcheck/`（selfcheck.py 生成） | 没有 | 间接有（哪个数字与哪题的答案相同） |

## 使用限制

- 不要把题面粘贴进本流程以外的任何 AI 会话或在线服务（聊天机器人、在线求解器、在线翻译）。复算 agent 不上网。
- 许可：MAMO ComplexLP 为 CC BY-SA 4.0（FreedomIntelligence/Mamo@2c91069）；IndustryOR 为 CC BY-NC 4.0（HF CardinalOperations/IndustryOR，revision b00811923f167cdf4ae1677c33cd61d4eea78f48）。这里只用于非商业的研究核对。
- 不提交到任何公开仓库；裁决人的副本在任务结束后按协调人要求删除。

## 流程（协调人）

1. 建包和自检（已完成）：`python3 scripts/build_blind_package.py`，`python3 scripts/selfcheck.py`。
2. 主会话派 16 个复算 agent：A 批 A01–A08 用 Fable 5.1，B 批 B01–B08 用 Opus 5.5。每个 agent 只给它的组目录路径和一句"读该目录里的 REDERIVATION_INSTRUCTIONS.md 并照做"；最好不给联网工具。
3. 两批都交回后：`python3 scripts/compare.py --model A=<模型 ID> --model B=<模型 ID>`（先可加 `--allow-incomplete` 看进度）。125 题全部与参考答案比对：66 道抽样题按"两批都与参考一致才自动 CORRECT"处理；抽样以外的 59 道 IndustryOR 题只有 A、B 彼此一致而都与参考不一致时才交裁决（全量筛查发现），其余保留原参考值、只统计一致率。
4. `python3 scripts/make_adjudication.py`，把 hidden `adjudication/` 整个文件夹交给裁决人。裁决表分"抽样核对""全量筛查""只定题型"三页，按来源分开列。
5. 裁决表交回后：`python3 scripts/export_for_ingest.py --sheet <填好的 adjudication_C.xlsx>`，再按 `INGEST_E13_E14.md` 导入 R1。

各步骤的细节、规则和已做的核对见 `BUILD_NOTES.md`。
