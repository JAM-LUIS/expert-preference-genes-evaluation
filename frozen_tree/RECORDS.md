v5 出处：DECISIONS.md sha256 `2435c35aa9e7e1d717e546b62437664cd49e6d02d29a12943869cc8d70d7d970`；RECORDS.md `2082c1fbd801aa4fc60f21b356f7c462de97c444102e7697a87f408c90c89b35`；HANDOFF.md `2e4e143064058441d9691873c12960043ecfe534cac05e3f039fac740411e576`（原件在 `PROVENANCE/v5_pristine/`，不入库）。

# RECORDS — ORgene R1

按时间追加，不改旧条目。只记 dev、smoke 和自造例子上的数字；test 上的任何结果在冻结和闸门放行之前都不会出现在这里。

## R1-R1 2026-09-28 建立 R1 工作区（E01）

- 复制开始时间（UTC）：`2026-09-28T22:47:53Z`（`PROVENANCE/copy_started_utc.txt`）。复制前查看过 Ollama（没有加载任何模型）和进程表（没有其他运行在跑）。
- v5 源树哈希：`732887baac96c28f9af84d76032b22ac5a28ab90b95ec916eb3bbd0a75499bf3`
  = sha256(`PROVENANCE/v5_source.SHA256SUMS`)，127 个文件；范围是 allowlist（runtime、analysis、conditions、genes、schema、data、DECISIONS.md、RECORDS.md、HANDOFF.md），
  去掉 `__pycache__/`、`data/raw/Mamo/.git/`、`.DS_Store`。
- 原样副本 `PROVENANCE/v5_pristine/` 的清单 `r1_pristine.SHA256SUMS` 与 `v5_source.SHA256SUMS` 逐行相同（diff 为空）；副本已设为只读。
- 复制结束后在 v5 端重算清单 `v5_source.after.SHA256SUMS`，与复制前逐行相同；v5 整个目录（含 allowlist 之外）比复制开始时间新的文件数为 0。
  v5 目录里没有执行任何程序。
- **9 月 7 日在 test 上跑完的 C0–C2 运行已被取代，未打开**：v5 的 experiments/ 不在 allowlist 里，没有复制、没有列目录、没有读取；这些运行不复用。
- 写死 v5 路径的 7 个脚本（run_c3l.sh、run_c3e.sh、run_test_batch1.sh、run_dev_c2.sh、run_dev_np6000.sh、chain_dev_c2.sh、chain_dev_c3.sh）已移到
  `PROVENANCE/v5_runtime_scripts_disabled/`，去掉写和执行权限。
- `releases/v1.0/`：v5 的 genes.v3.jsonl、conditions/、schema/，只读。

## R1-R2 2026-09-28 R1 回归（代码改动之前，工作副本与 v5 相同）

- 解释器 `/opt/homebrew/bin/python3`（3.14.7，PuLP 3.3.2，pytest 9.1.1）。
- `python -m pytest -q runtime/tests`：**55 passed**。
- `runtime/orgene_cli.py selftest`：**PASS**。
- 锚点哈希（`tools/anchor_hashes.py --check`，R1 代码跑在 `releases/v1.0/` 上）15/15 复现：

| 对象 | 值 |
|---|---|
| gene 库 1.0 文件 | `dffff83adde65a8b250b74698c99c4a72a77184c7d0de87edce7db1559319d66` |
| C3 合同（17 条编译，5306 字符） | `055f9ab4a7afd87efee79959688c9568899704acab9f1a8787587e2142607102` |
| 激活集 digest C3 | `8b58e7ceeeb86ef53b69b5a8da6af4f5ad466e4f2183bfecb7e0282db637c340` |
| 激活集 digest C3L（13 条） | `81f05b7b158fb026bf81bd04ca33e4437cc8e3b7c44e2b5c871851a1d405e222` |
| 激活集 digest C3E（5 条） | `806fdb5cc214b4d5683f3d64b3638c2a267ee45fc5fdc296167418f61e21a27f` |
| 系统提示 C0（= C3L = C3E） | `dbae2eec5bb774667286d4b18261ad5ee4221fef5916d711e50709415b53a450` |
| 系统提示 C1 | `94c42eedc7d68ca374c204e82310dbbb728131cc7dfb0506024022cd1c853f69` |
| 系统提示 C2 | `d59532d6bbebfc8e082cfb261236621db7fff224e801cd77ccdb054003ec6a50` |
| 系统提示 C3 | `c432a57891f572800d3557271f2e8de37a321d690d8dccc71acfa95bc4cd47ef` |

  v5 的记录里激活集和系统提示只有 16 位前缀，这里补上了完整值；C1/C3 字符比 1.0101（与 v5 相同）。
- 数据锚点（工作副本中性化之前）全部与 v5 记录一致：cases mamo_complex_lp `10b91fd3…3aa83484`、industryor `7817c234…241538dd`；
  划分 mamo dev `3e179dd6…3969fb`、test `b4f0f6c2…bdca7`，industryor dev `f45a5a02…22868`、test `e2233fd4…2ce88`（dev 60/151、25/75）；
  原始文件 MAMO `07eb3db3…bbfc3`、IndustryOR `5b889e49…f95f36`；欠定粗筛 `3589315e…e721a`。
- 模型：qwen3:8b manifest `500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41`，权重 blob `a3de86cd…8e686f`，模板 blob `ae370d88…dfc4`；
  长上下文别名 qwen3-8b-ctx32k:latest manifest `c009fe1f…58ce2`，权重、模板 blob 与 qwen3:8b 相同，params blob `97c97f89…`。只读了 manifest，没有调用模型。
- 全部 27 项锚点及出处写在 `PROVENANCE/v5_anchor_hashes.json`（`all_anchors_match = true`）。LLM4OR 清洗版 MAMO（只用题号）的哈希 `28e10dff…7a0d` 取自数据任务的下载清单，文件不在 R1 里，没有重算。

## R1-R3 2026-09-28 中性化（E02 / E14 的 neutralize 步骤）

| 文件 | v5 sha256 | R1 sha256 | 改了什么 |
|---|---|---|---|
| data/cases/mamo_complex_lp.jsonl | `10b91fd3…` | `743b6c1ed2179a77b5943b57ce24956831d6edf3a6aa206cbbf045e4497b009a` | 第 1 行 raw_path → `data/raw/Mamo/data/optimization/Complex_LP/mamo_complex_lp.jsonl` |
| data/cases/industryor.jsonl | `7817c234…` | `13ae3ea9a4c13482904b2cc1ca3e80440ece10140dfa27af3b72a72d11adcec6` | 第 1 行 raw_path → `data/raw/industryor/IndustryOR.json` |
| data/cases/smoke.jsonl | `38e0e343…` | `ed8b41af93b25e239428194ad983ce8891b141e76db60eb2e34dda6c99661a7c` | 第 1 行 raw_path → `data/smoke/smoke_raw.jsonl`（与现行代码重新生成的文件逐字节相同） |
| data/splits/mamo_complex_lp/SPLIT_LOCK.json | `c461bdd6…` | `15db1d2069f4f56760d440bd953b57234c2ee5381cc2fd695eeb4d97ad4216cf` | cases_path 相对、cases_sha256 = 中性版 |
| data/splits/industryor/SPLIT_LOCK.json | `f14d3134…` | `eb297b16ffe41e8c3f7f20686bbc81af578191ed07cf39b8918fab47d8990a13` | 同上 |
| data/mamo_underspecified_ids.json | `3589315e…` | `5f39b57ed126851fffbf1b3443a39f83aae34ec98522ac7a92e639af2ab6f3d9` | `_note` 里的人名 |
| genes/genes.r1.jsonl（v5 genes.v3.jsonl） | `dffff83a…` | `6803c3f5e3a039717b64a998c03303e20b6827ba06dc84f2d27e094866cc948d` | 第 16 行 audit 人名；该 gene 版本 1.0.0 → 1.0.1 |

- 三个 cases 文件第 2 行起逐字节不变（第 2 行起的 sha256：mamo `27aa57f6…2d4b`、industryor `ce261349…97a9`、smoke `8e31a21e…e4b7`，v5 与 R1 相同）。
  dev/test 题号文件与 v5 逐字节相同，`dev_sha256`、`test_sha256` 不变。中性版 cases、SPLIT_LOCK、题号文件和欠定粗筛文件已设为只读。
- `genes/CANDIDATES.md`、`data/EXCLUSIONS.md`、`data/README.md` 写了中性版（见 DECISIONS R1-D2；逐题引用 test 的段落不收录）。
- gene 工作库的哈希：激活集 digest C3 `eb419c483724d52c7ecebccd6478a80519fe5cd2761c85a1b8e33ae8e6795c2b`、C3L `baa415853e815d63b5bb08fc9dcd6efb7c53e306fd15f1d2cd6fa5d5c45daee5`、
  C3E `806fdb5c…`（与 1.0 相同）；C3 合同和六个系统提示的哈希与 1.0 相同。

## R1-R4 2026-09-28 E02 改动后的回归

- 改动：`runtime/orgene/paths.py`、`env.py`（新）；cli、split、data、conditions、execute、ollama_runner、api_runner 写进产物的路径改为相对路径、命令行改为 `$R1`；
  生成程序的解释器改为 `$ORGENE_PY`（默认 `/opt/homebrew/bin/python3`），`run_condition.sh`、`derive_repair_ladder.sh`、`make_evidence_snapshot.sh` 不再调用 PATH 里的 python3；
  `check_test_isolation.py` 按仓库根目录解析 SPLIT_LOCK 里的相对路径；默认 gene 库改为 `genes/genes.r1.jsonl`。
- `python -m pytest -q runtime/tests`：**84 passed**（原 55 个 + 新增 29 个：test_paths 10、test_neutral_data 14、test_v1_regression 5）。
- `selftest`：**PASS**；`orgene_cli.py env`：Python 3.14.7 / PuLP 3.3.2 / CBC 2.10.13（arm64），测试 LP `Optimal 1.0`。
- `tools/anchor_hashes.py --check`：v1.0 锚点 15/15 仍然复现。
- `analysis/check_test_isolation.py`：**PASS**（两个 SPLIT_LOCK 的 cases/dev/test 哈希一致，dev/test 不相交；R1 还没有 experiments/，扫描 0 个请求文件）。
- 中性写法检查：第一个提交的全部文件（含 DECISIONS、RECORDS、HANDOFF）里，检索人名、机构名、主机名、用户目录前缀均为 0 处（cases 文件只看命中行号，也是 0）。
- 匿名仓库模拟：只取将要提交的文件放进临时目录（没有 PROVENANCE/、releases/v1.0/、data/raw/）：pytest **74 passed、10 skipped**（跳过的 10 个依赖出处副本或 releases/v1.0/，按设计跳过），selftest PASS，隔离检查 PASS。

## R1-R5 2026-09-28 分析集合、子集锁和隔离检查（E14）

- 阶段 1 的分析集合文件（v2，含 `_excl0905` 集合）复制为 `data/analysis_sets/analysis_sets.v2.json`，逐字节相同，sha256 `6baf6b7f8678e78f12884f5775ebbfda8d4b396e9b793abee6133f1462a5205d`；
  集合定义 `configs/analysis_set_defs.r1.json` sha256 `d6a233f692a49dfde8e5fea661d6f932f5a39d831853e4d34a08bdcebbc6ed98`。
- `tools/derive_splits_r1.py` 生成 6 个子集锁；每个集合的题数和 dev/test 题号哈希都与集合文件所记一致，没有题换边（`--check` 重新派生后逐字节相同）：

| 集合 | dev | test | 删掉的 dev / test | test 题号哈希 | SPLIT_LOCK sha256 |
|---|---|---|---|---|---|
| mamo_main_clean111 | 30 | 81 | 30 / 70 | `c877ee5d…` | `1569bb7199285fab…` |
| mamo_sensitivity_full211 | 60 | 151 | 0 / 0 | `b4f0f6c2…` | `e60642d1f8a67ab4…` |
| industryor_main_rev2026_100 | 25 | 75 | 0 / 0 | `e2233fd4…` | `22be0fa75704d5a9…` |
| mamo_main_clean111_excl0905 | 30 | 80 | 30 / 71 | `6aaa1d3b…` | `2e5aa81f063052d5…` |
| industryor_main_rev2026_100_excl0905 | 25 | 71 | 0 / 4 | `c38c425d…` | `fa65315153d4954b…` |
| mamo_sensitivity_full211_excl0905 | 60 | 146 | 0 / 5 | `5990623f…` | `acd6bce6e6f7eda3…` |

- 9 月 5 日看过题面的 9 道 test 题：MAMO 清洗子集 1 道、MAMO 全集 5 道、IndustryOR 4 道；三个 `_excl0905` 集合都不含它们。
- 集合定义的当前解析：dev_signal55 = 55（MAMO 30 + IndustryOR 25），dev_all85 = 85，dev_error_type_only30 = 30；
  main 等 7 个 test 集合等题型标注和参考答案核对导入（导入前 main 是 MAMO 80 + IndustryOR 71，这是去掉 NL_NOT_LINEARIZABLE 和 Q3 移出题之前的上限）。
- `analysis/check_test_isolation.py`：PASS（两个冻结划分和 6 个子集锁一致；31 处 devCaseIds 都是 dev 题；conditions/、genes/ 的文本里没有 test 题号；R1 还没有运行目录和基线目录）。
- pytest：E14 新增 47 个测试（test_subset_split 9、test_analysis_sets 10、test_annotations 10、test_isolation_check 15、test_scale_features 3）。
  在带 PROVENANCE/、releases/v1.0/ 的树上 130 passed、1 skipped（E02 后的 84 个 + E14 新增 47 个；跳过的 1 个是需要 E13 `refs.py` 的覆盖文件往返测试）；
  没有这两个目录的树上 120 passed、11 skipped（另 10 个依赖出处副本或 releases/v1.0/）。与 r1/e13 试合并后这个往返测试也通过。

## R1-R6 2026-09-29 第一批分支合并（wave1）

- 按顺序把 10 个通过核验的分支用 `git merge --no-ff` 合进 main，每合并一个就跑一次全部测试（`$PY -m pytest -q runtime/tests`，E21 合并后加 `tools/tests`）和 selftest。
  全部提交（含合并提交）的作者和提交者都是仓库身份 orgene-r1。合并前 main 为 `684ed49`（84 passed）。

| 分支 | 分支 HEAD | 合并提交 | 冲突 | 合并后 pytest |
|---|---|---|---|---|
| r1/e03 | `b30cc38` | `9ecdfea` | 无 | 160 passed |
| r1/e04 | `bacd3e5` | `ddb7502` | 无 | 325 passed |
| r1/e05 | `d2a947f` | `66f2116` | conditions.py | 392 passed, 1 skipped |
| r1/e08 | `d306c80` | `4f83864` | 无 | 450 passed, 1 skipped |
| r1/e09 | `7d91f4d` | `5abc370` | ollama_runner.py、conditions.py、run_condition.sh | 530 passed, 2 skipped |
| r1/e12 | `4eaa913` | `aed4234` | 无文本冲突；与 E05 测试有语义冲突 | 625 passed, 3 skipped |
| r1/e13 | `17b25a4` | `8adf1e6` | pipeline.py | 686 passed, 3 skipped |
| r1/e14 | `0ecc227` | `5364b35` | 无 | 733 passed, 3 skipped |
| r1/e19 | `0897aad` | `c046448` | 无文本冲突；一个测试随 E09 默认值调整 | 807 passed, 4 skipped |
| r1/e21 | `64464b1` | `cab8b2c` | 无 | runtime 810 + tools 104 = 914 passed, 4 skipped |

- 冲突和语义冲突的处理（详细理由写在各合并提交的说明里）：
  - E05 × E03，`runtime/orgene/conditions.py`：取 E03 一侧。注册表已登记 C2E（prompt C2、reuse C2、gene_scope C3E、generic、spec_and_program、max_rounds 2），请求改由注册表构建，
    E05 对旧条件元组和旧构建器的改动都被取代；E05 对 C3E、C2E、两轮上限、阶梯截取、删除 C3P 的说明并进模块文档串。v1 构建器保持 v5 原样（回归基准）。
    E03 的 `validate` 在 `validate_round` 接受 gene_scope/repair/closing 时按注册表传值，C2E 走批处理路径；"REPAIR_PROFILES 与注册表一致"的测试在合并后实际运行并通过。
  - E09 × E08，`runtime/ollama_runner.py`：保留 E08 的薄包装，把 E09 的改动移进来并保留 E09 的四项保证：`--local-tokens on|off` 默认 on；
    服务器报的 digest 必须等于本地 manifest（没报 digest 也拒绝）；第一次调用前用本地模板移植渲染全部请求；计数器 identity 记为 `local_tokenizer` 并参与续跑比对。
    `--token-counter module:function` 替换内置计数器，与 `--local-tokens off` 同时给出时拒绝；单次调用计数失败沿用 E08 的做法，记进 `local_tokens_error`，回答保留；
    用到内置计数器时 `tokcount.py` 进 code_sha256。`runner.run_batch` 的续跑拒绝信息改为列出全部不同的键（原来只报第一个）。
  - E09 × E03，`conditions.py`：`build_system_prompts_v1` 接收 E09 的 `token_counter` 参数（函数体已自动合并）。E09 的测试改调 `build_system_prompts_v1`。
  - E09 × E05，`runtime/run_condition.sh`：保留 E05 的循环结构，修复预算检查那一行加 E09 的 `--model "$MODEL"`。
  - E12 × E05（语义）：`run_program` 返回的 `exec.solve_records` 带墙钟字段 `t`，E05 的阶梯截取和重验证测试比较两次执行时要去掉墙钟字段，`test_repair_e05.norm` 的字段表加上 `t`。
  - E13 × E12，`runtime/orgene/pipeline.py`：两边都保留，先 E13 的 reference_summary，后 E12 的 misreport 汇总。
  - E19 × E09（语义）：E19 有一个测试让 ollama_runner 对着报真实 qwen3:8b digest 的假服务器跑；E09 合并后默认开启本地计数，
    这个测试在模型主机上会读本机 Ollama 模型库和 llama-tokenize（在别的机器上会失败）。它测的是登记表，改为传 `--local-tokens off`。
    `test_backends.py` 里对假服务器的运行同样默认加 `--local-tokens off`；另加两个测试：默认会建内置计数器（假服务器没有本地模型库时在任何调用前退出），`--token-counter` 与 `--local-tokens off` 同时给出时拒绝。
- 全部合并后（main `cab8b2c`，工作树干净）：
  - pytest：runtime/tests **810 passed, 4 skipped**，tools/tests **104 passed**。4 个跳过都是按设计的：在线登记表检查（`ORGENE_LIVE_REGISTRY=1`）、
    要调用模型的 Ollama 集成测试（`ORGENE_OLLAMA_TESTS=1`，彩排时跑）、需要基线环境 Pyomo 的可选测试、已被注册表取代的旧提示表测试。
  - 匿名仓库模拟（`git archive HEAD` 解到临时目录，没有 PROVENANCE/、releases/v1.0/、data/raw/、.git）：**898 passed, 20 skipped**，多出的 16 个跳过都依赖出处副本、releases/v1.0 或 git 检出。临时目录已删除。
  - selftest PASS；`tools/anchor_hashes.py --check` 15/15；`analysis/check_test_isolation.py` PASS（7 个 test 集合待标注）；`tools/derive_splits_r1.py --check` PASS；
    `tools/model_registry.py validate` OK（4 个条目）；`tools/check_gene_versions.py` 退出码 0。
  - `tools/anon_scan.py`：149 个文件、51 个提交、词表 10 条、本机名 2 个，命中 0；工作树检索用户目录前缀、姓名、机构名、其他项目名 0 处；PROVENANCE/、releases/v1.0/、data/raw/ 没有被 git 跟踪。
    身份词表 `PROVENANCE/anon_terms.txt` 从 E21 的 worktree 复制到主检出（不入库，只读）。
  - 冻结演练（清单写到仓库外的临时目录，用完已删）：130 个文件、complete=false、缺 23 项（各模块的 pending 条目，以及还没有的 baselines/），gene_anchors 正常，verify PASS；没有清单时 test 闸门拒绝。
- 10 个 worktree 已用 `git worktree remove` 清理（删除前核对过：都是干净的；E03、E04 里的 releases/ 副本与主检出逐文件相同；E21 里只有上面复制过的词表）。r1/e* 分支保留，都已并入 main。
- 合并过程没有调用模型（开始和结束时 `ollama ps` 都为空），没有打开 v5，没有读取或输出任何 test 题面，也没有任何 test 结果。

## R1-R7 2026-09-29 wave1 合并核验

- 对象：main `7908fb8`（标签 `wave1`）。核验修正提交 `f9a0194`，本条记录另成一个提交；标签 `wave1` 不动，仍指向合并记录提交。
- 被合并分支的改动是否都在 main：对 10 个分支逐个取"合并基点 → 分支 HEAD"的新增行和删除行，与 main 逐文件比对。
  main 里找不到的新增行都能对上 R1-R6 记下的冲突处理：E03/E05 的旧条件元组被注册表取代（E05 的说明在模块文档串里）；E08/E09 的 runner 逻辑移进薄包装（E09 的四项保证逐项在）；
  `build_system_prompts` 改名为 `build_system_prompts_v1`；续跑拒绝信息改为列出全部键；E19 测试加 `--local-tokens off`。被分支删掉又在 main 里出现的行只有通用的 `try:` 之类。
  E05 删掉 `analysis/derive_repair_ladder.sh`、改用 `.py`，是分支本身的改动。
- **发现并修正一处语义冲突（E05 × E08）**：`analysis/reuse_c0_as_c3l.py` 按 v5 runner 的 config.json 读 `options`，而 E08 之后的 runner 写的是 `opts`，
  于是经 `run_condition.sh` 跑 C3L、C3E、C2E 时，复用第 0 轮这一步一律被拒（num_ctx、num_predict、temperature 读成 None）。检查是"失败即拒绝"，不会产生错误结果，但修复配置跑不起来；
  E05 的测试用手写的 v5 格式 config，所以没有测出来。修正：先读 `opts`，没有时读 `options`（v5 的运行）。E05 的测试改为默认写 E08 格式、两种格式都接受；
  `test_backends.py` 新增一个测试，用真实的 ollama_runner 对假服务器生成第 0 轮，再对它的 config.json 做复用检查（设置一致时通过，num_ctx 不同时拒绝）。两个测试在修正前都失败。
  另在仓库外临时目录里用假服务器端到端跑了 `run_condition.sh`：C0 → C3L、C2 → C2E 复用都通过（5 项设置核对），validate、score 正常；临时目录已删。
- 修正后：pytest runtime/tests + tools/tests **915 passed, 4 skipped**（新增 1 个测试；4 个跳过同 R1-R6）；`git archive HEAD` 匿名仓库模拟 **899 passed, 20 skipped**；selftest PASS。
- v1.0 回归锚点：`tools/anchor_hashes.py --check` 15/15；另用 `build_system_prompts_v1` 在 releases/v1.0 上独立重算，gene 库文件 sha、合同 sha（5306 字符）、C3/C3L/C3E 激活 digest、
  C0–C3 系统提示 sha 都与工程方案 2.5 节一致，C3L、C3E 的系统提示与 C0 相同。
- 其他：check_test_isolation PASS（7 个集合待标注）；derive_splits_r1 --check PASS；model_registry validate OK；check_gene_versions 退出码 0；
  anon_scan（--require-terms）命中 0；工作树与 git 元数据检索身份痕迹 0 处；冻结演练 complete=false、缺 23 项、verify PASS；没有清单时 test 闸门拒绝（退出码 1）。
- v5 未被改动：allowlist 按 `PROVENANCE/v5_source.SHA256SUMS` 重算 127 行逐行相同；v5 在 test 目录以外的文件与目录、以及 test 目录项本身，最新修改时间都早于复制开始时间（test 目录没有进入）。
- 核验没有调用模型（`ollama ps` 为空），没有在 v5 里运行任何东西，没有读取或输出 test 题面，也没有任何 test 结果。

## R1-R8 2026-09-29 wave1 合并核验（第二遍：分支之间的接缝）

- 对象：main `817b680`（R1-R7 之后）。修正提交 `52452d3`，本条记录另成一个提交；标签 `wave1` 不动。
- 重跑：pytest runtime/tests + tools/tests 915 passed, 4 skipped；selftest PASS；锚点 15/15。
- 分支改动是否都在 main：逐个分支取"合并基点 `684ed49` → 分支 HEAD"的补丁，按文件做反向应用检查（`git apply --check -R`），并逐行比对新增、删除行。
  反向应用不通过的文件只有 R1-R6 记下的冲突文件和 R1-R7 修过的文件；这些文件里 main 缺的新增行逐条都能对上已记录的处理（E03 取代 E05 的旧元组、E09 逻辑移进 E08 的包装、
  `build_system_prompts_v1` 改名、续跑信息列全部键、`opts` 读法、E19 测试加 `--local-tokens off`）。E09 的四项保证、E08 的续跑键（含 `local_tokenizer`）、E12 × E13 的打分顺序都在。
- **发现并修正两处接缝问题**（都是一个分支的改动没有传到另一个分支写的代码里，测试没有覆盖）：
  1. `tools/tokcount_crosscheck.py`（E09）仍调用 E03 改名前的 `conditions.build_system_prompts`，合并时只改了 E09 测试里的调用，这个工具一运行就报 AttributeError。改为 `build_system_prompts_v1`（仍是每个范围全部 gene 激活的提示表），conditions 的文档串写明这一用途。
  2. `runtime/run_condition.sh`（E05）的 num_predict 默认仍是 4000，而配置注册表（E03，所有配置）和模型登记表 `qwen3-8b.main`（E19）都是 6000，脚本又不传 `--registry`，按默认值跑会和登记的设置不一致。默认改为 6000。
- 新增 `runtime/tests/test_wave1_seams.py`（5 个测试）：runtime、analysis、tools、data 代码里引用的 orgene 名字都存在（静态检查）；run_condition.sh 的默认值等于两份登记表；
  E03 的注册表构建器配真实的 E04 按题激活、词表和特征（逐题合同、激活轨迹、features_sha256 与 E04 的算法一致、C3L-ALL/C3E/C2E 不受规则影响、带规则的库不给特征时拒绝、批量 validate 的拦截认得 E04 的规则格式；E03 自己的测试是用替身代替 E04 的）；
  E21 的闸门把冻结清单交给 E13 的参考答案覆盖检查（显式给的 `--freeze-manifest` 保持不变）。前两个测试在修正前的提交上失败，修正后通过。
- 修正后：pytest runtime/tests + tools/tests **920 passed, 4 skipped**；`git archive HEAD` 匿名仓库模拟 **904 passed, 20 skipped**；selftest PASS；`tools/anchor_hashes.py --check` 15/15。
- v1.0 回归锚点另行独立重算：把 `PROVENANCE/v5_pristine` 里 v5 原版的 `orgene` 包拷到仓库外临时目录，用 v5 原版构建器和 main 的 `build_system_prompts_v1` 分别在 releases/v1.0 上构建，
  gene 库文件 sha、合同 sha（5306 字符、17 条）、C3/C3L/C3E 激活 digest、C0–C3 与 C3L/C3E 系统提示 sha 两边逐项相同，也都与工程方案 2.5 节一致。
- 其他：check_test_isolation PASS（7 个集合待标注）；derive_splits_r1 --check PASS；model_registry validate OK；check_gene_versions 退出码 0；anon_scan（--require-terms）命中 0；
  工作树检索用户目录前缀、姓名、机构名、其他项目名 0 处，git 作者、提交者、标签者都是仓库身份；冻结演练（仓库外）131 个文件、complete=false、缺 23 项、verify PASS；没有清单时 test 闸门拒绝。
- v5 未被改动：allowlist 127 个文件与 `PROVENANCE/v5_source.SHA256SUMS` 逐行相同；复制开始之后 v5 里没有任何文件或目录被改动（test 目录只看目录项本身，不进入）。
- 核验没有调用模型（`ollama ps` 为空），没有在 v5 里运行任何东西，没有读取或输出 test 题面，也没有任何 test 结果。

## R1-R9 2026-09-29 第一批各模块的实施与核验结果（各自分支上，合并前）

各模块分支从 main `684ed49` 建，核验后合并（R1-R6）。下面是各分支在核验后的读数；测试数是分支自己的（worktree 里没有 PROVENANCE/、releases/v1.0/ 时相关测试跳过）。
E14 的记录见 R1-R5。决定见 DECISIONS R1-D7 至 R1-D15。

- E03 配置注册表（核验后 HEAD `b30cc38`）：`configs/r1_configs.json` sha256 `85c5a300…d361`；注册表构建器在 v1.0 输入上复现 C0–C3 系统提示和 C3 合同的哈希。
  worktree 155 passed / 5 skipped，匿名克隆 149 / 11；selftest PASS；锚点 15/15。
- E04 按题激活（`bacd3e5`）：词表种子版 `genes/activation_lexicon.v1.json` sha256 `fb98272e…bbfd`；工作库 17 条 gene 都没有激活规则，dev 激活率全为 1.0；
  v1.0 库在 all 和 per_problem 两种模式下三个激活集 digest 都等于锚点。pytest 244 passed / 5 skipped。
- E05 修复阶梯（`d2a947f`）：通用修复模板 sha256 `ddb95169…1dcb`；没有 gene 用完次数时 C3E 的修复消息与 v5 在 8 种失败组合上逐字节相同；
  假 runner 下从 2 轮运行截出的 0、1 轮结果与直接跑的结果完全相同；9 种变异都被测试查出。worktree 141 passed / 11 skipped；链入 releases/v1.0 时 selftest PASS，锚点 15/15。
- E08 runner（`d306c80`）：逐调用记录字段、续跑拒绝、登记表拒绝、身份漂移都有测试；非有限的选项值在发送前拒绝。链入出处目录后 142 passed / 0 skipped。
- E09 本地计数（`7d91f4d`）：llama-tokenize 0.3.0（build 10621，commit c1d0e7a00）。与 GGUF 词表建的独立 BPE 分词器逐个比对 token id：合成边界串 14/14、
  C0–C3 系统提示 4/4、smoke 题及其渲染提示 3/3 和 3/3、85 道 dev 题的 user 消息 85/85（32,089 token）、[C0 系统提示, user] 的渲染提示 85/85（48,749 token），全部一致；
  脚本只输出计数。qwen3:8b manifest `500a1f06…`、权重 `a3de86cd…`、模板 `ae370d88…`。链入出处目录后 163 passed / 1 skipped。
- E12 求解记录器（`4eaa913`）：v5 两个 dev C0 目录的 85 个第 0 轮程序，有无记录器时返回码、stdout、stderr（遮掉临时名后）、解析出的状态和目标值 85/85 相同，
  没有超时；同一批程序（dev，只作管道检查）的目标值虚报标记：MAMO 60 题中 1 个（`mamo_complex_lp-0182`，取整打印，`objective_rounding_only` 为真），IndustryOR 25 题中 0 个。
  链入出处目录后 179 passed / 1 skipped；可选的真 Pyomo 测试 1 passed，baselines 环境没有文件被改动。
- E13 容差与覆盖（`17b25a4`）：规则摘要 `3bb2fccc…d03c`，覆盖文件格式见 `data/reference_overrides/README.md`，等标注结果由 E14 生成；
  v5 dev 结果 1020 行按新代码重算，主口径与 v5 的 `correct` 完全一致。链入出处目录后 145 passed。
- E19 登记表（`0897aad`）：模型环境快照 `configs/snapshots/model_env.20260929T001230Z.json`（sha256 `47334729…4b7d`，含全部权重 blob 重算）：
  Ollama 0.33.0；qwen3:8b digest `500a1f06…`、权重 `a3de86cd…`、模板 `ae370d88…`、Q4_K_M；别名 `qwen3-8b-ctx32k` 的 manifest `c009fe1f…`，权重同 qwen3:8b；
  flash attention 开、KV 缓存 q8_0、并行槽 1，三处来源一致，服务 2026-08-27T21:19:55Z 起未重启；服务日志里 qwen3:8b 权重 337 次加载、ORLM 6 次、LLMOPT 8 次，全部 flash attention 开、K/V q8_0；
  Python 3.14.7、PuLP 3.3.2、CBC 2.10.13；基线环境 coptpy 8.0.7、Pyomo 6.10.1、glpk 5.0、llama.cpp b10621，没有 COPT 许可文件。
  四个条目的 sha256（`tools/model_registry.py hash <id>`）：main `7aa977b3…8d26`、var07 `5c672a26…bcdf`、r0-v5 `1e0f1d7a…c935`、r0-ctx16k `c70f49b6…8d7d`。worktree 146 passed / 13 skipped。
- E21 冻结与自检（`64464b1`）：worktree 181 passed / 10 skipped；anon_scan 0 命中；冻结演练 verify PASS，改动任一冻结文件后 verify 失败，没有清单时 test 闸门拒绝。

## R1-R10 2026-09-29 分析与分词器环境 `.venv-tools`（R1-D5 默认做法第 14 条）

- `/opt/homebrew/bin/python3 -m venv .venv-tools`（Python 3.14.7，arm64，pip 26.2.1），2026-09-29T03:14:40Z；从 PyPI 只装二进制 wheel、不用下载缓存：
  numpy、scipy、statsmodels、pandas、matplotlib、tiktoken、pytest，连同依赖共 31 个包，版本以安装时解析为准，全部钉在 `configs/venv_tools.freeze.txt`
  （pip freeze，sha256 `9f0d7c14a0cba35edb3929a51b1132bcdffa3d9cb85a7050e695bb53f56f1fcc`，没有绝对路径）。主要版本：numpy 2.5.3、scipy 1.18.1、statsmodels 0.15.0、
  pandas 3.0.6、matplotlib 3.11.2、tiktoken 0.14.0、pytest 9.1.1。共用的 Homebrew Python 没有装任何包。
- tiktoken 编码文件从 tiktoken 默认的官方地址下载到 `.cache/tiktoken/`（`TIKTOKEN_CACHE_DIR` 指向它；git 忽略、自检不扫；文件只读），2026-09-29T03:52:49Z：

| 编码 | 字节 | sha256 | n_vocab |
|---|---|---|---|
| cl100k_base | 1681126 | `223921b76ee99bde995b7ff738513eef100fb51d18c93597a113bcffe865b2a7` | 100277 |
| o200k_base | 3613922 | `446a9538cb6c348e3516120d7c08b09f57c36495e2acfffe59a5bf8b0cfb1a2d` | 200019 |

  两个哈希都等于 tiktoken 0.14.0 自带的期望值。登记在 `configs/venv_tools.json`；冻结清单的 `tools_venv_pip_freeze`、`tokenizer_files` 两项改指这两个文件。
- `tools/venv_tools_check.py`：核对 freeze 文件哈希与钉版本、环境里的 Python 版本和已装包（不多不少）、编码文件的大小和哈希，
  并经 `tokcount.TiktokenCounter`（阻止任何下载）离线加载两个编码、核对 tiktoken 版本和 n_vocab。当前结果 OK。
- 这一步没有调用模型；下载只有 PyPI 的包和上面两个编码文件。

## R1-R11 2026-09-29 诚信核查：E01 读到的那道 test 题

- 起因：E01 的执行 agent 通读 v5 的 `genes/CANDIDATES.md` 时读到其中一例引用的一道 MAMO test 题的参考值，以及这道题要取整才对得上（没有看到题面，记录里没写题号；
  R1 的中性版已删去这一例，见 R1-D2）。
- 核查（由不写 gene 的 agent 做，全程只输出题号和计数，没有打印参考值、题面或那一段文字）：在 `PROVENANCE/v5_pristine/genes/CANDIDATES.md` 里，
  R1 中性版删改的 7 行中只有 1 行同时带取整说法和数值；把它的数值与全部 cases 的参考值逐一比对，只与 `mamo_complex_lp-0022`（test）的参考值相同。
  **已核对，属于已剔除的题**：它是 9 月 5 日看过题面、已从主分析剔除的 9 道 test 题之一（`seen_20260905_test`），三个 `_excl0905` 集合都不含它，主分析题数不变。
- 顺带核对 v5 的 `genes/` 下全部文件（两个）是否还引用 test 题号或 test 参考值（只数次数）：
  - `CANDIDATES.md`：test 题号 0 处（完整题号形式只有 1 处，是 dev 题）；引用 test 参考值 1 处，就是上面这一例。另有十来个小数字（小于 100 的计数、编号等）恰好等于某些 test 题的参考值，
    所在行都不谈参考值或目标值，按数值无法也不必归属，不算引用。
  - `genes.v3.jsonl`（即 release 1.0 的种子 gene 库，与 `releases/v1.0/genes.v3.jsonl` 相同）：test 题号 0 处（32 处都是 devCaseIds 里的 dev 题号）；引用 test 参考值 0 处。
    与某个 test 参考值数值相同的只出现在日期、版本号、maxApplications、priority、dev 题号的数字部分和 audit 说明里的小数字，这些字段都不谈参考值或目标值。
  - R1 的 `genes/`（工作库、中性版 CANDIDATES、激活词表和示例）同样没有 test 题号。
  所以 release 1.0 沿用 v5 的种子 gene 不受影响；v5 的 CANDIDATES.md 是说明文档，不进 R1 工作树（R1-D2）。

## R1-R12 2026-09-29 wave1 合并后的后续改动（标签 `wave1-followups`）

- 在 main 上从 `1c12790` 起逐项追加提交，每项一个提交、每项做完都跑全部测试（`$PY -m pytest -q runtime/tests tools/tests`）、selftest、anon_scan 和锚点：

| 项 | 提交 | 内容 | pytest |
|---|---|---|---|
| A1 | `5bbf1c4` | `paper/evidence/` 进 .gitignore，自检仍按产物目录扫描；.gitignore 与自检范围一致的检查 | 923 passed, 4 skipped |
| A2 | `151acf1` | 模型调用过 test 闸门（stage generate），config.json 记 `freeze_gate` | 927 / 4 |
| A3 | `ee97785` | validate 对所有 gene 校验的配置都按注册表传 gene_scope、repair、closing（C2E、C3L-ALL 不再被拒） | 928 / 4 |
| A4 | `80a7a13` | run_condition.sh 传 `--registry/--registry-entry`（默认 qwen3-8b.main，可由第 8 个参数或 REGISTRY_ENTRY 覆盖）和 `--keep-alive`；修复预算超出时停止，think 设置传给预算检查；复用第 0 轮时核对登记表条目 | 938 / 4 |
| A5 | `6c1b483` | runner 的 metrics.json 记缺本地计数的调用数，`runner.local_token_gaps` 供彩排第 5 项读取 | 940 / 4 |
| A6 | `2ea8736` | HANDOFF：第 3 节开工检查、第 5 节已完成项、第 6 节冻结顺序 | 940 / 4 |
| A7 | `c661c83` | 冻结清单的 gene_anchors 按注册表逐配置计算（`tools/anchor_hashes.py:config_anchors`） | 942 / 4 |
| A8 | `fb0bcbb` | DECISIONS R1-D7 至 R1-D15、RECORDS R1-R9（第一批各模块建议的条目） | 942 / 4 |
| B | `5d799f9` | DECISIONS R1-D16（2026-09-28 main session 的 8 条技术决定） | 942 / 4 |
| C | `7e7f7a4` | `.venv-tools` 与 tiktoken 编码文件、`configs/venv_tools.{json,freeze.txt}`、`tools/venv_tools_check.py`（R1-R10） | 951 / 4 |
| D | `39253a8` | 诚信核查（R1-R11）：那道题属于 9 月 5 日已剔除的 9 道之一，主分析题数不变 | 951 / 4 |

- 结束时（main `39253a8` 加本条）：pytest **951 passed, 4 skipped**（4 个跳过同 R1-R6）；`git archive HEAD` 匿名仓库模拟 **934 passed, 21 skipped**
  （比 R1-R8 多出的 1 个跳过是需要 `.venv-tools` 的环境检查）；selftest PASS；`tools/anon_scan.py --require-terms` 0 命中；`tools/anchor_hashes.py --check` 15/15；
  check_test_isolation PASS（7 个集合待标注）；derive_splits_r1 --check PASS；model_registry validate OK；check_gene_versions 退出码 0；venv_tools_check OK。
  冻结演练（清单写在仓库外，用完已删）：gene_anchors 正常，complete=false，缺 21 项（各模块 pending 的条目和还没有的 baselines/），verify PASS。
- 全部提交的作者和提交者都是仓库身份 orgene-r1。没有调用模型（`ollama ps` 始终为空），没有打开或运行 v5 的任何东西，没有读取或输出任何 test 题面，也没有任何 test 结果；
  下载只有 PyPI 的包和两个 tiktoken 编码文件。并行的 E16、E17、E18、E22 的 worktree 和分支没有被改动；用 `git merge-tree` 预演，四个分支与当前 main 都没有冲突。

## R1-R13 2026-09-29 wave1 后续改动的核验（`1c12790..e30e139`）

- 逐项对照任务说明 A1–A8、B、C、D 审了 12 个提交：都已做到。另补 3 个修正提交（下面第 3 条），决定见 DECISIONS R1-D17。
- 测试能否查出错误实现：在仓库外的临时克隆里逐一改坏 A2、A4、A5、A7 的实现，共 17 处（A2：去掉闸门、忽略 run_config 的 split、忽略题号、闸门放到建目录之后、对 dev 也闸门；
  A4：预算超出不中止、预算脚本超出时退出码 0、不传 think、runner 不带登记表、复用第 0 轮不核对条目；A5：缺计数记 0、把失败的调用算进去、旧目录不重算；
  A7：跳过按题激活的配置、digest 只按 geneId、作用域写死、spec 退回 gene_side），每一处都有测试失败。临时克隆用完已删，没有提交这些改动。
- 发现并修正（main 上追加，作者和提交者都是 orgene-r1）：
  - `9a2e9dd`（A7）：原地改 gene 库（包括加激活规则）、激活词表、`features.py`、模板或注册表，冻结演练的 verify 都会失败（逐项试过）；但 requests、validate、score 可以用
    `--genes`、`--lexicon`、`--configs`、`--cond-dir`、`--cases` 读冻结范围外的文件，闸门照样放行，逐请求的 digest 也没有和清单比对，所以"库级 digest + 逐请求 meta"单靠 verify 不够。
    现在过闸门的这几步只读冻结范围内的文件（`freeze.unfrozen_inputs`，在写闸门记录之前拒绝）。
  - `f71cc55`（A2）：生成只经 `runner.run_batch`（`ollama_runner.py`、`api_runner.py`；`run_condition.sh` 经 `ollama_runner.py`），backends 在 main 上只被 run_batch 调用；
    但闸门只看 case_id，不带 case_id 的请求文件（v5 格式）不按题号闸门。现在也从 request_id 取题号。
  - `8dd1ee0`（A1）：自检跳过所有 `.venv*`、`node_modules` 等目录名，而 .gitignore 只写了 `.venv-*/`；新检查要求 git 跟踪或会被 `git add -A` 加入的文件都在自检范围内。
- B：R1-D16 的 8 条与主会话的决定逐条一致，每条注明 "2026-09-28 main session"。A8：DECISIONS R1-D1 至 R1-D16、RECORDS R1-R1 至 R1-R12 编号连续、没有重复；
  抽查引用的 9 个分支提交、`r1_configs.json` 和激活词表的哈希都存在且一致；E12 读数里的 `mamo_complex_lp-0182` 是 dev 题。
- C：`.venv-tools` 的 `pip freeze --all --exclude pip` 与 `configs/venv_tools.freeze.txt` 逐行相同（31 行，sha256 `9f0d7c14…1fcc`，没有路径）；Python 3.14.7、pip 26.2.1。
  两个编码文件的 sha256 独立重算，与登记值和 tiktoken 0.14.0 自带的期望值都相同，文件名是 URL 的 sha1。编码文件改一个字节、或 freeze 文件多一行，`venv_tools_check` 都以退出码 1 失败。
  `.venv-tools/`、`.cache/` 被 git 忽略，自检也不扫；git 跟踪的文件里没有这两处和 PROVENANCE/、releases/v1.0/、data/raw/、paper/evidence/ 下的文件。
- D（脚本只输出题号、行号、计数和布尔值）：v5 原件与 R1 中性版 CANDIDATES.md 相比被删改 7 行，只有 1 行同时有取整说法和数值；该行的数值只与 `mamo_complex_lp-0022`（test）的参考值相同，
  该行还以四位编号写了这道题。0022 在 `seen_20260905_test`（9 道）里，三个 `_excl0905` 集合的 test 题号都不含它，结论与 R1-R11 相同
  （R1-R11 说的"test 题号 0 处"指完整题号形式）。v5 的 `genes.v3.jsonl` 和 R1 的 `genes.r1.jsonl`：完整题号 32 处都是 dev 题，没有指向 test 题的四位编号；
  与某个 test 参考值数值相同的只在日期、版本号、maxApplications、priority、timeout、dev 题号和 audit 说明里的 precision 值（都在 0 到 1 之间）。
  R1 中性版 CANDIDATES.md 里的两个四位编号是 MAMO dev 题（全文只谈 MAMO）。
- 核验结束时（main `8dd1ee0`）：pytest **956 passed, 4 skipped**；`git archive HEAD` 匿名仓库模拟 **938 passed, 22 skipped**（新增 1 个跳过是需要 git 检出的自检）；
  selftest PASS；anon_scan 0 命中；锚点 15/15；check_test_isolation PASS（7 个集合待标注）；derive_splits_r1 --check PASS；model_registry validate OK（4 个条目）；
  check_gene_versions 退出码 0；venv_tools_check OK；env ok。冻结演练（清单写在仓库外，用完已删）：137 个文件，complete=false，缺 21 项，gene_anchors 覆盖注册表的 9 个配置，
  verify PASS，闸门拒绝演练版清单。
- `git merge-tree` 预演：r1/e06、e10、e11、e16、e17、e18、e20a、e22 与 main `8dd1ee0` 都没有冲突；在 e06、e10、e16、e18、e22 的合并树上跑闸门、自检、冻结、backends、run_condition 的测试，都通过。
- 核验没有调用模型，没有打开或运行 v5 的任何东西，也没有任何 test 结果；D 项脚本从 cases 文件只取参考值字段，题面字段不保留、不输出，输出里没有参考值；
  没有碰其他 worktree 和分支，也没有动 experiments/。

## 2026-09-30: gene iteration 0 integration and development campaign

- Preserved the existing eight-file working patch before changes; committed the path-anonymization follow-up separately as `150ff7b`. Integration commit `af604aa` adds the approved library, lexicon, predicate registration, provenance hashes, 37 synthetic integration tests and a sequential dev driver.
- All 87 original proposal predicate examples and 10 activation examples passed through the integrated runtime; approved function ASTs match their source. The proposal JSONL is a 14-record delta, merged into the 17-record seed to produce the full 21-record library.
- Restored cached, checksum-verified ggml 0.22.0 and llama.cpp 0.3.0 via a local recovery tap. Both tokenizer and server report build 10621 / commit c1d0e7a00. No model upgrade or Ollama restart. Remote commands use LC_ALL=C / LANG=C because C.UTF-8 is unavailable on this macOS host.
- Post-integration regression: **1374 passed, 11 skipped, 0 failed in 143.08s** (`runtime/tests tools/tests`). Selftest, split locks, test-isolation check and qwen registry quick check passed; seven analysis sets remain pending annotation. Anonymity scan: zero hits.
- Started `experiments/gene-it0-dev-qwen3-20260930/` through `tools/run_gene_it0_dev.py`; launch PID 41636. `status.json` and stage logs are authoritative. Rehearsal is separate from the 220 dev55 condition units; progress is not a completed effectiveness result. No formal-test run.

Campaign update: the original four rehearsal units completed with full local tokens and correct shared sources. The campaign audit incorrectly counted units/setup.json as a fifth unit and stopped before dev55. Corrected the audit to validate schemas and condition pairing; five focused regression tests pass. The original failure log is preserved outside the repository; its in-repository copy only replaces the home-directory prefix. A separate v2 campaign repeats the rehearsal and then runs all dev55; no records are spliced. Active path: `experiments/gene-it0-dev-qwen3-20260930-v2/`.

## 2026-09-30: completed approved gene dev55 (qwen)

Campaign `experiments/gene-it0-dev-qwen3-20260930-v2/` is complete: MAMO 120/120 and IndustryOR 100/100 main units; rehearsal is separate. Audited all 220 locked dev units, local token completeness, exact C0 call/request/content reuse by C3L and C3E, approved gene/lexicon/predicate hashes, one unchanged code version and decoding setup, current model/condition registries. No incomplete units. Scored original dev references with the runtime primary tolerance (absolute and relative 1e-4); no answer override applied. Only dev case rows were JSON-parsed for scoring.

Correct counts (MAMO / IndustryOR / combined): C0 17/30 / 10/25 / 27/55; C3E 18/30 / 10/25 / 28/55; C3L 24/30 / 12/25 / 36/55; C3 8/30 / 11/25 / 19/55. C3L versus C3E paired table is both correct 28, C3L only 8, C3E only 0, neither 19, difference 14.5 percentage points. All primary-correct answers are solver-record consistent. C3L repairs 9 initially wrong answers; C3E repairs 1; neither introduces a correct-to-wrong transition.

Mean complete-method tokens are C3L 2736.2 and C3E 2036.3 (+34.4%); mean calls 1.564 and 1.345. Shared C0 must not be double-counted as physical execution. The campaign made 203 actual new model calls, with 598771 recorded tokens excluding duplicated C0 counts. C3 remains lower at 19/55; its first round was 15/55, and final errors are 29 objective mismatches plus 7 missing objectives. Preserve this result and diagnose dev failures without claiming a specific gene cause.

Primary evidence: campaign `dev55_results_audit.json` (no problem/spec/program/prompt text), per-stage results/metrics, and untouched unit records. This is descriptive qwen development evidence, not a formal test or a comparison against the old gene library. Original references await independent adjudication; the second model, final gene release, rehearsal, preregistration and freeze remain outstanding. No new genes or model calls were made during this audit.
