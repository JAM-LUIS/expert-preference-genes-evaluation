# data/analysis_sets/

- `analysis_sets.v2.json`：阶段 1 数据任务生成的分析集合文件（v2，2026-09-28 17:42 版，含 `_excl0905` 集合），逐字节复制，
  sha256 `6baf6b7f8678e78f12884f5775ebbfda8d4b396e9b793abee6133f1462a5205d`。只有题号和 dev/test 归属，没有题面、没有模型结果。
  题号哈希的写法与 `SPLIT_LOCK.json` 相同：`sha256(json.dumps(sorted(ids)))`。
- 这个文件不改。要换版本就另存新文件名，同时更新 `configs/analysis_set_defs.r1.json` 里记的路径和 sha256（`runtime/orgene/analysis_sets.py` 会拒绝哈希不符的文件），并在 RECORDS 记录。
- 用法：
  - 每个集合落到冻结划分上的子集锁：`$ORGENE_PY tools/derive_splits_r1.py`（`--check` 只核对不写），产物在 `data/splits_r1/<集合名>/`。
  - 分析用的组合集合（main、各敏感性集合、dev 口径集合）定义在 `configs/analysis_set_defs.r1.json`，由 `runtime/orgene/analysis_sets.py` 解析；代码里不写题号。
  - 题型标签和参考答案核对结果到位后，用 `data/ingest_annotations.py` 生成 `data/labels/`、`data/reference_overrides/`、`data/exclusions_r1.json`；在这之前依赖它们的集合（main 等）状态是"待定"，严格模式下拒绝使用。
