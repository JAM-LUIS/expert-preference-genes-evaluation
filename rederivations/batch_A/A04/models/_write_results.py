#!/usr/bin/env python3
# Builds ../results.jsonl from the .out.txt files in this folder, then verifies it.
import json, os, re
here = os.path.dirname(os.path.abspath(__file__)); grp = os.path.dirname(here)
def out(name):
    txt = open(os.path.join(here, name + ".out.txt")).read()
    st = re.search(r"^STATUS: (.*)$", txt, re.M).group(1).strip()
    fo = re.search(r"^FINAL_OBJECTIVE: (.*)$", txt, re.M).group(1).strip()
    rl = re.search(r"^INTEGERS_RELAXED: \S+ (\S+)", txt, re.M)
    return st, (None if fo == "None" else float(fo)), (float(rl.group(1)) if rl else None)
def row(cid, sense, summary, solver="PULP_CBC_CMD", amb_int=False, asked=None, issue="NONE", issue_note="",
        readings=None, conf="HIGH", ptype=None, tlin=None, trat="", tconf=None, notes="", null_obj=False):
    st, obj, rel = out(cid)
    rd = []
    for text, f in (readings or []):
        s2, o2, _ = out(f)
        rd.append({"reading": text, "objective": o2, "status": s2, "model_file": f"models/{f}.py"})
    return {"case_id": cid, "status": st, "objective": None if null_obj else obj, "sense": sense,
            "model_file": f"models/{cid}.py", "output_file": f"models/{cid}.out.txt", "solver": solver,
            "model_summary": summary, "integrality_ambiguous": amb_int,
            "integer_relaxed_objective": rel if amb_int else None, "asked_value": asked,
            "issue": issue, "issue_note": issue_note, "readings": rd, "confidence": conf,
            "problem_type": ptype, "type_after_linearization": tlin, "type_rationale": trat,
            "type_confidence": tconf, "notes": notes}
R = []
R.append(row("industryor-0003", "max",
    "每月工人数、招聘、解雇、自产量、外包量为整数，加班工时、库存、缺货为连续；最大化净利润=销售收入−原料−外包−库存−缺货−正常工资−加班工资−招聘/解雇费用；约束为人数平衡、工时能力（每件5小时，正常160小时/人，加班≤20小时/人）、库存/缺货平衡、期末库存≥10000且缺货为0。",
    amb_int=True, conf="MEDIUM", ptype="MILP",
    trat="人数、招聘/解雇、产量、外包量为整数，加班工时、库存、缺货为连续，目标和约束都是线性的。", tconf="MEDIUM",
    notes="解雇/招聘当月生效；销售收入按满足的需求（当月需求+缺货变化）计，期末缺货清零故总销量等于总需求；初始库存不计成本。产量、外包量、人数是否必须为整数题面未明说，按整数作主模型并报告连续松弛值。"))
R.append(row("industryor-0008", "min",
    "0-1 变量表示工人是否承担某项任务；每项任务恰由一名工人完成，每名工人至多一项任务；最小化总工时。",
    ptype="IP", trat="全部为 0-1 指派变量，目标和约束线性。", tconf="HIGH"))
R.append(row("industryor-0009", "max",
    "四种玩具产量为整数变量，另有是否生产的 0-1 变量；最大化利润；木材、钢材约束，卡车与火车互斥，生产船则必须生产飞机，船数不超过火车数。",
    asked=1, conf="MEDIUM", ptype="IP",
    trat="产量为整数、是否生产为 0-1 变量，逻辑条件用 0-1 变量加线性约束表示，目标和约束线性。", tconf="HIGH",
    notes="题面问“应生产多少种玩具”，asked_value 填最优解中产量为正的玩具种类数；objective 为最大利润。大 M 取由木材、钢材推出的各产量上界。若该问句本意是各种玩具各生产多少，则答案为脚本输出中的产量。"))
R.append(row("industryor-0012", "min",
    "各型号容器产量（整数）、是否启用设备（0-1）、用大容积型号替代满足小容积需求的数量；最小化变动成本加固定启用费；每种需求被容积不小于它的型号满足，产量为正则启用设备。",
    ptype="IP", trat="产量与替代量为整件数，启用设备为 0-1 变量，固定费用用 0-1 加线性约束表示，目标和约束线性。", tconf="MEDIUM",
    notes="若把产量视为连续则为 MILP，最优值不变（需求为整数）。"))
R.append(row("industryor-0031", "max",
    "变量为每种产品在各台设备上加工的件数（整数），A 工序件数与 B 工序件数相等；最大化 (售价−原料费)×件数 − 各设备加工费率×占用机时；各设备机时不超过有效机时。",
    amb_int=True, conf="MEDIUM", ptype="IP",
    trat="决策变量是各产品在各设备上的加工件数，按整件处理，目标和约束线性；若允许小数件数则为 LP。", tconf="MEDIUM",
    notes="加工费按“每机时费率×实际占用机时”计（按表头字面）。件数是否必须取整题面未说明，主模型取整数并报告连续松弛值。"))
R.append(row("industryor-0036", "min",
    "弧 0-1 变量、各客户开始服务时刻和累计载重为连续变量；最小化总欧氏行驶距离；每客户恰被访问一次，至多 5 辆车，载重≤200，硬时间窗（早到等待），服务 90 分钟，返回车场不晚于 1236。",
    conf="MEDIUM", ptype="MILP",
    trat="弧选择为 0-1 变量，开始服务时刻和载重为连续变量，时间窗与容量用大 M 线性约束表示，目标线性。", tconf="HIGH",
    notes="题面未给行驶速度/行驶时间，按惯例假设行驶时间（分钟）等于欧氏距离、距离不取整；大 M 由时间窗上下界推出，并据时间窗和容量预先删去不可行弧。"))
R.append(row("industryor-0041", "max",
    "各年投入各项目的金额及闲置现金为连续变量；最大化第 3 年末本利和；每年初可用现金平衡，项目 2、3、4 有投资上限。",
    ptype="LP", trat="投资金额为连续变量，现金平衡约束与目标都是线性的。", tconf="HIGH",
    notes="允许现金闲置（不计息）。"))
R.append(row("industryor-0055", "min",
    "7 门课是否选修的 0-1 变量；最小化选课门数；数学、运筹、计算机各至少 2 门（跨类课程同时计入），并满足先修关系。",
    ptype="IP", trat="全部为 0-1 变量，类别覆盖和先修约束线性，目标线性。", tconf="HIGH",
    notes="最优选课方案见脚本输出；最少门数的方案可能不唯一。"))
R.append(row("industryor-0056", "max",
    "每月购入量、售出量为连续变量；最大化三个月销售收入减购货支出；售出量不超过月初库存，购货款不超过可用资金，库存不超过 5000，季末库存等于 2000。",
    issue="AMBIGUOUS",
    issue_note="仓库容量 5000 的约束时点题面未说明：当月先卖出再进货（约束月末库存）与进货到库时月初库存尚未售出（约束月初库存+当月购入）两种理解下最优值不同。另外购货款能否用当月销售收入支付也未说明，但该点不改变最优值（r2 与 r3 相同、r4 与主读法相同）。",
    readings=[("当月先售后购：容量约束为 月初库存−售出+购入≤5000，当月销售收入可用于当月购货", "industryor-0056"),
              ("容量约束为 月初库存+购入≤5000，当月销售收入可用于当月购货", "industryor-0056__r3"),
              ("容量约束为 月初库存+购入≤5000，购货只能用月初资金", "industryor-0056__r2"),
              ("容量约束为 月初库存−售出+购入≤5000，购货只能用月初资金", "industryor-0056__r4")],
    conf="MEDIUM", ptype="LP", trat="购入量、售出量为连续变量（粮食可分），库存、资金约束和目标都是线性的。", tconf="HIGH",
    notes="利润按三个月现金收支差计，不计期初、期末库存价值；因季末须留 2000 担库存，利润为负。季末库存按等于 2000 处理。"))
R.append(row("industryor-0081", "min",
    "每辆车停在哪一侧的 0-1 变量；最小化占用街道长度（两侧停车总长度的较大者，用辅助变量 z 表示）。",
    conf="MEDIUM", ptype="NL_LINEARIZABLE", tlin="MILP",
    trat="停车侧别为 0-1 变量，目标是两侧长度的最大值（min-max），用上境图辅助连续变量 z≥每侧长度 精确线性化，得到 MILP。", tconf="MEDIUM",
    notes="“占用街道总长度”理解为两侧中较长一侧的长度。题面第二问（某一侧不超过 30 米）只需加一条约束，见 models/industryor-0081__q2.py，其最优值与第一问相同。题面要求用 AMPL，这里用 PuLP/CBC。"))
R.append(row("industryor-0087", "min",
    "A、B 两型卡车租用数量为整数；最小化租金 30A+40B；冷藏容量 20A+30B≥3000，非冷藏容量 40A+30B≥4000。",
    ptype="IP", trat="两个变量都是卡车辆数（整数），目标和约束线性。", tconf="HIGH",
    notes="B 型总容量与 A 型相同（60），冷藏与非冷藏各 30。连续松弛值见输出（约 4166.67），车辆数按整数处理。"))
R.append(row("industryor-0097", "max",
    "原料 A、B、D 进入混合池的量、混合液及原料 C 分别进入两种产品的量为连续变量；最大化销售收入减原料采购成本；混合池物料与含硫平衡、产品含硫上限、原料 D 至多 50 吨、产品销量不超过市场需求。",
    solver="scipy", issue="AMBIGUOUS",
    issue_note="“their selling prices are 9.15 (thousand yuan per ton)”一句：可读作两种产品售价分别为 9 和 15，也可读作两种产品售价都是 9.15，两种读法最优值不同。另外市场需求 100/200 吨是销量上限还是必须恰好满足也未明说。",
    readings=[("售价分别为 9 和 15，需求为销量上限", "industryor-0097"),
              ("两种产品售价均为 9.15，需求为销量上限", "industryor-0097__r2"),
              ("售价分别为 9 和 15，需求必须恰好满足", "industryor-0097__r3"),
              ("两种产品售价均为 9.15，需求必须恰好满足", "industryor-0097__r4")],
    conf="LOW", ptype="NL_NOT_LINEARIZABLE",
    trat="混合池问题：混合池含硫浓度（连续）与池到各产品的流量（连续）相乘出现在含硫约束中，是两个连续变量的双线性项，不能精确线性化。", tconf="HIGH",
    notes="求解方法：固定混合池含硫浓度 p 后模型为 LP（scipy linprog/HiGHS），对 p 在 [1,3] 上以 0.0005 步长扫描并在最优点附近做一维精修；最优点落在区间端点，据此按全局最优报告 status=Optimal。"))
for cid, summ in [("mamo_complex_lp-0012", "五种食物的份数为整数变量；最小化总花费；蛋白质、碳水、热量三项营养下限。"),
                  ("mamo_complex_lp-0019", "五种食物的份数为整数变量；最小化总花费；蛋白质、碳水、热量三项营养下限。")]:
    R.append(row(cid, "min", summ, amb_int=True, conf="MEDIUM",
                 notes="食物份数是否可取小数题面未说明，主模型按整数份，并报告连续松弛值。"))
R.append(row("mamo_complex_lp-0063", "min",
    "4 城市 TSP：弧 0-1 变量，每城进出各一次，MTZ 约束消除子回路；最小化总旅行费用。"))
R.append(row("mamo_complex_lp-0138", "max",
    "各有向渠道上的流量为连续变量，受容量上限约束，中间节点流量守恒；最大化从节点 0 到节点 8 的净流量。",
    notes="中心 1 一行只给了 8 个数（题面注明不含自身），按去往 0,2,...,8 读取；源点一行 8 个数按去往 1..8 读取。"))
with open(os.path.join(grp, "results.jsonl"), "w", encoding="utf-8") as f:
    for r in R:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")

# ---- verification ----
rows = [json.loads(l) for l in open(os.path.join(grp, "results.jsonl"), encoding="utf-8")]
ids = sorted(fn[:-4] for fn in os.listdir(grp) if fn.endswith(".txt") and fn != "MANIFEST.sha256")
assert sorted(r["case_id"] for r in rows) == ids and len(rows) == len(set(r["case_id"] for r in rows)) == 16
for r in rows:
    assert os.path.exists(os.path.join(grp, r["model_file"])) and os.path.exists(os.path.join(grp, r["output_file"]))
    _, o, _ = out(r["case_id"])
    assert r["objective"] == o, r["case_id"]
    if r["case_id"].startswith("industryor-"):
        assert r["problem_type"] and r["type_rationale"] and r["type_confidence"]
    if r["integrality_ambiguous"]:
        assert r["integer_relaxed_objective"] is not None
    for rd in r["readings"]:
        assert os.path.exists(os.path.join(grp, rd["model_file"]))
print("CHECK_OK rows:", len(rows))
