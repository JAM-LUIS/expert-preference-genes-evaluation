# data/reference_overrides/

参考答案核对结论的覆盖文件（E13 读取、计分；E14 的 `ingest_annotations.py` 按下面的格式生成）。每个来源一个文件：
`<source>.json`（如 `industryor.json`、`mamo_complex_lp.json`）。目录里只有本说明时，打分一律用原参考值。
文件只含题号、结论、数值、代号和哈希，**不含题面，也不允许自由文本字段**（依据、备注可能引用题面，读取时会拒绝未知字段）。

## 计分规则（R1 DECISIONS R1-D5；代码 `runtime/orgene/refs.py` 的 `SCORING_RULES`，摘要 `rules_sha256()`）

| 结论 | 打分用的参考值 | 主分析 | 另报 |
|---|---|---|---|
| CORRECT | 原值 | 进 | — |
| CORRECT_ROUNDED | 核对得到的精确值（`new_value`） | 进 | 用原值打分的结果 |
| INCORRECT（两人一致或经裁决） | 更正值（`new_value`） | 进 | 用原值打分的结果 |
| AMBIGUOUS、UNDERSPECIFIED | 原值 | **移出**，只留在全量敏感性分析 | — |
| 没抽到 | 原值 | 进 | — |

容差：`|obj − ref| ≤ max(t, t·|ref|)`，绝对容差和相对容差取同一个值 t；三档 1e-6、1e-4、1e-2，主口径 1e-4（结果行的 `correct`）。

非数值参考值（2026-09-29 冻结前定）：程序打印的 STATUS 和参考值都先归到类别（`score.status_category`：optimal、infeasible、unbounded、infeasible_or_unbounded、local_*、other），只有类别完全相同、而且是 infeasible 或 unbounded 时判对；infeasible_or_unbounded（如 COPT 的 INF_OR_UNB、参考值 "No Best Solution"）和 local_*（如 COPT 的 LOCAL_INFEASIBLE）一律不判对。数值参考值仍只比较打印的目标值。结果行另有 `status_category`、`status_undecided`、`reference_category`，metrics 有 `n_status_undecided`。这条规则也在 `SCORING_RULES` 里（`non_numeric_reference`），所以规则摘要随之改变。

## 格式

```json
{
 "schema": "orgene.reference_overrides.v1",
 "source": "industryor",
 "cases_sha256": "<data/cases/industryor.jsonl 的 sha256（R1 中性版）>",
 "rules_sha256": "<refs.rules_sha256()>",
 "entries": [
  {"case_id": "industryor-0000", "original_value": 100.0, "new_value": 104.5, "verdict": "INCORRECT",
   "checkers": ["A", "B"], "method": "independent_agreement", "adjudicator": "",
   "date": "2026-10-01", "evidence_sha256": "<依据文件的 sha256>"}
 ]
}
```

- `original_value` 必须与 cases 文件里该题的参考值完全相同（数值，或 `infeasible` / `unbounded`，或 null），否则拒绝（防止覆盖文件和 cases 版本对不上）。
- `new_value`：数值、`infeasible`、`unbounded` 或 null。CORRECT_ROUNDED、INCORRECT 必须给，而且必须超出原值的主容差（在容差内就应该是 CORRECT）；CORRECT 如果给了，必须在主容差内；AMBIGUOUS、UNDERSPECIFIED 给了也不用于打分。
- `checkers`：核对人代号列表（A、B、C 这样的短代号，不写姓名）。CORRECT 以外的结论至少两人；`method` 取 `independent_agreement`、`single_check_correct`（只能配 CORRECT）、`discussion`、`adjudication`（须填 `adjudicator` 代号）。
- `date`：YYYY-MM-DD；`evidence_sha256`：依据文件的 sha256，一个或一个列表。
- 同一题只能出现一次；题号必须在 cases 文件里；`cases_sha256`、`rules_sha256` 必须与当前 cases 文件和代码一致。
- 用 `refs.build_overrides_doc(source, cases_path, entries)` 生成并校验，`refs.write_overrides(doc, path)` 以固定格式写出（`json.dumps(indent=1, sort_keys=True, ensure_ascii=False)` 加换行），哈希稳定，可直接进冻结清单。

## 打分时怎么用

- `orgene_cli.py score --overrides auto`（默认）：有 `data/reference_overrides/<source>.json` 就用；`--overrides none` 用原值；也可给路径。
- `--freeze-manifest FREEZE_MANIFEST.json`：覆盖文件必须列在清单里且 sha256 相同；清单列了但文件不在、文件在但清单没列、哈希不同，都拒绝打分。清单格式可以是 `{"files": {"data/reference_overrides/industryor.json": "<sha256>"}}`、`{"files": {"<path>": {"sha256": "<sha256>"}}}` 或 `{"files": [{"path": ..., "sha256": ...}]}`。`--overrides-sha256` 直接给期望哈希。
- 结果行新增：`correct_tol`（三档，对有效参考值）、`correct_original_ref`、`correct_tol_original_ref`（对原值）、`reference_original_objective`、`reference_original_status`、`reference_verdict`、`reference_version`（`original` 或 `override@<文件 sha256 前 16 位>`）、`reference_main_eligible`。`reference_objective` / `reference_status` 是打分实际用的（有效）参考值。
- metrics 新增：`tolerance_tiers`、`accuracy_by_tol`、`n_correct_by_tol`、`accuracy_original_ref`、`n_correct_original_ref`、`reference`（规则摘要、覆盖文件的路径和哈希、被覆盖题数、移出主分析题数、各结论题数）；`by_source` 同样有分档准确率。
