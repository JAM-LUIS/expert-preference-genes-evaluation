v5 出处：DECISIONS.md sha256 `2435c35aa9e7e1d717e546b62437664cd49e6d02d29a12943869cc8d70d7d970`；RECORDS.md `2082c1fbd801aa4fc60f21b356f7c462de97c444102e7697a87f408c90c89b35`；HANDOFF.md `2e4e143064058441d9691873c12960043ecfe534cac05e3f039fac740411e576`（原件在 `PROVENANCE/v5_pristine/`，不入库）。

# HANDOFF — ORgene R1

给下一个接手的会话。决策见 `DECISIONS.md`，过程和数字见 `RECORDS.md`，逐项改法见工程方案（仓库外，E01–E22）。

## 1. 现在的状态（2026-09-28）

- E01（工作区与出处哈希）、E02（路径、解释器、禁用 v5 脚本、git）已完成；E14 里的 neutralize 一步（cases 头行、SPLIT_LOCK）也已完成。
- E14（分支 r1/e14）：子集锁 `data/splits_r1/`、分析集合定义 `configs/analysis_set_defs.r1.json`、隔离检查扩大范围、标注导入接口 `data/ingest_annotations.py`、规模特征脚本 `analysis/r1/scale_features.py`。
  题型标注和参考答案核对结果还没到，main 等 test 集合是"待定"；规模特征要等 E09 分词器和 E12 求解记录再生成。
- 回归：pytest 84 passed（v5 原有 55 个全部保留），selftest PASS，v1.0 锚点 15/15 复现，隔离检查 PASS。
- 其余各项（E03–E13、E14 的其余部分、E15–E22）都还没有开始。
- （2026-09-29 补）第一批 E03、E04、E05、E08、E09、E12、E13、E14、E19、E21 已合并进 main（标签 `wave1`，RECORDS R1-R6 至 R1-R8），
  合并后的后续改动见标签 `wave1-followups` 和 RECORDS R1-R9 起；当前的测试数以 RECORDS 最新一条为准。上面几行是合并前的状态。

## 2. 目录

| 路径 | 进 git | 说明 |
|---|---|---|
| runtime/ analysis/ conditions/ schema/ tools/ | 是 | 工作代码；schema v3 不变 |
| genes/genes.r1.jsonl、genes/CANDIDATES.md | 是 | gene 工作库（起点 = v5 库 1.0，只改了一条 gene 的 audit 文字和版本） |
| data/cases/、data/splits/、data/mamo_underspecified_ids.json | 是 | 中性版，只读（chmod a-w）；题目记录和题号与 v5 逐字节相同 |
| data/README.md、data/EXCLUSIONS.md、data/smoke/ | 是 | 中性版文档；smoke 是作者自写的 3 道冒烟题 |
| data/analysis_sets/、data/splits_r1/、configs/analysis_set_defs.r1.json | 是 | 分析集合（阶段 1 的题号文件，逐字节复制）、子集锁、集合定义（E14） |
| data/labels/、data/reference_overrides/、data/exclusions_r1.json | 是 | 标注导入后才有（`data/ingest_annotations.py`） |
| data/raw/ | 否 | 原始基准文件（不入库、不发布） |
| releases/v1.0/ | 否 | v5 的 gene 库 1.0 + conditions/ + schema/，只读，回归基准 |
| PROVENANCE/ | 否 | v5 原样副本（只读）、两份清单、锚点哈希 `v5_anchor_hashes.json`、被禁用的 7 个脚本、中性化脚本与映射 |
| experiments/ | 否 | 新运行，命名沿用 `<日期>-<模型>-<数据>-{dev|test}-<配置>` |
| .venv-tools/、.cache/tiktoken/ | 否 | 分析与分词器环境（Homebrew Python 3.14.7 建的 venv）和 tiktoken 编码文件（只读）；版本和哈希登记在 `configs/venv_tools.json`、`configs/venv_tools.freeze.txt`（入库） |
| paper/evidence/ | 否 | 证据快照（`analysis/make_evidence_snapshot.sh`）；不入库，但中性写法自检照扫 |

## 3. 每次开工先做

```sh
# 在仓库根目录
PY=${ORGENE_PY:-/opt/homebrew/bin/python3}
$PY runtime/orgene_cli.py env                 # 期望 ok: true，测试 LP Optimal 1.0
$PY -m pytest -q runtime/tests tools/tests    # 期望全部通过（跳过的只有按设计需要环境变量的几个）
$PY runtime/orgene_cli.py selftest            # 期望最后一行 [selftest] PASS
$PY tools/anon_scan.py --require-terms        # 期望 hits 0（中性写法自检；身份词表在 PROVENANCE/anon_terms.txt，不入库）
$PY tools/anchor_hashes.py --check > /dev/null   # 期望 release anchors: 15/15 reproduced
$PY analysis/check_test_isolation.py          # 期望 RESULT: PASS（标注未导入时会列出待定的集合）
$PY tools/derive_splits_r1.py --check         # 期望 RESULT: PASS（子集锁与分析集合文件一致）
$PY tools/model_registry.py check             # 期望 OK（只读：Ollama 身份、服务设置、解释器、基线版本；不调用模型）
$PY tools/venv_tools_check.py                 # 期望 [venv-tools] OK（.venv-tools 的包与 freeze 文件一致、tiktoken 编码文件哈希一致、离线可加载）
```

- 要调用模型之前先看 `ollama ps` 和进程表，有别的项目在跑就等；不重启 Ollama 服务，不动其他项目。
- 在匿名的克隆里（没有 releases/v1.0/、PROVENANCE/），依赖它们的测试会跳过，其余照常通过。

## 4. 规则（摘要）

- v5 只读，任何东西都不在 v5 目录里运行（会生成 `__pycache__`，等于改了 v5）。
- 写 gene 的人在 test 运行之前不看 test 题的信息：不打开 test 题面，不在输出、日志、测试里打印 test 题面；测试夹具只用 `data/smoke` 或自造的小题，需要真实题时只用 dev 题。
- 中性写法：工作树里不写人名、机构名、主机名、用户目录路径；新代码一律用相对路径（`runtime/orgene/paths.py`）；需要在代码里匹配这类前缀时分段拼写（见 paths.py）。
- 生成程序的解释器：`$ORGENE_PY`，默认 `/opt/homebrew/bin/python3`；不往这个共用 Python 里装包。
- 中性版 cases、SPLIT_LOCK、题号文件是只读的；要改只能按 DECISIONS 记录理由后另生成，并更新 `PROVENANCE/v5_anchor_hashes.json` 的对应关系。

## 5. 留给后续各项的已知事项

- （E08 已做）`runtime/ollama_runner.py` 的 `--keep-alive` 默认改为 `0`（作者定的主实验默认；原为 `30m`）。
- （E14 已做）`data.py` 的 IndustryOR license 常量改为 CC-BY-NC-4.0（已锁定的 cases 文件不动）。
- 标注结果到位后：协调人用阶段 1 的汇总脚本生成无题面的 `type_final_labels.csv`、`ref_check.csv`，再在仓库根目录跑
  `$PY data/ingest_annotations.py --type … --ref … --sample … --strict`（先加 `--dry-run` 看计数）；然后 `check_test_isolation.py` 应不再列出待定集合。
  参考答案核对样本如按 todo 加了 6 道 IndustryOR 题，用新的样本文件即可（导入时记它的 sha256）。
- 规模特征：E09 的分词器和 E12 的求解记录到位后，跑 `analysis/r1/scale_features.py --token-counter … --solve-records …` 生成 `data/features/scale_features.json`（只含数字）。
- （E21 已做）`analysis/make_evidence_snapshot.sh` 默认只收 dev 和 smoke 运行；`--include-test` 要先过冻结闸门。输出目录 `paper/evidence/` 不入 git，但中性写法自检照扫。
- （E14 已做）`analysis/check_test_isolation.py` 扩大了扫描范围：非 test 运行目录的全部文本文件（含 units）、baselines/ 下的训练输入清单、gene 的 devCaseIds、conditions/ 和 genes/ 的文本；
  E22 的工程案例题号放进对应划分目录的 `eng_holdout_ids.json` 后自动按 held-out 处理。
- （E21 已做）中性写法自检 `tools/anon_scan.py`（每次提交都跑的测试 `runtime/tests/test_neutral_selfcheck.py`）；`.gitignore` 与自检的排除范围由同一测试保持一致。
- 工程方案第 4.2 节其余已知问题（C1 按字符配平、不记开始时间等）按 E03–E13 处理；（E05 已做）C3E 的 maxApplications 不对称已修，
  C3E 与 C3L 一样按每条 gene 的 maxApplications 记账。

## 6. 冻结（test 之前，E21）

顺序固定，每一步都在前一步完成后做：

1. `$PY tools/freeze.py make --anon-terms PROVENANCE/anon_terms.txt`：生成 `FREEZE_MANIFEST.json`（清单不完整或中性写法自检有命中时不写）；
2. 提交清单（仓库身份 orgene-r1）；
3. 把清单上传 OSF 并登记；
4. `$PY tools/freeze.py register --osf <GUID>`：把登记号写进清单的 `osf` 块（不在 `content_sha256` 内，冻结哈希不变）；
5. 再提交一次。

之后 test 的每一步（requests、模型调用、validate、score、快照）都要先过闸门：清单完整、核对通过、登记号对应当前内容，
所读的 cases、gene 库、配置注册表、激活词表和提示模板都在冻结范围内（DECISIONS R1-D17）；每次放行记在运行目录的 `freeze_gate.jsonl`。冻结目录（runtime、analysis、tools、configs、conditions、genes、schema、baselines）
在 test 期间不能有未提交或未跟踪的文件。`osf` 块不在 `content_sha256` 内，投稿前把登记号换成匿名 view-only 链接不影响冻结哈希。


## Latest update: 2026-09-30 approved gene iteration 0

The earlier working-library state is superseded for development by `configs/gene_iteration.it0.json`. Author approval is complete for all 12 proposals; do not request it again. Original dirty files were preserved and committed as `150ff7b`; integration is `af604aa`. The toolchain is restored and post-integration regression passes (1374 passed / 11 skipped).

First inspect `experiments/gene-it0-dev-qwen3-20260930/status.json` and its stage logs. The detached driver runs one-case rehearsal, then MAMO30 and IndustryOR25, four conditions each. It stops on incomplete units or failed token/provenance/reuse audits. Keep the single GPU slot free until this campaign completes. Preserve failed attempts; do not merge incompatible records. Summarize development performance only after all 220 main-dev units are verified. Formal freeze, E07/E15/E20b, E16/E22/E23 completion, annotations, and final gene release remain pending. Use LC_ALL=C LANG=C for commands.

Campaign update: the original four rehearsal units completed with full local tokens and correct shared sources. The campaign audit incorrectly counted units/setup.json as a fifth unit and stopped before dev55. Corrected the audit to validate schemas and condition pairing; five focused regression tests pass. The original failure log is preserved outside the repository; its in-repository copy only replaces the home-directory prefix. A separate v2 campaign repeats the rehearsal and then runs all dev55; no records are spliced. Active path: `experiments/gene-it0-dev-qwen3-20260930-v2/`.

## 2026-09-30: completed approved gene dev55 (qwen)

Campaign `experiments/gene-it0-dev-qwen3-20260930-v2/` is complete: MAMO 120/120 and IndustryOR 100/100 main units; rehearsal is separate. Audited all 220 locked dev units, local token completeness, exact C0 call/request/content reuse by C3L and C3E, approved gene/lexicon/predicate hashes, one unchanged code version and decoding setup, current model/condition registries. No incomplete units. Scored original dev references with the runtime primary tolerance (absolute and relative 1e-4); no answer override applied. Only dev case rows were JSON-parsed for scoring.

Correct counts (MAMO / IndustryOR / combined): C0 17/30 / 10/25 / 27/55; C3E 18/30 / 10/25 / 28/55; C3L 24/30 / 12/25 / 36/55; C3 8/30 / 11/25 / 19/55. C3L versus C3E paired table is both correct 28, C3L only 8, C3E only 0, neither 19, difference 14.5 percentage points. All primary-correct answers are solver-record consistent. C3L repairs 9 initially wrong answers; C3E repairs 1; neither introduces a correct-to-wrong transition.

Mean complete-method tokens are C3L 2736.2 and C3E 2036.3 (+34.4%); mean calls 1.564 and 1.345. Shared C0 must not be double-counted as physical execution. The campaign made 203 actual new model calls, with 598771 recorded tokens excluding duplicated C0 counts. C3 remains lower at 19/55; its first round was 15/55, and final errors are 29 objective mismatches plus 7 missing objectives. Preserve this result and diagnose dev failures without claiming a specific gene cause.

Primary evidence: campaign `dev55_results_audit.json` (no problem/spec/program/prompt text), per-stage results/metrics, and untouched unit records. This is descriptive qwen development evidence, not a formal test or a comparison against the old gene library. Original references await independent adjudication; the second model, final gene release, rehearsal, preregistration and freeze remain outstanding. No new genes or model calls were made during this audit.
