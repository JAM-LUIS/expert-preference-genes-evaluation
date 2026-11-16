#!/usr/bin/env python3
# builds results.jsonl from the .out.txt files (run from the group directory) and checks consistency
import json, os, re, glob

def out(case):
    t = open(f"models/{case}.out.txt").read()
    st = re.search(r"^STATUS: (.*)$", t, re.M).group(1)
    ob = re.search(r"^FINAL_OBJECTIVE: (.*)$", t, re.M).group(1)
    rl = re.search(r"^INTEGERS_RELAXED: \S+ (\S+)", t, re.M)
    return st, (None if ob == "None" else float(ob)), (float(rl.group(1)) if rl else None)

def rd(case, text):
    st, ob, _ = out(case)
    return {"reading": text, "objective": ob, "status": st, "model_file": f"models/{case}.py"}

R = []
def add(case, sense, summary, ia, conf, ptype=None, rationale="", tconf=None, issue="NONE", issue_note="",
        readings=None, notes="", relaxed="auto", tal=None, asked=None):
    st, ob, rl = out(case)
    if relaxed == "auto":
        relaxed = rl if ia else None
    R.append({"case_id": case, "status": st, "objective": ob, "sense": sense,
              "model_file": f"models/{case}.py", "output_file": f"models/{case}.out.txt",
              "solver": "PULP_CBC_CMD", "model_summary": summary, "integrality_ambiguous": ia,
              "integer_relaxed_objective": relaxed, "asked_value": asked, "issue": issue,
              "issue_note": issue_note, "readings": readings or [], "confidence": conf,
              "problem_type": ptype, "type_after_linearization": tal, "type_rationale": rationale,
              "type_confidence": tconf, "notes": notes})

add("industryor-0014", "max",
    "三种蛋白食材用量连续（100g 为单位），五种蔬菜按 100g 包取整数包数并用 0-1 变量表示是否选用；最大化蛋白质总量；预算、总重量约束，至少选三种蔬菜。",
    False, "HIGH", "MILP", "蛋白食材用量连续，蔬菜包数为整数并配 0-1 选用变量，目标与约束均线性；“至少三种”是标准逻辑条件。", "HIGH",
    notes="每种蔬菜至多一包（纯 0-1）的读法得到相同最优值；包数放松为连续后最优值也相同。")
add("industryor-0023", "max",
    "三种服装周产量为整数，各配一个 0-1 变量表示是否启用对应专用设备；最大化（售价-可变成本）×产量减去固定费用；劳动力和材料两条资源约束，产量受开关变量约束（大 M 取资源推出的上界）。",
    False, "HIGH", "IP", "产量按件取整数、设备启用为 0-1，固定费用用 0-1 加线性约束表达，目标和约束线性；若把产量视为连续则为 MILP。", "MEDIUM",
    notes="产量改为连续后最优值不变。")
add("industryor-0027", "max",
    "变量为各产品在各台 A、B 设备上加工的件数（整数）；最大化（售价-原料费）×产量减去设备费用，设备费用按“满负荷费用/有效台时”折算成每台时费率乘以实际占用台时；每种产品 A 工序总量等于 B 工序总量，各设备台时不超过有效台时。",
    True, "MEDIUM", "IP", "决策变量是各设备上加工的产品件数，按不可分件数取整数；目标和约束都是线性的；若件数视为连续则为 LP。", "MEDIUM",
    notes="拿不准两处：(1) 件数是否取整（放松后的值见 integer_relaxed_objective）；(2) 设备费用的处理：主模型按台时比例计费；若把满负荷费用视为与产量无关的固定支出（全部扣除），见 models/industryor-0027__r2.py，其最优值与主模型略有差别。")
add("industryor-0032", "max",
    "变量为各车间分配给各部件的小时数（连续）和成品套数 z；最大化 z；各车间工时上限，z 不超过每种部件的总产量。",
    True, "MEDIUM", "LP", "工时分配为连续变量，max-min 目标用辅助变量 z 的上境图写成线性约束（凸方向），题面也要求写成线性规划；按第 3.6 节可视为 max-min 的标准 LP 写法。", "MEDIUM",
    relaxed=out("industryor-0032")[1],
    notes="主模型按题面“线性规划”把成品数当连续量；若要求成品数为整数（工时仍连续），见 models/industryor-0032__int.py，结果为主值向下取整。题面未说明每件成品各需几个部件，按各 1 个处理。主值的精确值为 84800/29。若严格按“最直接模型含 min()”判型，也可标 NL_LINEARIZABLE（线性化后 LP）。")
add("industryor-0042", "min",
    "变量为每座炉子用两种方法各炼的炉次数（整数）；最小化燃料费；每座炉子 12 小时内的时间约束，总产钢量不少于 30 吨。",
    True, "MEDIUM", "IP", "炉次数是不可分的次数，取整数，目标和约束线性；题面称线性规划，若炉次视为连续则为 LP。", "MEDIUM",
    notes="题面表述较含糊（“两座炉子同时使用两种方法”）。按每座炉子各有 12 小时、或两座炉子合计 12 小时、整数或连续，几种读法的最优值相同，故不记为歧义。")
add("industryor-0054", "max",
    "三种产品的月产量（整数）；最大化利润；A、B、C 三种设备的月有效台时约束。",
    True, "MEDIUM", "IP", "产量按件取整数，目标与三条设备台时约束均线性；若产量可取小数则为 LP。", "MEDIUM",
    notes="题面未说明产量是否必须为整数，整数与连续两种处理的最优值不同（连续值见 integer_relaxed_objective）。“充分利用设备能力”按台时不超过上限处理，没有强制取等号。利润单位为千元。")
add("industryor-0059", "max",
    "变量为每种原料投入每种牌号糖果的公斤数（连续）；最大化 (售价-加工费)×糖果产量 减 原料成本；原料月限量，以及各牌号中原料 A 的最低含量、原料 C 的最高含量比例约束。",
    False, "HIGH", "LP", "原料用量为连续的公斤数；含量比例约束两边乘以总量后是线性的；目标线性。", "HIGH",
    notes="求解器输出有 1e-5 量级的数值尾差，精确最优值为 6160。题目问各牌号产量，见输出文件末尾三行。")
add("industryor-0066", "max",
    "三种玩具的产量（整数，各有需求上限）；最大化利润；制造工时和检验工时约束。",
    False, "HIGH", "IP", "产量是整件数，目标和两条工时约束及上界都是线性的。", "HIGH",
    notes="产量放松为连续后最优值不变。")
add("industryor-0069", "min",
    "变量为每种下料方式（一根 10 米原料切出 i 根 3 米、j 根 4 米）使用的原料根数（整数）；恰好得到 90 根 3 米和 60 根 4 米；最小化余料总长（即所用原料总长减去所需成品总长）。",
    True, "LOW", "IP", "各下料方式的使用根数为整数，目标和需求约束线性；题面称线性规划，若根数视为连续则为 LP。", "MEDIUM",
    issue="AMBIGUOUS",
    issue_note="“minimize the total waste”没有说明多切出来的成品是否算废料、产量是恰好还是至少满足需求；另外题面称线性规划，根数是否取整也影响结果。",
    readings=[rd("industryor-0069", "根数为整数，需求恰好满足（等价于允许超产但超产部分计入废料），废料=原料总长-所需成品总长"),
              rd("industryor-0069__r2", "允许超产，只计切割余料、多余成品不算废料"),
              {"reading": "主读法但根数放松为连续（题面称线性规划）", "objective": out("industryor-0069")[2], "status": "Optimal", "model_file": "models/industryor-0069.py"}],
    notes="第三种读法的值取自主脚本输出的 INTEGERS_RELAXED 行。")
add("industryor-0075", "max",
    "变量为 A、B 产量（连续）、副产品 C 的销售量（至多 5）和销毁量；C 的销售量加销毁量等于 2 倍 B 产量；最大化 A、B、C 销售利润减 C 的销毁费；两道工序工时约束。",
    True, "MEDIUM", "LP", "A、B 产量及 C 的销售/销毁量按连续量处理，引入销售量和销毁量两个变量后目标和约束都是线性的；若产量取整则为 MILP/IP。", "MEDIUM",
    relaxed=out("industryor-0075")[1],
    notes="求解器输出有数值尾差，精确最优值为 57。把 A、B 产量改为整数（models/industryor-0075__int.py）得到的最优值相同。")
add("industryor-0076", "max",
    "变量 x[i,j] 为第 i 季度初购入、第 j 季度售出的木材量（万 m³，连续，j≥i）；最大化售价减进价减储存费；各季度销量不超过预计最大销量，跨季度库存不超过库容 20 万 m³。",
    False, "LOW", "LP", "购入并在各季度售出的木材量为连续变量，储存时间由下标决定是常数，目标和约束都是线性的。", "HIGH",
    issue="AMBIGUOUS",
    issue_note="两处拿不准：(1) 储存费 (a+bu) 的单位，题面写“元/m³”，而价格表单位是“万元/万 m²”（应为 m³），按字面储存费远高于价差，若实为“元/万 m³”则储存有利可图；(2) 库容 20 万 m³ 是只限制跨季度结转的库存，还是也限制季度初购入后的全部在库量（当季销售的也算）。另外当季购入当季售出是否收储存费题面未说明（主读法按不收）。",
    readings=[rd("industryor-0076", "储存费按字面为元/m³，仅对跨季度储存收取；库容只限制跨季度库存"),
              rd("industryor-0076__r2", "储存费为元/万 m³；库容只限制跨季度库存"),
              rd("industryor-0076__r3", "储存费按字面为元/m³；库容限制季度初购入后的全部在库量"),
              rd("industryor-0076__r4", "储存费为元/万 m³；库容限制季度初购入后的全部在库量")],
    notes="目标值单位为万元。")
add("industryor-0091", "max",
    "A、B 两种产品的周产量（整数）；最大化利润；机器装配时间不超过 30 小时（1800 分钟）；B 产量不少于 A 产量的 2/5。",
    True, "MEDIUM", "IP", "产量是整件数，目标、机时约束和比例约束（5B≥2A）都是线性的；若产量视为连续则为 LP。", "MEDIUM",
    issue="AMBIGUOUS",
    issue_note="“每生产五件 A 至少生产两件 B”可读作比例约束 B≥0.4A，也可读作按完整的五件一组计（B≥2×⌊A/5⌋）；在产量取整时两种读法最优值不同。另外产量是否取整也影响结果（连续值见 integer_relaxed_objective）。",
    readings=[rd("industryor-0091", "比例约束 5B≥2A，产量为整数"),
              rd("industryor-0091__r2", "按完整五件一组：B≥2×⌊A/5⌋，产量为整数")])
add("mamo_complex_lp-0017", "min",
    "四种食物的份数（整数）；最小化总花费；蛋白质、碳水、热量三条下限约束。",
    True, "MEDIUM",
    notes="题面没说份数能否取小数，主模型按整数份；连续值见 integer_relaxed_objective，两者不同。")
add("mamo_complex_lp-0036", "min",
    "七种食物的份数（整数）；最小化总花费；蛋白质、碳水、热量三条下限约束。",
    True, "MEDIUM",
    notes="题面没说份数能否取小数，主模型按整数份；连续值见 integer_relaxed_objective，两者不同。")
add("mamo_complex_lp-0064", "min",
    "五城市旅行商问题：0-1 弧变量，每个城市进出各一次，MTZ 约束消除子回路；最小化总旅行费用。",
    False, "HIGH", notes="费用矩阵对称。")

with open("results.jsonl", "w", encoding="utf-8") as f:
    for r in R:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")

# checks
cases = sorted(os.path.basename(p)[:-4] for p in glob.glob("*.txt"))
rows = [json.loads(l) for l in open("results.jsonl", encoding="utf-8")]
ids = [r["case_id"] for r in rows]
assert sorted(ids) == cases and len(set(ids)) == len(ids) == 15, (ids, cases)
for r in rows:
    assert os.path.exists(r["model_file"]) and os.path.exists(r["output_file"])
    assert r["objective"] == out(r["case_id"])[1]
    for x in r["readings"]:
        assert os.path.exists(x["model_file"])
    if r["integrality_ambiguous"]:
        assert r["integer_relaxed_objective"] is not None
    if r["case_id"].startswith("industryor-"):
        assert r["problem_type"] and r["type_rationale"] and r["type_confidence"]
    if r["issue"] != "NONE":
        assert r["issue_note"] and len(r["readings"]) >= 2
from collections import Counter
print("rows", len(rows), Counter(r["status"] for r in rows))
print("issues", [(r["case_id"], r["issue"]) for r in rows if r["issue"] != "NONE"])
print("LOW", [r["case_id"] for r in rows if r["confidence"] == "LOW"])
