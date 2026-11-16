import json, re, os
os.chdir(os.path.dirname(os.path.abspath(__file__)) + "/..")
def fo(cid):
    t = open(f"models/{cid}.out.txt").read()
    v = re.search(r"FINAL_OBJECTIVE: (\S+)", t).group(1)
    return None if v == "None" else float(v)
def rel(cid):
    t = open(f"models/{cid}.out.txt").read()
    return float(re.search(r"INTEGERS_RELAXED: \S+ (\S+)", t).group(1))
def R(cid, sense, summary, ptype=None, rationale="", tconf=None, conf="HIGH", ia=False, issue="NONE",
      issue_note="", readings=None, notes="", asked=None, tal=None, solver="PULP_CBC_CMD"):
    return dict(case_id=cid, status="Optimal", objective=fo(cid), sense=sense,
                model_file=f"models/{cid}.py", output_file=f"models/{cid}.out.txt", solver=solver,
                model_summary=summary, integrality_ambiguous=ia,
                integer_relaxed_objective=(rel(cid) if ia else None), asked_value=asked,
                issue=issue, issue_note=issue_note, readings=readings or [], confidence=conf,
                problem_type=ptype, type_after_linearization=tal, type_rationale=rationale,
                type_confidence=tconf, notes=notes)
def rd(text, f):
    return dict(reading=text, objective=fo(f), status="Optimal", model_file=f"models/{f}.py")
rows = [
 R("industryor-0010","min","每个小区是否建店为0-1变量；最小化建店数；每个小区的800m范围列表内至少有一家店（集合覆盖）。",
   "IP","决策变量是12个0-1建店变量，目标与覆盖约束都是线性的，纯0-1规划。","HIGH",
   notes="一个最优方案为在B、G、J建店；最优解可能不唯一。"),
 R("industryor-0014","max","三种蛋白按100g为单位连续取量，五种蔬菜按整包数取整数，配0-1选用变量；最大化蛋白质；预算20美元、总重≤800g、至少选三种蔬菜。",
   "MILP","蛋白质份量连续，蔬菜包数整数并配0-1选用指示变量，目标和约束线性，为混合整数线性规划。","HIGH",
   notes="另试每种蔬菜至多一包的读法（models/industryor-0014__r2.py），最优值相同，不算歧义。把包数改成连续（0-1保持）最优值也不变。"),
 R("industryor-0022","max","三种产品产量（百公斤，连续）与是否启动生产线的0-1变量；最大化(售价-生产成本)×产量-启动费用；需求上限、22天产能（各产品占用天数=产量/日定额）、启用后产量至少为最小批量。",
   "MILP","产量连续，启动决策为0-1，固定费用和最小批量用0-1加线性约束表示，目标和约束线性。","HIGH",conf="MEDIUM",
   notes="题面说maximize total revenue，但又要求计入启动费用和生产成本，按利润（售价减生产成本再减启动费）理解；最优解只生产A2、A3并满足其全部需求。"),
 R("industryor-0030","min","五种饲料用量（连续）；最小化饲料费用；蛋白质≥700g、矿物质≥30g、维生素≥100mg。",
   "LP","饲料用量为连续变量，营养约束与费用目标都是线性的。","HIGH",conf="MEDIUM",issue="AMBIGUOUS",
   issue_note="题面说表中是每克饲料的营养含量和价格，但价格列单位是元/kg。若营养含量与价格对应同一单位饲料（例如都按每kg），最优值为主读法；若营养按每克、价格按每kg，费用要除以1000。两者最优配方相同，目标值差1000倍。",
   readings=[rd("营养含量与价格按同一单位饲料计（价格数值直接用作每单位费用）","industryor-0030"),
             rd("营养含量按每克饲料、价格按元/kg，决策变量为克数，单价换算为价格/1000","industryor-0030__r2")]),
 R("industryor-0035","min","各批次在三个染缸的开工时间（连续）与同一染缸上任意两批先后顺序的0-1变量；最小化最后一批完工时间；每批按缸1→2→3顺序、同缸不重叠（大M析取）。",
   "MILP","开工时间和最大完工时间为连续变量，先后顺序为0-1变量，析取约束用大M线性化（教科书标准逻辑条件），目标线性。","HIGH",
   notes="另对全部120个排列（置换流水作业）枚举，最好值与MILP一致。"),
 R("industryor-0036","min","弧变量x_ij为0-1，客户开始服务时间与累计载重为连续变量；最小化总欧氏行驶距离；每客户恰被访问一次、至多5辆车、载重≤200、硬时间窗、服务90分钟、须在1236分钟前回仓库。",
   "MILP","路线选择为0-1弧变量，服务开始时间和载重为连续变量，时间窗/容量用大M线性约束（MTZ型），目标线性。","HIGH",conf="MEDIUM",
   notes="题面没有给出车速，按行驶时间(分钟)=欧氏距离处理；距离未取整。求解得3条路线。若采用其他车速或距离取整，结果可能不同。"),
 R("industryor-0055","min","七门课程是否选修为0-1变量；最小化所选课程数；数学、运筹、计算机三类各至少两门（跨类课程同时计入），以及先修关系。",
   "IP","全部决策变量为0-1选课变量，类别要求和先修关系都是线性约束，目标线性。","HIGH",
   notes="一个最优方案为运筹学、数据结构、计算机模拟、计算机编程；最优解可能不唯一。"),
 R("industryor-0057","min","枚举1m和2m原纸的全部可行切割方式，决策变量为每种切法使用的原纸长度（连续）；满足三种宽度的长度需求；主读法最小化（使用原纸面积-订单面积）。",
   "LP","决策变量为各切割方式的使用长度，长度可拼接故为连续量，约束和目标线性。","HIGH",conf="LOW",issue="AMBIGUOUS",
   issue_note="'minimize the area of waste'未说明多切出（超过订单长度）的纸是否算废料。主读法把超产部分也算作浪费（等价于最小化原纸总面积）；另一读法只计切割边角料、需求取≥，此时可以超产窄条而不计入浪费，最优值更小。",
   readings=[rd("浪费=使用原纸总面积-订单所需面积（超产计入浪费）","industryor-0057"),
             rd("浪费只计各切法的边角料，需求为≥约束，超产不计","industryor-0057__r2")]),
 R("industryor-0067","min","7-12月两种产品产量与月末库存（件）、自有仓库与外租仓库使用体积（连续）；最小化生产成本+仓储成本；库存平衡、月总产能12万件、自有仓库≤15000立方米。",
   "LP","产量和库存线性平衡、仓储分为自有（有上限、单价1）和外租（单价1.5）两段，成本凸，目标和约束线性；件数按整数建模但连续松弛最优值相同，标LP。","MEDIUM",ia=True,
   notes="主模型把产量与库存设为整数，改为连续后最优值不变。仓储费按月末库存体积计；1-6月的需求与成本数据与7-12月计划无关，未使用；期末库存未强制为0（最优解为0）。"),
 R("industryor-0089","max","产品A、B每周产量（kg，连续）；最大化利润30A+10B；工时6A+3B≤40、B≥3A、储存约束。",
   "LP","两个连续产量变量，所有约束与目标线性。","HIGH",conf="MEDIUM",issue="AMBIGUOUS",
   issue_note="'The storage space required for product A is four times that of product B, and a maximum of four kilograms of product A can be stored per week'可理解为A≤4kg（此时该约束不紧，B的储存不受限），也可理解为仓库容量相当于4kg A的空间，即4A+B≤16（以B的单位空间计）。两种读法最优值不同。",
   readings=[rd("储存约束为A≤4","industryor-0089"), rd("储存约束为4A+B≤16（仓库容量等于4kg A所占空间）","industryor-0089__r2")],
   notes="主读法求解值有1e-6级浮点误差，精确值为160。"),
 R("industryor-0093","max","x1、x2为每天分配给A1、A2加工的牛奶桶数（连续）；最大化利润72x1+64x2；牛奶≤50桶、工时12x1+8x2≤480、A1产量3x1≤100。",
   "LP","两个连续变量（桶数），约束与目标线性。","HIGH",
   notes="最优解为整数（20桶和30桶），桶数是否取整不影响结果。"),
 R("mamo_complex_lp-0003","min","五种食物份数（整数）；最小化费用；蛋白质、碳水、热量下限。",
   conf="MEDIUM",ia=True,notes="题面未说明食物份数能否为小数；按不可分的份数取整数，连续松弛值见integer_relaxed_objective。"),
 R("mamo_complex_lp-0017","min","四种食物份数（整数）；最小化费用；蛋白质、碳水、热量下限。",
   conf="MEDIUM",ia=True,notes="题面未说明份数能否为小数；按整数份数作主模型，连续松弛值见integer_relaxed_objective。"),
 R("mamo_complex_lp-0064","min","5城市TSP，0-1弧变量与MTZ子回路消除；最小化总费用；每城出入各一次。",
   notes="对称费用矩阵；另用全排列枚举核对，结果一致。"),
 R("mamo_complex_lp-0083","min","4城市TSP，0-1弧变量与MTZ子回路消除；最小化总费用。",
   notes="全排列枚举核对一致。"),
 R("mamo_complex_lp-0135","max","9节点网络最大流，弧流量连续且不超过容量；中间节点流量守恒；最大化源点0的净流出。",
   notes="容量为0的弧视为不存在；结果等于进入节点8的弧容量总和（构成最小割）。"),
]
with open("results.jsonl","w",encoding="utf-8") as fh:
    for r in rows:
        fh.write(json.dumps(r, ensure_ascii=False) + "\n")
print(len(rows))
