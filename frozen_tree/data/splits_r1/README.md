# data/splits_r1/

由 `tools/derive_splits_r1.py` 从 `data/analysis_sets/analysis_sets.v2.json` 生成，每个集合一个目录。规则（D5、D7 按 R1 修订）：

- dev = 冻结划分的 dev ∩ 集合，test = 冻结划分的 test ∩ 集合；没有题换边，删掉的题只删不补、不重新抽样。
- 冻结划分 `data/splits/<benchmark>/` 只读，原样保留；这里的锁记下父锁的相对路径和 sha256、cases 路径和 sha256（沿用父锁）、
  集合来源文件的 sha256、子集哈希、dev/test 题号哈希和题数，以及被删掉的题（`removed_ids.json`）。
- 生成时断言题数和 dev/test 题号哈希与集合文件里记的相同；已存在且内容不同的目录拒绝覆盖。

| 目录 | dev | test | 删掉的 dev / test |
|---|---|---|---|
| mamo_main_clean111 | 30 | 81 | 30 / 70 |
| mamo_sensitivity_full211 | 60 | 151 | 0 / 0 |
| industryor_main_rev2026_100 | 25 | 75 | 0 / 0 |
| mamo_main_clean111_excl0905 | 30 | 80 | 30 / 71 |
| industryor_main_rev2026_100_excl0905 | 25 | 71 | 0 / 4 |
| mamo_sensitivity_full211_excl0905 | 60 | 146 | 0 / 5 |

核对：`$ORGENE_PY tools/derive_splits_r1.py --check`；`analysis/check_test_isolation.py` 也逐个核对这些锁。
