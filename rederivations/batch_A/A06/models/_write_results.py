#!/usr/bin/env python3
# Builds results.jsonl from the .out.txt files and checks consistency. Run from the group directory.
import json, os, re, glob
def out(path):
    t = open(path).read()
    st = re.search(r"^STATUS: (.*)$", t, re.M).group(1)
    ob = re.search(r"^FINAL_OBJECTIVE: (.*)$", t, re.M).group(1)
    rel = re.search(r"^INTEGERS_RELAXED: \w+ ([-\d.e+]+)", t, re.M)
    return st, (None if ob == "None" else round(float(ob), 6)), (round(float(rel.group(1)), 6) if rel else None)
def rd(cid, suffix, text):
    f = f"models/{cid}{suffix}.py"; st, ob, _ = out(f[:-3] + ".out.txt")
    return {"reading": text, "objective": ob, "status": st, "model_file": f}
def row(cid, sense, summary, conf, ptype=None, lin=None, rat="", tconf=None, int_amb=False, relaxed=None,
        asked=None, issue="NONE", issue_note="", readings=None, notes=""):
    st, ob, rel = out(f"models/{cid}.out.txt")
    return {"case_id": cid, "status": st, "objective": ob, "sense": sense, "model_file": f"models/{cid}.py",
            "output_file": f"models/{cid}.out.txt", "solver": "PULP_CBC_CMD", "model_summary": summary,
            "integrality_ambiguous": int_amb, "integer_relaxed_objective": (relaxed if relaxed is not None else rel) if int_amb else None,
            "asked_value": asked, "issue": issue, "issue_note": issue_note, "readings": readings or [],
            "confidence": conf, "problem_type": ptype, "type_after_linearization": lin, "type_rationale": rat,
            "type_confidence": tconf, "notes": notes}
R = []
c = "industryor-0005"
R.append(row(c, "max", "各食物用量（连续，百克）加 0-1 选择变量；最大化纤维；恰选一种蛋白、至少两种蔬菜、预算 15、总量 600 克。", "MEDIUM",
    "MILP", None, "用量为连续的克数，选择用 0-1 变量和线性联动约束表达，目标与约束均线性。", "HIGH",
    notes="题面没有给被选食物的最小用量，模型允许被选的蛋白质/蔬菜用量为 0；若要求严格为正则最优值只能逼近不能取到。克数按连续处理。"))
c = "industryor-0025"
R.append(row(c, "max", "各年初投入一年期、两年期项目的金额及闲置现金（连续）；逐年资金平衡；最大化第三年末持有资金。", "MEDIUM",
    "LP", None, "投资金额为连续变量，资金平衡约束与目标都是线性的。", "HIGH",
    issue="AMBIGUOUS", issue_note="“maximize the investor's earnings by the end of the third year”：目标可理解为第三年末的资金总额（含本金），也可理解为净收益（扣除本金），两者相差本金。另把 return 理解为净回报（1 元变 1.7 元 / 3 元）。",
    readings=[rd(c, "", "目标为第三年末资金总额（含本金）"), rd(c, "__r2", "目标为净收益（总额减本金）")]))
c = "industryor-0046"
R.append(row(c, "min", "每人每天值班小时数（连续）与是否排班的 0-1 变量；最小化工资；每天恰 14 小时、可用时间上限、每周最少工时、每人每周至多 2 班、每天至多 3 人。", "HIGH",
    "MILP", None, "工时为连续变量，班次用 0-1 变量计数，约束和目标线性。", "HIGH"))
c = "industryor-0048"
R.append(row(c, "min", "A、B 在正常工时与工序 II 加班工时内的产量（整数）及偏差变量；按 p1–p4 优先级逐级最小化偏差（字典序目标规划），报告值为各级最优偏差之和。", "LOW",
    "MILP", None, "产量为整台数，偏差变量连续，各目标约束与各级目标均线性。", "MEDIUM",
    int_amb=True, relaxed=0.0, asked=None, issue="AMBIGUOUS",
    issue_note="题面只要求建立目标规划模型，没有定义唯一的数值目标：可报告各优先级偏差（全部可同时达到 0），也可报告满足全部目标时的利润。另外工序 I 的 150 小时是硬约束还是目标、p4 的加班如何计入也有多种写法。",
    readings=[rd(c, "", "字典序目标规划，报告各级偏差之和"), rd(c, "__r2", "把 p1–p3 当硬约束，最大化利润")],
    notes="所有优先级偏差可同时为 0；该解下的利润见 r2。整数改连续后偏差仍为 0（脚本中各级 LP 松弛未单独输出，由整数解可行且偏差下界为 0 得出）。"))
c = "industryor-0050"
R.append(row(c, "max", "各月购入量与售出量（连续）；最大化销售收入减进货支出；月初购入后库存不超过 500，售出量不超过当月可用库存，期初库存 200。", "MEDIUM",
    "LP", None, "购销数量按连续量处理，库存平衡、容量约束和目标都是线性的；数据为整数时顶点解为整数。", "MEDIUM",
    int_amb=True, issue="AMBIGUOUS",
    issue_note="“purchases are made at the beginning of each month”与销售的先后：当月购入的货能否当月售出、容量在购入后还是售出后检查，两种读法最优值不同。期初 200 件库存不计成本、期末库存不计价值。",
    readings=[rd(c, "", "月初先购入，当月可售出刚购入的货，购入后库存 ≤500"), rd(c, "__r2", "当月只能售出月初已有库存，先售后购，购入后库存 ≤500")],
    notes="数量取整数时最优值与连续相同（解本身为整数）。"))
R[-1]["integer_relaxed_objective"] = R[-1]["objective"]
c = "industryor-0071"
R.append(row(c, "min", "工厂到地点的 0-1 指派变量；最小化 Σ d_ij·c_pq·x_ip·x_jq（二次指派），乘积用 0-1 辅助变量线性化。", "LOW",
    "NL_LINEARIZABLE", "IP", "目标含两个 0-1 指派变量的乘积，用 0-1 辅助变量加三条线性约束精确线性化，线性化后全部为 0-1 变量。", "MEDIUM",
    issue="AMBIGUOUS",
    issue_note="正文定义的是工厂间运量 d_ij 与地点间单位运费 c_pq（二次指派），但表头写成“工厂到地点的运量/运费”，且没有说明 i=j、p=q 的对角项是否计入。",
    readings=[rd(c, "", "二次指派，四个下标全部求和（含对角项）"), rd(c, "__r2", "按表头字面：工厂到地点的线性指派，费用=运量×单位运费"), rd(c, "__r3", "二次指派，只计 i≠j 的项")]))
c = "industryor-0074"
R.append(row(c, "min", "各工序开始时间和总工期（连续）；紧前关系约束；最小化 1000×总工期 + 5000×(B 结束 − A 开始)。", "MEDIUM",
    "LP", None, "开始时间为连续变量，紧前约束与费用目标均线性。", "HIGH",
    issue="AMBIGUOUS",
    issue_note="“The cost of work per day is 1000 Euros”：可理解为按项目总工期每天 1000，也可理解为按各工序作业天数之和计费（常数）。",
    readings=[rd(c, "", "每日费用按项目总工期计"), rd(c, "__r2", "每日费用按各工序工期之和计（常数项）")]))
c = "industryor-0078"
R.append(row(c, "min", "全职、兼职总工时（连续）及偏差变量；按 p1 销量、p2 充分就业、p3 加班最少的优先级逐级最小化偏差，报告值为各级最优偏差之和（即最少加班小时数）。", "LOW",
    "LP", None, "工时与偏差变量均连续，目标约束和各级目标线性。", "MEDIUM",
    issue="AMBIGUOUS",
    issue_note="题面只要求建立目标规划模型，没有定义唯一的数值目标；可报告字典序下的加班偏差，也可报告对应的利润。p3 中全职与兼职加班是否加权也未说明。",
    readings=[rd(c, "", "字典序目标规划，报告各级偏差之和（加班小时数，不加权）"), rd(c, "__r2", "p1、p2 作硬约束，最大化利润（销售利润减工资）")]))
c = "industryor-0086"
R.append(row(c, "max", "两种狗粮月产量（连续）；最大化售价减原料与加工成本的利润；谷物、肉类采购上限与 Meaties 机器产能约束。", "HIGH",
    "LP", None, "产量按连续量处理（数量级为十万包），目标与三条资源约束均线性。", "MEDIUM",
    int_amb=True, notes="包数取整数时最优值相同（最优解本身为整数）。"))
R[-1]["integer_relaxed_objective"] = R[-1]["objective"]
for c in ["mamo_complex_lp-0003", "mamo_complex_lp-0006", "mamo_complex_lp-0014", "mamo_complex_lp-0021", "mamo_complex_lp-0024", "mamo_complex_lp-0033"]:
    R.append(row(c, "min", "每种食物的份数（主模型取整数）；最小化总花费；蛋白质、碳水、热量三条下限约束。", "MEDIUM",
        int_amb=True, notes="题面未说明份数能否取小数；主模型按整份，连续松弛值见 integer_relaxed_objective。"))
with open("results.jsonl", "w", encoding="utf-8") as f:
    for r in R: f.write(json.dumps(r, ensure_ascii=False) + "\n")
# checks
ids = sorted(os.path.basename(p)[:-4] for p in glob.glob("*.txt"))
rows = [json.loads(l) for l in open("results.jsonl", encoding="utf-8")]
assert sorted(r["case_id"] for r in rows) == ids and len(rows) == len(set(ids)) == 15
for r in rows:
    assert os.path.exists(r["model_file"]) and os.path.exists(r["output_file"])
    assert out(r["output_file"])[1] == r["objective"]
    for x in r["readings"]: assert os.path.exists(x["model_file"])
    if r["case_id"].startswith("industryor"): assert r["problem_type"] and r["type_rationale"] and r["type_confidence"]
    if r["integrality_ambiguous"]: assert r["integer_relaxed_objective"] is not None
print("CHECK OK", len(rows))
from collections import Counter
print(Counter(r["status"] for r in rows)); print([(r["case_id"], r["issue"], r["confidence"]) for r in rows])
