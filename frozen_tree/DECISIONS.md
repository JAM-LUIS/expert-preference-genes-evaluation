v5 出处：DECISIONS.md sha256 `2435c35aa9e7e1d717e546b62437664cd49e6d02d29a12943869cc8d70d7d970`；RECORDS.md `2082c1fbd801aa4fc60f21b356f7c462de97c444102e7697a87f408c90c89b35`；HANDOFF.md `2e4e143064058441d9691873c12960043ecfe534cac05e3f039fac740411e576`（原件在 `PROVENANCE/v5_pristine/`，不入库）。

# DECISIONS — ORgene R1

R1 是 v5（9/7 冻结 gene 库 1.0）之后的修订工作区。本文件只记已经定下的做法和理由；执行过程和数字写在 `RECORDS.md`，下一步写在 `HANDOFF.md`。
v5 的决策原文不搬进来，需要时按上面的哈希在出处副本里查。写法保持中性：不写人名、机构名、主机名和绝对路径，"作者"指论文作者。

## R1-D1 工作区与 v5 的关系（2026-09-28）

- v5 只读。R1 只从 allowlist（runtime、analysis、conditions、genes、schema、data 和 v5 的三份文档）复制，不复制 experiments/。
  复制前后在 v5 端各算一份 SHA256SUMS，两份相同，且 v5 没有比复制开始时间更新的文件（`RECORDS.md` R1-R1）。
- 原样副本放 `PROVENANCE/v5_pristine/`（只读），v5 的 gene 库 1.0、conditions/、schema/ 另放 `releases/v1.0/`（只读）作回归基准。
  这两个目录和 `data/raw/`（按 v5 的 data/README，原始基准文件不入库、不发布）都不进 git。
- v5 的 7 个运行脚本写死了 v5 的绝对路径，在 R1 执行会往 v5 里写文件，已移出 runtime/，只存档在 `PROVENANCE/v5_runtime_scripts_disabled/`（不可执行）。
- 9 月 7 日在 test 上跑完的 C0、C1、C2 运行已被取代：不复制、不打开、不复用，在运行登记里记为"被取代的运行"。按最终设计定稿后，所有条件在 test 上重新跑一次。

## R1-D2 中性写法从一开始就做（2026-09-28）

- 冻结时算的哈希到投稿时不用改，所以 R1 的 git 工作树从第一个提交起就不含人名、机构名、主机名和本机绝对路径。
- 带这类信息的 v5 文件只留在出处副本；R1 用中性派生版（两边哈希的对应在 `PROVENANCE/v5_anchor_hashes.json`）：
  - `data/cases/*.jsonl`：只把第 1 行 `_header.raw_path` 改成相对路径，第 2 行起逐字节不变；
  - `data/splits/*/SPLIT_LOCK.json`：只改 `cases_path`（相对路径）和 `cases_sha256`（中性版的哈希）；dev/test 题号文件与 v5 逐字节相同，`dev_sha256`、`test_sha256` 不变；
  - `data/mamo_underspecified_ids.json`：只改 `_note` 里的人名，题号、规则和版本不变；
  - gene 工作库 `genes/genes.r1.jsonl`：见 R1-D4；
  - `genes/CANDIDATES.md`、`data/EXCLUSIONS.md`、`data/README.md`：中性版，文件头写明改了什么。
- v5 文档里有几处逐题引用了 test 题（EXCLUSIONS 的欠定题一节、README 的一行补充、CANDIDATES 的一个对照例）。这些内容不进 R1 工作树，
  建 R1 时 EXCLUSIONS 那一节也没有打开，只用脚本统计过它引用的题号属于 test。理由：写 gene 的人在 test 运行之前不看 test 题的信息。
- 中性写法的自检（tools/anon_scan，E21）做成每次提交都跑的测试，不单独做一步匿名化。

## R1-D3 路径与解释器（E02，2026-09-28）

- 写进任何产物的路径一律相对仓库根目录（`runtime/orgene/paths.py`）；仓库外的路径只记 `<outside-root>/<文件名>`；运行命令行记录时根目录写成 `$R1`。
- 执行生成程序的解释器固定为 `$ORGENE_PY`，默认 `/opt/homebrew/bin/python3`（PuLP 3.3.2，CBC 为 arm64 的 2.10.13），不从 PATH 取。
  理由：非交互 shell 的 PATH 里是系统自带的 python3，没有 pulp，生成程序会全部执行失败。
  `orgene_cli.py env` 让这个解释器真解一道一变量 LP（期望 `Optimal 1.0`），`requests` 和 `validate` 启动时都做这项检查，失败就退出；结果写进 run_config 的 `python_env`。
- 这个 Python 与其他项目共用，R1 不往里装任何包。分析和分词器另建 `.venv-tools`（不入库）。

## R1-D4 gene 工作库（2026-09-28）

- 工作库是 `genes/genes.r1.jsonl`，起点是 v5 的 gene 库 1.0。唯一的改动：`orgene.objective.aggregates_declared_variables` 的 audit 文字去掉人名，
  内容变了，版本号由 1.0.0 升到 1.0.1。谓词、严重度、合同文字、修复指令都没变，所以四个系统提示和 C3 合同的哈希与 1.0 相同，
  C3E 的激活集 digest 也相同；C3、C3L 的 digest 因这条 gene 的 audit 和版本变了而不同（数值见 `RECORDS.md`）。
- 版本规则：同一 geneId 的记录与上一个 release 不同，版本号必须升高（`runtime/tests/test_v1_regression.py` 已按此检查 1.0 → 工作库）。
- 这里的 "release 1.0" 指 v5 在 9/7 冻结的库；按修订设计，最终的新库另起版本，冻结前按 D3 写进冻结清单。

## R1-D5 作者 2026-09-28 定下的实验做法（经主会话转达）

- 修复轮数：C3L、C3E、C3（以及 C2E）都按最多 2 轮运行，主结果用"最多 2 轮"；1 轮的结果从同一次运行截取，作修复阶梯上的次要结果，不另跑。
- dev 口径：gene 迭代和检查点诊断的对错信号只用清洗后的 55 道 dev 题（MAMO 清洗子集 dev 30 + IndustryOR dev 25）；被清洗删掉的 30 道 MAMO dev 题只看错误类型，不作对错信号。
- 参考答案核对结论的计分规则（test 前写定并记哈希）：
  - CORRECT：保留原参考值；
  - CORRECT_ROUNDED：换成核对得到的精确值，另报用原值打分的结果；
  - INCORRECT（两人一致或经裁决）：换成更正值，另报用原值打分的结果；
  - AMBIGUOUS、UNDERSPECIFIED：移出主分析集合，只留在全量敏感性分析里；
  - 没抽到的题：保留原参考值。
- Ollama 主实验默认 `keep_alive 0`（每题冷加载，避免 KV 缓存命中改变贪心输出），成本在 dev 彩排里测。
  运行主机的 Ollama 服务开着 flash attention 和 q8_0 KV 缓存，不改配置，论文如实写明。
- 工程方案第 6.3 节的 14 条默认做法全部采用：
  1. qwen3 的所有调用统一 num_ctx 32768（R0 回归检查与 16384 的输出是否相同）；
  2. 温度 0、seed 1；方差子集温度 0.7，显式写 top_p 0.95、top_k 20，seed = base + k；
  3. 主打分用程序打印的 FINAL_OBJECTIVE，"核实准确率"作次要指标；
  4. C3E 沿用 v5 的定义（5 条 gene，含两条静态协议检查），只修 maxApplications 的对称性；
  5. qwen3 也整体随机调度，确定性检验照常报告；
  6. 激活消融只做在主线上（C3L-ALL 对 C3L）；C3 全部激活时只报告提示长度；
  7. 不跑"C3 + 通用修复"；阶梯为 C0 → C3E → C3L@1 → C3L@2，以及 C2 → C2E、C3@0 → C3@1 → C3@2；
  8. 改写版本：C0 基础提示、C1、C3 各 2 个，只在预注册的 100 题方差子集上跑，两个模型都跑；
  9. ORA：提示用自己的措辞；修复轮数与 C3L 相同；token 上限取 C3L 在 dev 上的 P90；
  10. AlphaOPT：只用 qwen3；PuLP 协议；从清洗后 55 道 dev 学经验库；不用 gold program；debug 次数默认 5 次作主结果、与 C3L 同轮数作敏感性；n_runs=1；
  11. ORLM 用原生 coptpy 加追加的打印代码，另报官方口径；LLMOPT 用 Q8_0 两步推理、不带自纠错，目标值取求解记录；
  12. 长度分析以按题目分层的条件 logistic 回归为主，GEE 作敏感性分析；
  13. 测量抽查：以题为单位，从主分析题集（不含 9 月 5 日看过题面的 9 道 test 题）按种子抽 50 题，按"基准 × 求解器判对/判错"分层（以 C3L 为准）；每题把 C0、C3E、C3L 输出里互不相同的程序去掉注释和条件痕迹后交两人判；
  14. 分析和分词器装进 R1 自己的 `.venv-tools`，不动共用的 Python；装不上就换一台机器跑分析，同样固定版本。

## R1-D6 分析集合与保持原划分的规则（E14，2026-09-28）

- 划分不变：9/5 冻结的 dev/test 归属原样保留（`data/splits/` 只读）。分析子集只删题、不补题、不重新抽样，每道题留在冻结时的那一边
  （`split.derive_subset_lock`，产物 `data/splits_r1/`）。"新数据源整体进 test"（D7）已实现为 `split.assign_new_source`，按已确认的设计不使用。
- 题号只来自阶段 1 的分析集合文件 `data/analysis_sets/analysis_sets.v2.json`（逐字节复制；sha256 记在定义文件里，哈希不符就拒绝使用）。
  分析用的集合只在 `configs/analysis_set_defs.r1.json` 里按集合名和清单名定义，代码里不写题号：
  - main（主分析，test）：MAMO 清洗子集去掉 9 月 5 日看过的题、再去掉 Q3 移出的题；IndustryOR 2026 修订版去掉 9 月 5 日看过的题、NL_NOT_LINEARIZABLE 和 Q3 移出的题。参考值用覆盖后的版本。
  - sens_orig_ref：main 的题，用原参考值。
  - sens_full211：MAMO 全部 211 题和 IndustryOR 全部题（都去掉 9 月 5 日看过的题，IndustryOR 再去掉 NL_NOT_LINEARIZABLE）；Q3 移出的题留在这里，用原参考值打分（它们没有覆盖值）。
  - sens_incl0905、sens_full211_incl0905：main、sens_full211 各自加回 9 月 5 日看过的题；只有这两个结果包含它们。
  - well_specified：main 去掉欠定关键词粗筛命中的题（与 v5 `paired_bootstrap.py --subset` 用同一文件）。
  - nl_separate：IndustryOR（去掉 9 月 5 日看过的题）里 NL_NOT_LINEARIZABLE 的题，单独报告，不计入 MDE 的样本量；可以为空。
  - dev_signal55（MAMO 清洗 dev 30 + IndustryOR dev 25）是 dev 上唯一的对错信号口径（R1-D5）；dev_all85 只用于管道检查；
    dev_error_type_only30（被清洗删掉的 30 道 MAMO dev 题）只看错误类型。
- 对工程方案 E14 小节的两处解释（待作者确认）：
  1. Q3 的"移出主分析"对 MAMO 和 IndustryOR 同样适用。方案里 main 的公式只在 IndustryOR 一侧减去 Q3 移出的题，但 R1-D5 的 Q3 规则不分基准，参考答案核对也抽了 MAMO 清洗子集。
  2. "只留在全量敏感性分析"理解为 sens_full211 同时包含两个基准的 Q3 移出题。方案原定义里 sens_full211 的 IndustryOR 部分取 main 的 IndustryOR 部分，这样 IndustryOR 的 Q3 移出题就不在任何敏感性集合里。
- 依赖题型标注和参考答案核对的集合，在两份结果导入之前状态是"待定"：解析时这两个清单按空处理并标出，严格模式（分析代码的默认）拒绝使用。
  导入由 `data/ingest_annotations.py` 按 R1-D5 的 Q3 规则执行：只读协调人脚本生成的无题面汇总表，只收封闭词表、数值和单字母代号（A、B、C），其他内容一律拒绝且不回显；
  参考答案覆盖文件用 E13 的格式和校验（`runtime/orgene/refs.py`），全部抽中的题都有最终结论之后才写出；`data/exclusions_r1.json` 的 q3_removed 必须与覆盖文件里 AMBIGUOUS、UNDERSPECIFIED 的题一致。
- IndustryOR 的许可常量改为 CC-BY-NC-4.0（2026-09-05 核实的数据卡字段）；已锁定的 cases 文件不改。

## R1-D7 配置注册表（E03，2026-09-28）

- 实验配置登记在 `configs/r1_configs.json`（合并时 sha256 `85c5a3003324e6387dd581c29e13e71ede911cb9bf82be9adf8c437eacefd361`）。代码只读字段
  （prompt、round0、validator、gene_scope、activation、repair、closing、max_rounds、num_predict、num_ctx、variant、pipeline、token_cap），不按配置名分支；
  基线适配器另列在 adapters 里，不走这条流水线。
- gene 记录的作用域名只用 C3、C3L、C3E，配置用 gene_scope 指向它们（C2E、ORA 指向 C3E，C3L-ALL 指向 C3L）。
  C0、C1、C2 登记为 validator observe、gene_scope C3、activation all：它们第 0 轮的输出统一离线跑谓词，只记录、不修复。
- C3 的合同按题编译；每条请求在 meta 里记自己的系统提示、合同、激活 trace 和特征哈希。发给模型的消息只有 system 和 user 两条，
  不含配置、请求和题目编号（`conditions.check_messages`）。C1 的长度目标仍是"C3 全部激活时的提示长度"（v5 规则），token 配平归 E11。

## R1-D8 按题激活（E04，2026-09-28）

- gene 记录新增可选字段 `activation`：规则只能引用题面特征，不能引用规范、程序或执行结果；没有这个字段等于总是激活。
  特征只从题面计算（`runtime/orgene/features.py`），词表 `genes/activation_lexicon.v1.json` 目前是种子版（sha256 `fb98272e58105e27…`），1C 可整体替换并记新哈希。
- per_problem 模式不给特征就报错，不会静默全部激活；all 模式是全部激活的消融（C3L-ALL）；none 对应不用 gene 的配置。
- 同一 geneId 的内容有任何变化（加 activation 也算）必须升版本号，`tools/check_gene_versions.py` 对照上一个 release 检查。
  规则的正反例写在 `genes/activation_examples.r1.json`；devEvidence 只能是 dev 题号。
- dev 激活报告 `analysis/r1/activation_report.py` 分两栏：清洗后 55 道 dev 题（对错信号）和被清洗删掉的 30 道（只看错误类型）；test 模式只输出激活率，冻结后才能运行。

## R1-D9 修复阶梯、C3E 的对称性、C2E（E05，2026-09-28）

- C3E 的修复消息由固定的通用模板生成（模板 sha256 `ddb95169c40091c83210c5217a29a8bbf124d55f71fdaa392178d70fc6e41dcb`，测试里钉死），
  按每条 gene 的 `repair.maxApplications` 记账，与 C3L 相同（R1-D5 默认做法第 4 条的落实）。没有 gene 用完次数时，第一次修复消息与 v5 逐字节相同，v5 的 dev 读数仍可对照。
- C2E：系统提示 C2，第 0 轮复用 C2，用 C3E 的 5 条 gene 校验，用同一个通用模板修复，结尾要求"JSON 规范 + 完整程序"。C3P 已删。
- 修复配置一律最多 2 轮；"最多 1 轮"和"第 0 轮"两个点由 `runtime/orgene/ladder.py`（`analysis/derive_repair_ladder.py`）从同一次运行截取，不调用模型，也不重跑程序。
- 修复消息里的程序路径只留 `prog.py`，不带随机的临时目录；否则同一单元跑两次，修复请求会不同，影响按请求哈希回放的假后端和确定性检验。
- 通用修复消息除 stderr 代码块和状态值外，每一行都必须是模板行（`genes.generic_message_violations`，彩排第 10 项用）。每一轮记 `repair_applied_genes`，冲突统计见 `ladder.conflict_summary`。

## R1-D10 runner 与逐调用记录（E08，2026-09-28）

- runner 是 `runtime/orgene/backends/`（Ollama、OpenAI 兼容、Anthropic、llama.cpp）上的薄包装。选项每次都显式发送，默认 num_ctx 32768、keep_alive 0、think false；
  seed = 基数 + 重复序号。
- 每次调用一条记录：started_at、finished_at、seed、digest、sent_opts、request_sha256、done_reason、服务器的 token 数、local_tokens；v5 的 parse_ok 已去掉。
- `request_sha256`：实际发送的请求体去掉只影响传输的 `stream`、`keep_alive` 后，取规范 JSON（键排序、无空白、UTF-8、拒绝 NaN）的 sha256；
  对 Ollama 覆盖 model、messages、options、think、format。keep_alive 不在内（同一请求冷、热加载时哈希相同），它单独记录。
- 续跑时 backend、身份、选项、seed、格式、请求文件、登记表条目、本地计数器有任何一项不同就拒绝；跑完重取模型身份，变了就以状态 3 退出。
  开跑时只记其他已加载模型的个数，不记名字。API 密钥只从环境变量读，不进任何记录。

## R1-D11 本地 token 计数（E09，2026-09-28）

- qwen3 的本地计数用 llama.cpp 的 llama-tokenize 读 Ollama 的权重 blob 本身（固定加 `--no-escape`）；提示按 Ollama 的 qwen3 模板逐字复刻渲染
  （`tokcount.RENDERER_QWEN3` = `qwen3-ollama-template.v1`，在 19 个参考对话上与 Go text/template 的输出逐字节相同）。不做估算。
- runner 默认开启本地计数：服务器报的 digest 必须等于本地 manifest（不报也拒绝）；第一次调用前先把全部请求渲染一遍；计数器身份参与续跑比对。
- 合并 E08 后，单次调用计数失败时保留回答，local_tokens 为 None，原因写进 local_tokens_error；runner 的 metrics.json 记下缺本地计数的调用数。
- API 模型的 tiktoken 计数接口已写好；编码文件和 tiktoken 版本在建好 `.venv-tools` 后登记。

## R1-D12 求解记录器与虚报（E12，2026-09-28）

- `execute.run_program` 默认经 `runtime/orgene/solve_recorder.py` 运行生成的程序：用 `sys.monitoring` 记下 PuLP、Pyomo、coptpy 的每次求解（状态、目标值、用时），
  不改变程序的 stdout、stderr 和返回码。
- 主打分仍用程序打印的 FINAL_OBJECTIVE（R1-D5 默认做法第 3 条）；每行另记虚报标记和 `verified_correct`（打印的目标值与求解记录一致且判对），
  核实准确率作次要指标。打印值与求解值不符只是因为取整时，另标 `objective_rounding_only`。

## R1-D13 三档容差与参考答案覆盖（E13，2026-09-28）

- 判定式 `|obj − ref| ≤ max(t, t·|ref|)`，t 取 1e-6、1e-4、1e-2 三档；主口径仍是 1e-4（结果行的 `correct`），另两档和原参考值口径另行记录。
- 参考答案覆盖按 R1-D5 的计分规则实现（`runtime/orgene/refs.py`，规则摘要 `3bb2fccc936503fd98569b965bd880da1bc917a76680436cb94a4f1dc21dd03c`，测试里钉死）。
  覆盖文件 `data/reference_overrides/<source>.json` 不允许自由文本，核对人只写短代号；任何一条校验不过就拒绝打分。
- `score --freeze-manifest` 在覆盖文件的哈希与冻结清单不符时拒绝打分；过了闸门的 test 打分自动带上清单（E21）。

## R1-D14 模型与解码参数登记表（E19，2026-09-28）

- 每个 runner 调用都对应 `configs/model_registry.json` 的一个条目：runner 带 `--registry/--registry-entry` 运行，发送的设置与条目有任何不同就在发送前拒绝，
  运行的 config.json 记条目的 sha256。条目里含观测到的模型身份和服务设置，所以这个哈希也覆盖它们。
- 条目：`qwen3-8b.main`（温度 0、seed 1、top_k 20、top_p 0.95、num_ctx 32768、num_predict 6000、think false、keep_alive 0）；`qwen3-8b.var07`（温度 0.7，seed = 1 + k）；
  `qwen3-8b.r0-v5`、`qwen3-8b.r0-ctx16k`（只用于 R0 回归）。`runtime/run_condition.sh` 默认用 `qwen3-8b.main`。
- 观测事实只由 `tools/model_registry.py update` 从只读快照写入，快照文件入库；`check` 核对。Ollama 服务的 flash attention 和 q8_0 KV 缓存从
  launchd 任务、服务进程环境、服务日志启动行三处读取且一致，日志里登记模型的每次加载也都用这两项；不改服务配置，论文如实写明。

## R1-D15 冻结、中性写法自检与 test 闸门（E21，2026-09-28）

- `tools/freeze.py make|verify|register|gate`：冻结清单 `FREEZE_MANIFEST.json` 按 `configs/freeze_spec.json`（方案 5.3 节的全部条目）逐文件记 sha256，
  另有计算项：冻结目录的 git tree 哈希、各配置的 gene 锚点。核对用 tree 哈希，不用 commit 哈希，所以匿名克隆可以复现。缺项时只能写演练版（complete=false）。
- test 闸门：碰到密封题（test 和 eng_holdout 的题号，或运行记为 test）的每一步（requests、模型调用、validate、score、含 test 的快照）都要求清单完整、
  核对通过，并带有对应当前内容的 OSF 登记号；每次放行追加到运行目录的 `freeze_gate.jsonl`。冻结顺序见 HANDOFF 第 6 节。
- 中性写法自检 `tools/anon_scan.py` 是每次提交都跑的测试，不改任何文件：工作树、产物目录（experiments、paper/evidence）和 git 元数据里
  不能有用户目录路径、非保留域名的邮箱、身份词、本机登录名和主机名。身份词表不入库（`PROVENANCE/anon_terms.txt`）。所有提交都用仓库身份 orgene-r1。

## R1-D16 主会话定下的技术决定（2026-09-28 main session；作者可推翻）

1. 参考答案覆盖文件（`data/reference_overrides/`）含 test 题号和更正后的参考值（不含题面）。写 gene 的会话不打开这些文件，只通过 `score` 使用。（2026-09-28 main session）
2. 容差判定按 IEEE 754 双精度计算，不加 epsilon，与 v5 的 1e-4 档一致；预注册写明这一点。（2026-09-28 main session）
3. 覆盖文件第一次生效时（会改变部分 dev 题的对错），在 RECORDS 记下它的哈希和受影响的 dev 题数；1C 的对错信号以当时生效的覆盖文件为准，如实记录。（2026-09-28 main session）
4. 采纳 R1-D6 里 E14 的两处解读：Q3 规则移出的题（AMBIGUOUS、UNDERSPECIFIED）从两个基准的 main 都移出；sens_full211 保留两个基准的这些题。R1-D6 的"待作者确认"由本条代替。（2026-09-28 main session）
5. 方差子集的 seed 基数取 1（seed = 1 + k）。R0 回归保留 `qwen3-8b.r0-v5`（num_ctx 16384、keep_alive 30m）和 `qwen3-8b.r0-ctx16k`（16384、冷加载）两个条目，每次比较只差一个因素。（2026-09-28 main session）
6. 虚报率的主口径不把只是取整打印算作虚报（`objective_rounding_only` 单列），同时报告全部目标值不一致的口径；预注册写明。（2026-09-28 main session）
7. OSF 登记号放在 FREEZE_MANIFEST 的 `osf` 块里（不在 `content_sha256` 内）；提交前统一换成匿名 view-only 链接，不影响冻结哈希。（2026-09-28 main session）
8. 合并 E09 后，单次调用的本地计数失败不再中止运行（保留回答，原因记在 `local_tokens_error`）；彩排检查第 5 项要求缺本地计数的调用数
   （runner 的 metrics.json 里的 `n_calls_missing_local_tokens`）为 0，不为 0 就查明原因。（2026-09-28 main session）

## R1-D17 按题激活的冻结口径与 test 各步读的文件（wave1 后续改动核验，2026-09-29）

- 冻结清单的 `gene_anchors` 对按题激活的配置（C3、C3L）只记作用域 gene 集的 digest（库级），按题的激活集逐请求记在 meta 里（A7 的做法，保留）。
  按题的激活集由 gene 库、激活词表、`features.py`、激活代码和题面决定；这些都按文件哈希和 git tree 冻结，原地改动由 verify 查出。
- 补充：过闸门的 requests、validate、score 只读冻结范围内的文件：三步都读的 cases；requests、validate 的 gene 库和配置注册表；requests 的激活词表和提示模板。
  文件列在清单里，或在清单记了 tree 哈希的目录里被 git 跟踪，才算在冻结范围内；否则在写闸门记录之前拒绝（`freeze.unfrozen_inputs`）。
  这样按题的 digest 不必逐题写进清单，也不会因为改用范围外的文件而与冻结内容脱节。
- runner 的闸门除了 case_id，也从 request_id（第一个 "." 之前）取题号，不带 case_id 的请求文件同样受闸门约束。

## 2026-09-30: author-approved gene iteration 0 (development)

The author approved all 12 packet_it0 proposals (G1-G4 and M1-M8) as proposed and requested immediate integration and development experiments. The approved development library is `genes/genes.it0.approved.jsonl` (21 genes: 7 unchanged, 10 amended, 4 new), with `genes/activation_lexicon.v2.json`. `configs/gene_iteration.it0.json` records source and runtime hashes. Existing predicate IDs and the working seed library remain available for historical regression; development runs explicitly mount the approved paths. This is not the final frozen release. No new gene content was authored during integration.

Run qwen3-8b.main on the locked dev55: C0/C3L/C3E/C3, local token counting enabled, registry parameters unchanged. Start with one real dev case; proceed to MAMO30 and IndustryOR25 only if the rehearsal records pass structural, provenance and token audits. Use fixed ordering for development only; E07 and the formal-test freeze requirements remain pending. Do not run formal test or paid APIs.
