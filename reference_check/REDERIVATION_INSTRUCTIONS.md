# 复算说明（给复算 agent）

> 本目录里的题面来自两个运筹优化基准（MAMO ComplexLP、IndustryOR），其中一部分属于实验的 test 集。你是"参考答案核对与题型标注"流程里的独立复算者。请逐条遵守下面的规则。
> 每个组目录里的本说明末尾附有"本组信息"（组名、目录路径、题号清单）。

## 0 任务

本组目录里每个 `<题号>.txt` 是一道题的完整题面。对每一道题：

1. **在看不到任何参考答案的情况下**，从题面独立建立完整的优化模型，写成脚本；
2. 用本机 PuLP 自带的 CBC 求解，记录求解状态和最优目标值；
3. 题号以 `industryor-` 开头的题，另外标出题型（第 3.6 节）；
4. 题面有歧义或缺数据的，写明在哪里、各种读法的结果；
5. 每题给置信度。

结果写进本组目录的 `results.jsonl` 和 `models/`（第 4 节）。

你的结果之后会与另一批互相隔离的 agent 的结果、以及数据集给的参考答案比对，不一致的题交人工裁决。所以结果**越独立、越如实越有用**：拿不准就写拿不准，不要为了"像标准答案"去凑数。标成低置信、交人工裁决，是期望的结果，不算失误。

## 1 隔离规则（必须遵守）

1. **只读写本组目录**（路径见文末"本组信息"）。不要在本组目录之外执行 ls、find、grep、cat 或任何读取、搜索操作（包括 Read、Glob、Grep、codegraph 等工具）。特别是：
   - 不读 `stage1/annotation_agent_hidden/`（参考答案在那里）、`stage1/annotation_packet/`、`stage1/data/`、`stage0/`，以及 `ORgene-EAAI-R1` 下的其他任何目录；
   - 不读 `stage1/annotation_agent/` 下别的组、别的批次和顶层文件；
   - 不读其他工作区（JAM-Research、JAM-Runtime 等）的文件，不连接 Mac Studio，不查 git 历史。
2. **不上网**：不用 WebSearch、WebFetch、浏览器或任何联网工具；尤其不要查 MAMO、IndustryOR 的数据集页面、代码仓库、论文或其附带的题目和答案。本机已装好所需的库，不需要上网。
3. **不看、不猜参考答案**：即使你觉得记得某道题在某个数据集里的答案，也不要使用这个记忆，一律按题面建模求解。
4. **独立**：不和别的 agent 交流，不读别的 agent 的结果。本组里的题也逐题从各自的题面读数据，可以复用代码写法，不要把一题的数据或结论套到另一题。
5. **不改题面文件、本说明和 MANIFEST.sha256**（都是只读的）。只新建 `results.jsonl` 和 `models/` 目录及其中的文件。
6. **不把题面发给任何外部服务**。完成后给主会话的汇报里**不写题面、不写目标值**，格式见第 7 节。

## 2 环境

- Python 解释器：`/opt/anaconda3/bin/python3`（Python 3.12.4；PuLP 3.0.2，自带 CBC 2.10.3；scipy 1.13.1；numpy 1.26.4）。一律写全路径用这个解释器。
- 线性和混合整数模型一律用 `pulp.PULP_CBC_CMD(msg=False, timeLimit=600)` 求解。即使 `pulp.listSolvers()` 列出别的求解器（例如 GUROBI），也**不要用**。
- 非线性、且不能精确线性化的题，可以用 scipy 或穷举，见第 3.5 节。
- 不要安装任何包。

## 3 每道题怎么做

### 3.1 读题、建模

1. 通读题面，逐句找出：决策变量（含单位）、目标（最大化还是最小化什么）、每一条约束、全部数据。
2. **按题面的字面意思写出最直接、正确的模型**，不做近似，也不简化题意。题面给的数据全部照抄进脚本，逐项核对数字、单位和方向。
3. 整数性：
   - 题面明确要求整数，或者变量是不可分割的个数（人、车、台、件、班次、次数等）而题面没说可以取小数：按整数处理；
   - 可分的量（吨、升、小时、金额、比例等）：按连续处理；
   - 拿不准时：按你的判断选一种作主模型，同时把一般整数变量改成连续再求一次（表示逻辑条件的 0-1 变量保持 0-1，模板见附录 A 最后一段），两个值都报告：`integrality_ambiguous: true`，`integer_relaxed_objective` 填改成连续后的值。

### 3.2 写脚本、求解

- 每题一个主脚本 `models/<题号>.py`。程序必须打印下面三行（格式固定，之后会用脚本核对）：
  ```
  STATUS: <pulp.LpStatus[m.status]>
  SOLUTION_STATUS: <pulp.LpSolution[m.sol_status]>
  FINAL_OBJECTIVE: <最优目标值>
  ```
  只有 STATUS 为 `Optimal`、并且 SOLUTION_STATUS 为 `Optimal Solution Found` 时，FINAL_OBJECTIVE 才打印数值，否则打印 `FINAL_OBJECTIVE: None`。原因：不可行时 `pulp.value(m.objective)` 也会返回一个数；达到时间上限时 STATUS 可能仍显示 Optimal，要看 SOLUTION_STATUS。
- 在本组目录下运行并保存输出：
  ```
  /opt/anaconda3/bin/python3 models/<题号>.py > models/<题号>.out.txt 2>&1
  ```
- 脚本模板（自拟小题，不是基准题）见附录 A。

### 3.3 求解后自查

记录结果前逐项核对：

- 每个数据都从题面抄对了吗（数字、单位、百分比、方向）？
- 目标方向（max/min）对吗？每条约束的方向（≤、≥、=）对吗？
- 题面的每一句都在模型里有体现吗？有没有加了题面没有的约束？
- 变量下界（一般非负）、上界、整数性对吗？
- 求解状态是最优吗？打印出的解合理吗？
- `objective` 报告的是模型目标函数的最优值。如果题目最后问的量不是目标函数值（例如问最优时某种产品的产量），另外把题目问的量填进 `asked_value`，在 `notes` 里说明。

### 3.4 题面有歧义或缺数据

- **歧义（AMBIGUOUS）**：题面有两种或以上说得通的理解，而且各自的最优值不同（相对差大于 1e-4）。做法：
  - 每种读法各写一个脚本：`models/<题号>.py` 是你认为最合理的读法；其他读法用 `models/<题号>__r2.py`、`models/<题号>__r3.py`……，输出同样存成 `.out.txt`；
  - `readings` 里逐条写出每种读法和对应结果（第 1 条就是主读法），`issue_note` 写明是哪一句、为什么有歧义；
  - `objective` 填最合理读法下的值。
  - 读法不同但最优值相同的，不算歧义，在 `notes` 里提一句即可。
- **缺数据（UNDERSPECIFIED）**：题面缺少建模必需的数据，建不出完整模型。`issue_note` 写明缺什么。能做出合理补设的，按补设求解，把补设和结果写进 `readings`；`objective` 填 `null`，不要把补设下的值当主值。
- 题面数字前后矛盾：按 AMBIGUOUS 或 UNDERSPECIFIED 处理，写清理由。

### 3.5 非线性题

先按第 3.6 节第 3 步判断能不能**精确**线性化：

- 能：写线性化后的 PuLP 模型求解，它就是主模型；题型标 `NL_LINEARIZABLE`，并填线性化后的类型。
- 不能：可以用 scipy（如 `scipy.optimize.minimize` 多起点、`differential_evolution`）或在整数取值上穷举。
  - 能说明结果是全局最优（凸问题，或在有限取值上完全穷举）：`status` 填 `Optimal`，在 `notes` 写依据；
  - 只能得到局部最优：`status` 填 `LocallyOptimal`，在 `notes` 写用了几个起点、最好的值；
  - 不求解、只判类型：`status` 填 `TypeOnly`，`objective` 为 `null`，在 `notes` 写原因。
- 非线性脚本同样打印 `STATUS:`（写 Optimal 或 LocallyOptimal）和 `FINAL_OBJECTIVE:` 两行，`SOLUTION_STATUS:` 可以不打印。

### 3.6 题型（只对 `industryor-` 开头的题；MAMO 题可以不填）

五类：`LP`、`MILP`、`IP`、`NL_LINEARIZABLE`、`NL_NOT_LINEARIZABLE`。判定标准：

**第 1 步**：按题面的字面意思，写出你认为最直接、正确的模型，不做近似，也不简化题意。

**第 2 步**：如果目标和约束都是决策变量的线性函数，就按变量类型标：
- `LP`：所有决策变量都是连续变量；
- `IP`：所有决策变量都是整数（包括 0-1 变量）；
- `MILP`：既有连续变量，又有整数或 0-1 变量。

补充三点：
- 固定费用、启动成本、二选一（either-or）、若…则…（if-then）、"至多或至少选 k 个"等逻辑条件，教科书上本来就用 0-1 变量加线性约束来写，直接标 `MILP` 或 `IP`，不标 `NL_LINEARIZABLE`。
- 两边同乘一个恒为正的量、移项或合并后就是线性的约束，按线性处理。例如"A 的产量至少占总产量的 30%"。
- 常数之间的乘除、百分比、单位换算都不算非线性。

**第 3 步**：如果最直接的模型里有决策变量的非线性表达式，例如两个决策变量相乘或相除、max/min、绝对值、分段函数、取整（向上或向下）、平方、开方、指数、对数，就判断它能不能**精确线性化**。下面四条都满足，才标 `NL_LINEARIZABLE`，并填"线性化后类型"（`type_after_linearization`）：
1. 能改写成只有线性目标和线性约束的模型，可以新增连续、整数或 0-1 辅助变量；
2. 改写后的最优目标值与原模型**完全相同**，是精确等价，不是近似；
3. 用到的大 M 等常数，能从题面数据或变量明确的上下界推出来；
4. 用教科书中的标准技巧就能写出。常见的精确技巧有：
   - **含 0-1 因子的乘积**：0-1 × 0-1、0-1 × 有界连续变量、0-1 × 有界整数变量，用 McCormick 或大 M 约束；
   - **有界整数变量的非线性函数**，包括整数 × 连续：先做二进制展开或逐值枚举，再按上一条处理；
   - **max / min / 绝对值**：凸方向（如最小化最大值、最小化绝对值）用上境图辅助变量，结果是 LP；非凸方向（如最大化绝对值），变量有界时用 0-1 变量加大 M，结果是 MILP；
   - **分段线性函数**，包括数量折扣和阶梯价格：凸方向直接写成 LP；其他情况用 0-1 变量或 SOS2，结果是 MILP；
   - **线性分式目标**（如最大化利润/成本，分母恒为正）：用 Charnes–Cooper 变换，结果是 LP；
   - **取整**：如"车辆数 = ⌈运量 / 载重⌉"，引入整数变量 n，加约束 载重 × n ≥ 运量。

**第 4 步**：非线性、但不满足第 3 步的题，标 `NL_NOT_LINEARIZABLE`。典型情形：
- 两个连续决策变量相乘，而且都不能离散化。例如价格和销量都是决策变量时的收入 p × q；
- 连续变量的二次或更高次项。例如方差、平方成本、面积 = 长 × 宽；
- 连续变量的开方、指数、对数。例如经济订货批量公式里的开方。

注意：
- 用分段线性去**近似**光滑的非线性函数，不算精确线性化。
- 一道题既有逻辑条件、又有需要线性化的乘积：以需要线性化的非线性项为准，能精确线性化标 `NL_LINEARIZABLE`（线性化后一般是 MILP），不能则标 `NL_NOT_LINEARIZABLE`。
- 整数性按第 3.1 节第 3 条判断；拿不准时按你的判断选题型，`integrality_ambiguous` 填 `true`，并在依据里说明。
- 题面缺数据的题，仍按能看出的结构标题型。

`type_rationale` 写一句：决策变量是什么、是不是整数、约束和目标是否线性；标 NL_* 的，写出是哪一项非线性、用什么技巧线性化，或者为什么不能线性化。

### 3.7 置信度

每题填（HIGH = 高，MEDIUM = 中，LOW = 低）：

- `confidence`（模型和目标值）：
  - HIGH：题意清楚，模型与题面逐句对上，求解器给出最优；
  - MEDIUM：有一处拿不准的建模选择（例如整数性或某句话的理解），但你倾向当前做法；
  - LOW：多处拿不准，或求解状态不是 Optimal，或只找到局部最优，或你怀疑自己的模型有错。
- `type_confidence`（题型，只对 `industryor-` 题填）：同样三档。

## 4 输出格式

### 4.1 `results.jsonl`

放在本组目录下，每题一行，每行一个 JSON 对象（UTF-8；用 Python `json.dumps(obj, ensure_ascii=False)` 写，不要多行缩进）。

| 字段 | 必填 | 取值 |
|---|---|---|
| `case_id` | 是 | 题号，与题面文件名去掉 `.txt` 完全相同 |
| `status` | 是 | `Optimal` / `LocallyOptimal` / `Feasible`（到时间上限，只有可行解）/ `Infeasible` / `Unbounded` / `NotSolved`（报错或没有解）/ `TypeOnly`（只判类型、不求解） |
| `objective` | 是 | 数值（JSON number，不加引号、不加千分位逗号）。status 不是 Optimal、LocallyOptimal、Feasible 时填 `null`；UNDERSPECIFIED 时填 `null` |
| `sense` | 是 | `max` 或 `min` |
| `model_file` | 是 | 主脚本相对路径，如 `models/industryor-0001.py`；TypeOnly 且没写脚本时填 `null` |
| `output_file` | 是 | 主脚本输出，如 `models/industryor-0001.out.txt`；没有时填 `null` |
| `solver` | 是 | `PULP_CBC_CMD`、`scipy`、`enumeration` 或 `none` |
| `model_summary` | 是 | 1–3 句：决策变量、目标、主要约束。用自己的话，不要大段照抄题面 |
| `integrality_ambiguous` | 是 | `true` / `false` |
| `integer_relaxed_objective` | 条件 | `integrality_ambiguous` 为 `true` 时必填：一般整数变量改成连续后的最优值（0-1 变量不改）；否则 `null` |
| `asked_value` | 否 | 题目问的量不是目标函数值时，填题目问的那个量；否则 `null` |
| `issue` | 是 | `NONE` / `AMBIGUOUS` / `UNDERSPECIFIED` |
| `issue_note` | 条件 | `issue` 不是 `NONE` 时必填：哪一句、缺什么、有哪几种读法；否则填 `""` |
| `readings` | 条件 | AMBIGUOUS 时至少 2 条（第 1 条是主读法）；UNDERSPECIFIED 有补设时填；否则 `[]`。每条 `{"reading": "一句话", "objective": 数值或 null, "status": "...", "model_file": "models/...py"}` |
| `confidence` | 是 | `HIGH` / `MEDIUM` / `LOW` |
| `problem_type` | industryor 题必填 | `LP` / `MILP` / `IP` / `NL_LINEARIZABLE` / `NL_NOT_LINEARIZABLE`；MAMO 题可填，不填写 `null` |
| `type_after_linearization` | 条件 | 只在 `NL_LINEARIZABLE` 时填 `LP` / `MILP` / `IP`，否则 `null` |
| `type_rationale` | industryor 题必填 | 一句依据（第 3.6 节末）；MAMO 题可填 `""` |
| `type_confidence` | industryor 题必填 | `HIGH` / `MEDIUM` / `LOW`；MAMO 题填 `null` |
| `notes` | 否 | 其他说明 |

示例（自拟小题，不是基准题；实际的 `case_id` 用本组题号）：

```json
{"case_id": "example-0001", "status": "Optimal", "objective": 2160.0, "sense": "max", "model_file": "models/example-0001.py", "output_file": "models/example-0001.out.txt", "solver": "PULP_CBC_CMD", "model_summary": "椅子、桌子产量为整数变量；最大化利润；木材、工时两条资源约束，桌子至多 10 张。", "integrality_ambiguous": false, "integer_relaxed_objective": null, "asked_value": null, "issue": "NONE", "issue_note": "", "readings": [], "confidence": "HIGH", "problem_type": "IP", "type_after_linearization": null, "type_rationale": "两个产量变量都是整件数，目标和约束都是线性的。", "type_confidence": "HIGH", "notes": ""}
```

### 4.2 `models/`

- 每题至少有 `models/<题号>.py`（主脚本）和 `models/<题号>.out.txt`（它的输出）；
- 其他读法：`models/<题号>__r2.py` 与 `models/<题号>__r2.out.txt`，依次类推；
- 脚本要能用第 2 节的解释器在本组目录下直接重跑，得到同样的输出：不读写 `models/` 以外的文件，不联网，不依赖随机数（用 scipy 多起点时固定随机种子）。

## 5 工作顺序

1. 对照文末"本组信息"的题号清单，确认本组目录里的题面文件齐全；建 `models/` 目录。
2. 一题一题做：读题 → 建模 → 求解 → 自查 → 在 `results.jsonl` 追加一行。
3. 全部做完后检查（可以在本组目录内写个小脚本核对，核对脚本放在 `models/` 里）：
   - `results.jsonl` 行数等于本组题数，每行都是合法 JSON，题号与题面文件一一对应、没有重复；
   - 每个 `model_file`、`output_file` 都存在；
   - `objective` 与对应 `.out.txt` 里的 `FINAL_OBJECTIVE` 一致；
   - industryor 题都填了 `problem_type`、`type_rationale`、`type_confidence`。

准确比速度重要。IndustryOR 的题往往较长、数据多，抄数据时格外小心。

## 6 常见情形

- 求解器报错或超时：`status` 写 `NotSolved` 或 `Feasible`，在 `notes` 说明，`confidence` 填 `LOW`。
- 不可行或无界：先检查是否抄错数据或约束方向；确认后如实报告（`Infeasible` / `Unbounded`，`objective` 为 `null`）。
- 题面给的数据表很大：照样逐项抄进脚本（用列表或字典），不要省略或估计。
- 题面里有多余信息（与最优化无关的数据）：可以不用，在 `notes` 里提一句。

## 7 完成后给主会话的汇报

只写：组名；题数；`results.jsonl` 行数；各 `status` 的题数；`issue` 为 AMBIGUOUS、UNDERSPECIFIED 的题号；`confidence` 为 LOW 的题号；有没有违反第 1 节隔离规则的情况（例如不小心读了本组以外的文件或用了联网工具，有就如实写明）。**不要写题面内容、目标值或模型细节。**

## 附录 A：PuLP 脚本模板（自拟小题，不是基准题）

```python
#!/usr/bin/env python3
# 自拟小题：车间生产椅子（利润 45）和桌子（利润 80）。木材：每把椅子 5、每张桌子 20，共 400；
# 工时：每把椅子 10 小时、每张桌子 15 小时，共 455 小时；桌子至多卖出 10 张；椅子和桌子都是整件。最大化利润。
# 环境正常时输出 STATUS: Optimal、SOLUTION_STATUS: Optimal Solution Found、FINAL_OBJECTIVE: 2160.0
# （32 把椅子、9 张桌子），INTEGERS_RELAXED 一行为 2172.5（整数性改变了最优值）。
import pulp

m = pulp.LpProblem("example_0001", pulp.LpMaximize)          # 或 pulp.LpMinimize
chairs = pulp.LpVariable("chairs", lowBound=0, cat="Integer")
tables = pulp.LpVariable("tables", lowBound=0, upBound=10, cat="Integer")

m += 45 * chairs + 80 * tables, "profit"                      # 目标
m += 5 * chairs + 20 * tables <= 400, "wood"                  # 约束：尽量一句题面对应一条
m += 10 * chairs + 15 * tables <= 455, "labour"

# 常见写法：
# y = pulp.LpVariable("open", cat="Binary"); m += x <= M * y    # 固定费用 / 开关；M 取题面给出的上界
# z = pulp.LpVariable("z"); m += z >= t1; m += z >= t2         # 最小化 max(t1, t2) -> 最小化 z
# x = pulp.LpVariable.dicts("x", keys, lowBound=0)              # 用字典存数据和变量

m.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=600))
status = pulp.LpStatus[m.status]
sol_status = pulp.LpSolution[m.sol_status]
print("STATUS:", status)
print("SOLUTION_STATUS:", sol_status)
if status == "Optimal" and sol_status == "Optimal Solution Found":
    print("FINAL_OBJECTIVE:", pulp.value(m.objective))
    for v in m.variables():
        print(f"  {v.name} = {v.varValue}")
else:
    print("FINAL_OBJECTIVE: None")

# 只在整数性拿不准时需要（第 3.1 节第 3 条）：把一般整数变量改成连续再求一次，0-1 变量保持不变。
# PuLP 把 cat="Binary" 存成上下界为 [0, 1] 的 Integer，所以按上下界识别 0-1 变量。
to_relax = [v for v in m.variables()
            if v.cat == pulp.LpInteger and not (v.lowBound == 0 and v.upBound == 1)]
for v in to_relax:
    v.cat = pulp.LpContinuous
m.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=600))
print("INTEGERS_RELAXED:", pulp.LpStatus[m.status], pulp.value(m.objective),
      f"({len(to_relax)} general-integer variables made continuous; binaries kept)")
for v in to_relax:
    v.cat = pulp.LpInteger
```
