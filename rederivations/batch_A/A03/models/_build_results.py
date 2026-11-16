#!/usr/bin/env python3
# Builds results.jsonl from the .out.txt files and checks consistency (run from the group directory).
import json, os, re
def out(name):
    txt = open(f"models/{name}.out.txt").read()
    st = re.search(r"^STATUS: (.*)$", txt, re.M).group(1)
    fo = re.search(r"^FINAL_OBJECTIVE: (.*)$", txt, re.M).group(1)
    rl = re.search(r"^INTEGERS_RELAXED: \S+ (\S+)", txt, re.M)
    return st, (None if fo == "None" else float(fo)), (float(rl.group(1)) if rl else None)
def rd(text, name):
    st, fo, _ = out(name)
    return {"reading": text, "objective": fo, "status": st, "model_file": f"models/{name}.py"}
def row(cid, sense, summary, solver="PULP_CBC_CMD", amb_int=False, asked=None, issue="NONE", issue_note="", readings=(),
        conf="HIGH", ptype=None, after=None, rat="", tconf=None, notes="", rnd=None):
    st, fo, rl = out(cid)
    if rnd is not None and fo is not None: fo = round(fo, rnd)
    if rl is not None and rnd is not None: rl = round(rl, rnd)
    return {"case_id": cid, "status": st, "objective": fo, "sense": sense, "model_file": f"models/{cid}.py",
            "output_file": f"models/{cid}.out.txt", "solver": solver, "model_summary": summary,
            "integrality_ambiguous": amb_int, "integer_relaxed_objective": rl if amb_int else None, "asked_value": asked,
            "issue": issue, "issue_note": issue_note, "readings": [rd(t, n) for t, n in readings], "confidence": conf,
            "problem_type": ptype, "type_after_linearization": after, "type_rationale": rat, "type_confidence": tconf, "notes": notes}
R = []
c = "industryor-0001"
R.append(row(c, "min", "每周整数人数：熟练工正常/加班生产两种食品、开始担任培训的熟练工、开始受训的新工人、已结训新工人生产两种食品；连续的缺货量与库存量。最小化 8 周工资（熟练工 360、加班 540、受训 120、结训后 240）加逐周延期赔偿；约束为熟练工人数平衡、1 名熟练工两周至多带 3 人、第 8 周末前恰好培训 50 人、逐周供需平衡。",
    amb_int=True, issue="AMBIGUOUS",
    issue_note="题面未说明 (a) 第 8 周末是否必须交清全部订货，(b) 是否允许提前生产存放后交货；另外加班者是否仅限原熟练工、结训新工人能否带培训、工人能否在一周内分摊两种食品（整数性）也未明说。各读法最优值不同。",
    readings=[("主读法：不要求第 8 周末交清（未交部分按周计赔），允许提前生产存放", c),
              ("要求第 8 周末缺货为零，允许提前生产存放", c + "__r2"),
              ("不要求第 8 周末交清，不允许提前生产（库存恒为 0）", c + "__r3"),
              ("要求第 8 周末缺货为零，不允许提前生产", c + "__r4")],
    conf="LOW", ptype="MILP", rat="人数为整数变量，缺货量/库存量为连续变量，目标与约束均为线性。", tconf="MEDIUM",
    notes="目标含 50 名熟练工 8 周的固定工资。假设：只有原熟练工可加班和带培训；培训须在第 7 周或之前开始；结训新工人不论是否生产均付 240。integer_relaxed_objective 为人数取连续时主读法的值。", rnd=4))
c = "industryor-0002"
R.append(row(c, "max", "整数变量为各年产出的战斗机中用于培训的架数；最大化第 2 年末累计培训出的飞行员数；约束为各年培训机不超过当年产量。",
    issue="AMBIGUOUS", issue_note="题面没有给出目标函数与完整约束（未说明培训机是否在次年继续培训、是否需要保留作战飞机、飞行员数与作战飞机数的匹配关系），只问第 2 年末飞行员总数；不同读法结果不同。",
    readings=[("主读法：全部飞机均可用于培训，第 1 年的培训机第 2 年继续培训", c), ("各年产出的飞机只在当年培训一次", c + "__r2")],
    conf="LOW", ptype="IP", rat="决策变量为培训用飞机架数（整数），目标和约束均线性。", tconf="MEDIUM", notes="题面缺少明确的优化目标，结果依赖补设。"))
c = "industryor-0007"
R.append(row(c, "min", "整数变量：各仓库到各港口的集装箱数和卡车数；最小化按卡车行驶里程计的运费（每车每公里 30 欧元）；约束为仓库库存上限、港口需求、每车至多 2 箱。",
    issue="AMBIGUOUS", issue_note="“每个集装箱的运输成本与卡车行驶距离成正比，费率 30 欧元/公里”与“每车至多装 2 箱”并存：费用可按卡车计，也可按集装箱计，两者最优值不同。",
    readings=[("主读法：按卡车计费，车数 >= 箱数/2 且为整数", c), ("按集装箱计费，卡车容量不影响费用", c + "__r2")],
    conf="MEDIUM", ptype="IP", rat="集装箱数与卡车数均为整数变量，目标和约束线性；车数=⌈箱数/2⌉ 用整数变量加线性约束表示。", tconf="MEDIUM",
    notes="总库存大于总需求，供给约束取 <=。按集装箱计费的读法下是纯运输问题（LP 即得整数解）。"))
c = "industryor-0016"
R.append(row(c, "max", "连续变量：各月进货量、销售量、月末库存；最大化三个月销售收入减进货成本；约束为月初进货后库存不超过 500、库存平衡且非负，期初库存 200。",
    conf="HIGH", ptype="LP", rat="进货量、销售量按连续变量处理（题面要求写成线性规划），目标和约束线性；最优解本身为整数。", tconf="MEDIUM",
    notes="期末库存不计价值；期初 200 件库存的成本不计入。"))
c = "industryor-0018"
R.append(row(c, "min", "连续变量：两种布的生产小时数及各目标的正负偏差；按 p1>p2>p3>p4 的优先级逐级最小化偏差（未用足 110 小时、加班超过 10 小时、两种布未达销量、加班量）。",
    issue="AMBIGUOUS", issue_note="题面只要求“建立模型”，没有指明单一的数值目标：按目标规划逐级求解时最后一级的值是加班小时数；若把各目标当硬约束并最大化利润则得到利润值。",
    readings=[("主读法：优先级目标规划，逐级最小化偏差，报告最后一级（加班小时）的值", c), ("把 p1–p3 当硬约束，最大化周利润", c + "__r2")],
    conf="LOW", ptype="LP", rat="产量（小时/米）和偏差变量均连续，各级目标与约束线性（优先级目标规划）。", tconf="MEDIUM",
    notes="前三级偏差均为 0；objective 为第四级的最优偏差。主读法解处的利润见 .out.txt 的 PROFIT_AT_SOLUTION。"))
c = "industryor-0021"
R.append(row(c, "min", "整数变量：向三家供应商的订货次数，另有两个 0-1 变量表示是否向 A、B 订货；最小化按每张桌子单价计的总成本；约束为桌子总数在 150 到 600 之间、订 A 则 B 至少 30 张、订 B 则须订 C。",
    conf="HIGH", ptype="IP", rat="订货次数为整数，逻辑条件用 0-1 变量加线性约束，目标和约束线性。", tconf="HIGH"))
c = "industryor-0030"
R.append(row(c, "min", "连续变量：5 种饲料的用量；最小化饲料费用；约束为蛋白质、矿物质、维生素三项最低需求。",
    issue="AMBIGUOUS", issue_note="正文说表中是“每克饲料”的营养含量和价格，表头价格单位却是 元/kg（且表号 1-5/1-6 不一致）：含量按每 kg 计还是每 g 计，使费用相差 1000 倍。",
    readings=[("主读法：营养含量按每 kg 饲料计，用量单位 kg", c), ("营养含量按每 g 饲料计，价格按 元/kg 折算", c + "__r2")],
    conf="MEDIUM", ptype="LP", rat="饲料用量为连续变量，目标和约束线性。", tconf="HIGH"))
c = "industryor-0037"
R.append(row(c, "max", "整数变量：A、B 两种微机的周产量；最大化利润；约束为利润不低于 10000、A 至少 10 台、B 至少 15 台、工序 I 恰好 150 小时、工序 II 至少用满 70 小时（可加班）。",
    amb_int=True, issue="AMBIGUOUS", issue_note="题面列出带优先级的目标（目标规划形式），又说“为使总利润最大”建模：可以理解为在满足各目标下最大化利润，也可以理解为逐级最小化目标偏差，两者报告的数值不同。",
    readings=[("主读法：各目标作为约束，最大化利润", c), ("优先级目标规划，逐级最小化偏差，报告最后一级偏差", c + "__r2")],
    conf="MEDIUM", ptype="IP", rat="产量为整台数，目标和约束线性；若按目标规划写则另有连续偏差变量（MILP）。", tconf="MEDIUM",
    notes="工序 I 恰好 150 小时时利润被唯一确定，整数与连续结果相同。"))
c = "industryor-0038"
R.append(row(c, "min", "连续变量：各产品在各机床上的开工时间与总完工时间；0-1 变量：产品两两之间的先后顺序（各机床顺序相同）；最小化最大完工时间。",
    conf="HIGH", ptype="MILP", rat="排序用 0-1 变量加大 M 析取约束，开工时间连续，目标和约束线性。", tconf="MEDIUM",
    notes="“总加工周期”理解为全部产品完工的时间（makespan）。"))
c = "industryor-0047"
R.append(row(c, "max", "连续变量：三种作物面积；整数变量：奶牛头数、鸡只数、两季外出务工人日；最大化年净收入（含外出务工收入）；约束为土地、资金、两季劳动力、牛舍与鸡舍容量。",
    amb_int=True, conf="MEDIUM", ptype="MILP", rat="作物面积连续，牲畜数量和外出务工人日为整数，目标和约束线性。", tconf="MEDIUM",
    notes="“劳动日按整日计”理解为外出务工人日取整数；牲畜头数取整数。integer_relaxed_objective 为全部取连续时的值。", rnd=4))
c = "industryor-0093"
R.append(row(c, "max", "连续变量：分别用于加工两种产品的牛奶桶数；最大化日利润；约束为牛奶供应、劳动时间、甲类设备加工能力。",
    conf="HIGH", ptype="LP", rat="牛奶桶数按连续变量处理，目标和约束线性。", tconf="HIGH"))
c = "industryor-0099"
R.append(row(c, "max", "整数变量：三种部件各装的备件数（0–5）；最大化三部件可靠度的乘积；约束为备件总价和总重量上限。", solver="enumeration",
    conf="HIGH", ptype="NL_LINEARIZABLE", after="IP", rat="目标是备件数的表格函数之积（非线性）；备件数为有界整数，可逐值枚举成 0-1 选择变量，取对数后目标为线性和（或对 0-1 乘积作 McCormick），精确等价。", tconf="MEDIUM",
    notes="对 6^3 种组合完全穷举，结果为全局最优。"))
c = "industryor-0100"
R.append(row(c, "max", "0-1 变量：有向边是否在链路上；连续变量：链路带宽和结点次序；最大化链路上最小带宽；约束为 A 到 E 的简单路径、必须经过 C、无回路。",
    issue="AMBIGUOUS", issue_note="带宽表不对称，题面未说明行、列哪个是起点：按“行为起点、列为终点”与按转置读，最优值不同。",
    readings=[("主读法：行结点为起点、列结点为终点", c), ("转置：列结点为起点、行结点为终点", c + "__r2")],
    conf="MEDIUM", ptype="NL_LINEARIZABLE", after="MILP", rat="目标为所选边带宽的最小值（max-min，非线性）；用上境图辅助变量加大 M（取表中最大带宽）精确线性化，选边为 0-1 变量。", tconf="MEDIUM"))
c = "mamo_complex_lp-0039"
R.append(row(c, "min", "整数变量：6 种食物的份数；最小化费用；约束为蛋白质、碳水、热量三项最低需求。",
    amb_int=True, conf="MEDIUM", rat="", notes="题面未说明份数能否取小数；主模型取整数，连续松弛值另报。", rnd=6))
c = "mamo_complex_lp-0083"
R.append(row(c, "min", "0-1 变量：城市间的行驶弧；最小化回路总成本；约束为每城进出各一次、MTZ 消除子回路。", conf="HIGH"))
c = "mamo_complex_lp-0153"
R.append(row(c, "min", "0-1 变量：各配送中心是否开设；连续变量：各中心到各门店的运量；最小化开设费加运输费；约束为门店需求、中心容量。", conf="HIGH"))
with open("results.jsonl", "w", encoding="utf-8") as f:
    for r in R: f.write(json.dumps(r, ensure_ascii=False) + "\n")
# ---- checks
ids = sorted(fn[:-4] for fn in os.listdir(".") if fn.endswith(".txt"))
rows = [json.loads(l) for l in open("results.jsonl", encoding="utf-8")]
assert sorted(r["case_id"] for r in rows) == ids and len(rows) == len(set(r["case_id"] for r in rows)) == 16
for r in rows:
    assert os.path.exists(r["model_file"]) and os.path.exists(r["output_file"])
    for q in r["readings"]: assert os.path.exists(q["model_file"]) and os.path.exists(q["model_file"][:-3] + ".out.txt")
    fo = out(r["case_id"])[1]
    assert abs(fo - r["objective"]) <= 1e-3 * max(1, abs(fo)), r["case_id"]
    if r["case_id"].startswith("industryor-"): assert r["problem_type"] and r["type_rationale"] and r["type_confidence"]
    if r["issue"] == "AMBIGUOUS": assert len(r["readings"]) >= 2 and r["issue_note"]
    if r["integrality_ambiguous"]: assert r["integer_relaxed_objective"] is not None
from collections import Counter
print("rows", len(rows), Counter(r["status"] for r in rows))
print("AMB", [r["case_id"] for r in rows if r["issue"] != "NONE"])
print("LOW", [r["case_id"] for r in rows if r["confidence"] == "LOW"])
