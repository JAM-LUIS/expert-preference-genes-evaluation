#!/usr/bin/env python3
"""Build the adjudication sheet for the adjudicator (code C = Qi Deng) from the output of compare.py.

  python3 make_adjudication.py [--results-root DIR] [--hidden DIR] [--comparison DIR] [--out DIR] [--force]
  python3 make_adjudication.py --round2 --filled <filled round-1 adjudication_C.xlsx>   # second audit round, only
      if round 1 of the reference audit or of the type audit overturned >= 1 case (main-session rule 2026-09-29);
      writes <hidden>/adjudication_round2/ (same layout, one data sheet 随机复核第二轮) or reports that none is needed

Reads   <hidden>/comparison/comparison.json (compare.py), <hidden>/references.json, <hidden>/source_cases/ (statements),
        <results-root>/batch_{A,B}/<group>/results.jsonl and the model scripts named there
Writes  <out>/ (default <hidden>/adjudication/), a self-contained folder to hand to the adjudicator:
          adjudication_C.xlsx          sheet "说明" (guide) and three data sheets, listed separately by source:
                                         抽样核对   reference checks of the 66 sampled cases (adjudication + random audit)
                                         全量筛查   full-screening findings: unsampled IndustryOR cases where both batches
                                                    agree with each other and both differ from the reference
                                         只定题型   rows that only need a type label (adjudication + random audit)
                                       one row per case: statement, reference (and older-release answers), batch A / B
                                       results, model summaries, doubts; dropdowns for the verdict and the type,
                                       corrected value, one-sentence reason, optional minutes
          adjudication_readable.html   the same content laid out for reading, in the same three sections, with the
                                       full statements and scripts
          ADJUDICATION_GUIDE_zh.md     instructions in Chinese (also the first sheet of the xlsx and the top of the HTML)
          models/A/..., models/B/...   copies of the batch scripts and outputs of the rows in the sheet
          adjudication_rows.json       which items each row needs and on which sheet (read by export_for_ingest.py)
          MANIFEST.sha256
ISOLATION: the folder holds TEST statements and reference answers. Only the coordinator and the adjudicator may open
it; nobody who writes or reviews genes. The script prints counts and case ids only.
"""
import argparse
import collections
import html
import json
import os
import re
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _common as C  # noqa: E402

XLSX_NAME = f"adjudication_{C.ADJUDICATOR_CODE}.xlsx"
SHEETS = (("sample", "抽样核对"), ("screening", "全量筛查"), ("type_only", "只定题型"))
SOURCE_ZH = {"sample": "抽样核对（66 道抽样题）", "screening": "全量筛查发现（抽样以外的 IndustryOR 题）",
             "type_only": "只定题型"}
RESULT_ZH = {"MATCH": "与参考一致", "ROUNDED": "取整后与参考一致", "ALT_MATCH": "主值不一致，另一个值与参考一致",
             "MISMATCH": "与参考不一致", "NO_VALUE": "没有目标值", "MISSING": "缺结果"}
ALT_ZH = {"integer_relaxed": "整数松弛值", "asked_value": "题目所问量"}
MINUTES = {"verdict_adjudicate_mamo": (5, 10), "verdict_adjudicate_industryor": (10, 15), "verdict_screen": (10, 15),
           "type_adjudicate": (3, 5), "verdict_audit": (3, 5), "type_audit": (2, 3)}


def hint_codes(codes):
    out = []
    for c in codes:
        x, _, rest = c.partition("_")
        who = x if x in C.BATCHES else ""
        if c == "SCREEN_AB_AGREE_BOTH_OFF_REFERENCE":
            out.append("全量筛查发现：本题不在 66 道抽样题里；A、B 两批的结果彼此一致（主容差内），但都与参考答案不一致")
        elif c == "AB_AGREE_BOTH_OFF_REFERENCE":
            out.append("A、B 的结果一致，但都与参考不一致：INCORRECT 或 CORRECT_ROUNDED 候选")
        elif c == "AB_DISAGREE":
            out.append("A、B 的结果互不一致")
        elif c == "TYPE_DISAGREE":
            out.append("A、B 的题型不一致")
        elif who and rest == "ROUNDED":
            out.append(f"{who} 的值取整后与参考一致：CORRECT_ROUNDED 候选（也可能是整数性差异）")
        elif who and rest == "ALT_MATCH":
            out.append(f"{who} 的另一个值（其他读法 / 整数松弛值 / 题目所问量）与参考一致：AMBIGUOUS 候选")
        elif who and rest == "MISMATCH":
            out.append(f"{who} 与参考不一致")
        elif who and rest == "NO_VALUE":
            out.append(f"{who} 没有给出目标值")
        elif who and rest in ("AMBIGUOUS", "UNDERSPECIFIED"):
            out.append(f"{who} 报告题面{'有歧义' if rest == 'AMBIGUOUS' else '缺数据'}")
        elif who and rest == "LOW_CONFIDENCE":
            out.append(f"{who} 对模型低置信")
        elif who and rest.startswith("STATUS_"):
            out.append(f"{who} 的求解状态不是 Optimal（{rest[7:]}）")
        elif who and rest == "INVALID":
            out.append(f"{who} 的结果行格式有问题")
        elif who and rest.startswith("OUTPUT_"):
            out.append(f"{who} 的脚本输出与所报目标值对不上或缺输出（{rest[7:].lower()}）")
        elif who and rest.startswith("RERUN_"):
            out.append(f"{who} 的脚本重跑未复现（{rest[6:].lower()}）")
        elif who and rest == "MISSING":
            out.append(f"{who} 缺这道题的结果")
        elif who and rest in ("NL_LINEARIZABLE", "NL_NOT_LINEARIZABLE"):
            out.append(f"{who} 标为 {rest}")
        elif who and rest == "TYPE_LOW_CONFIDENCE":
            out.append(f"{who} 对题型低置信")
        elif who and rest == "TYPE_INVALID":
            out.append(f"{who} 的题型字段缺失或不合规")
        else:
            out.append(c)
    return out


def load_raw_rows(results_root, groups):
    raw = {b: {} for b in C.BATCHES}
    for b in C.BATCHES:
        for g in groups[b]:
            path = os.path.join(C.group_dir(results_root, b, g), "results.jsonl")
            if not os.path.exists(path):
                continue
            with open(path, encoding="utf-8") as f:
                for line in f:
                    try:
                        r = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(r, dict) and r.get("case_id") in groups[b][g] and r["case_id"] not in raw[b]:
                        raw[b][r["case_id"]] = (g, r)
    return raw


def fmt(v):
    if v is None:
        return ""
    if isinstance(v, float):
        return str(int(v)) if v.is_integer() and abs(v) < 1e15 else repr(v)
    return str(v)


def other_release_text(ref):
    parts = []
    for o in ref.get("other_releases", []):
        if o["release"].startswith("IndustryOR first release"):
            parts.append(f"2024 首版（HF bd09345a，2024-05-29；那一版题面措辞不同；两版题目对应的置信度 "
                         f"{o.get('lineage_match_confidence', '?')}）：{o['answer_raw']}")
        else:
            parts.append(f"HF 快照 e1bb6174（2025-10-11；题面与现版相同，2026-05 数据集作者改了答案）：{o['answer_raw']}")
    return "；".join(parts)


def batch_cells(X, entry, raw_row, ref_res, copies, show_ref):
    n = entry[X]
    r = raw_row[1] if raw_row else {}
    if not n.get("present"):
        return {f"{X}_status": "（缺结果）"}
    alts = []
    for label, v in n.get("alts", []):
        alts.append(f"{ALT_ZH.get(label, label.replace('reading_', '读法 '))}：{fmt(v)}")
    issue = n.get("issue") or ""
    doubt = []
    if issue and issue != "NONE":
        doubt.append(f"[{issue}] {str(r.get('issue_note') or '').strip()}")
    if n.get("integrality_ambiguous"):
        doubt.append("[整数性拿不准]")
    if str(r.get("notes") or "").strip():
        doubt.append(f"[备注] {str(r.get('notes')).strip()}")
    for rd in r.get("readings") or []:
        if isinstance(rd, dict):
            doubt.append(f"[读法] {str(rd.get('reading') or '').strip()} → {fmt(C.num(rd.get('objective')))} "
                         f"（{rd.get('status') or ''}）")
    t = n.get("type") or ""
    if t == "NL_LINEARIZABLE" and n.get("type_after_linearization"):
        t += f" → {n['type_after_linearization']}"
    vs = ""
    if show_ref and ref_res:
        vs = RESULT_ZH.get(ref_res["result"], ref_res["result"])
        if ref_res.get("detail"):
            d = ref_res["detail"]
            vs += f"（{ALT_ZH.get(d, d.replace('reading_', '读法 '))}）"
    return {
        f"{X}_status": n.get("status") or "",
        f"{X}_objective": fmt(n.get("value")) or (n.get("special") or ""),
        f"{X}_alternatives": "；".join(alts),
        f"{X}_vs_reference": vs,
        f"{X}_type": t,
        f"{X}_type_conf": n.get("type_confidence") or "",
        f"{X}_conf": n.get("confidence") or "",
        f"{X}_issue": "\n".join(doubt),
        f"{X}_type_rationale": str(r.get("type_rationale") or "").strip(),
        f"{X}_summary": str(r.get("model_summary") or "").strip(),
        f"{X}_script": "\n".join(copies),
    }


def copy_scripts(results_root, X, raw_row, out, cid):
    """Copy the batch's scripts and outputs for this case into out/models/X/; return the relative paths and texts."""
    if not raw_row:
        return [], {}
    g, r = raw_row
    mdir = os.path.join(C.group_dir(results_root, X, g), "models")
    rels, texts = [], {}
    if not os.path.isdir(mdir):
        return rels, texts
    named = {r.get("model_file"), r.get("output_file")}
    named |= {rd.get("model_file") for rd in (r.get("readings") or []) if isinstance(rd, dict)}
    named = {os.path.basename(x) for x in named if isinstance(x, str) and x.startswith("models/") and ".." not in x}
    for fn in sorted(os.listdir(mdir)):
        if not (fn in named or fn.startswith(f"{cid}__") or fn.startswith(f"{cid}.")):
            continue
        src = os.path.join(mdir, fn)
        if not os.path.isfile(src):
            continue
        dst_rel = os.path.join("models", X, fn)
        os.makedirs(os.path.join(out, "models", X), exist_ok=True)
        shutil.copy2(src, os.path.join(out, dst_rel))
        rels.append(dst_rel)
        with open(src, encoding="utf-8", errors="replace") as f:
            texts[dst_rel] = f.read()[:200000]
    return rels, texts


# ------------------------------------------------------------------ guide

def guide_text(n):
    m = MINUTES
    return f"""# 参考答案核对与题型标注：裁决说明

给裁决人（代号 C，Qi Deng）。本文件、裁决表 `{XLSX_NAME}` 的第一页和 HTML 阅读版开头是同一份说明。

## 1 背景和做法

- EAAI-26-22218 的修改稿要核对两个基准的参考答案，并给 IndustryOR 全部 100 题标题型（LP / MILP / IP / 可线性化的非线性 / 不可线性化的非线性）。
- 做法（2026-09-29 定）：两批互相隔离的 AI agent（A 批、B 批，用两个不同的模型）在**看不到参考答案**的情况下，对 MAMO ComplexLP 25 题和 IndustryOR 全部 100 题各自独立建模、用 PuLP 自带的 CBC 求解，并给 IndustryOR 题标题型。之后才由脚本与参考答案比对。
- 参考答案分两种范围处理：
  - **抽样核对**（事先抽定的 66 道题：MAMO 25 + IndustryOR 41）：两批都与参考答案在容差内一致，而且两批都是最优解、都没报歧义或缺数据、都不是低置信、脚本输出与所报值一致 → 自动记 CORRECT；其余全部交您裁决。
  - **全量筛查**（抽样以外的 59 道 IndustryOR 题）：只有 A、B 两批的结果彼此一致、而又都与参考答案不一致时，才交您裁决（强信号）；其余情况保留原参考值，不用您看。
- 题型（2026-09-29 定）：只有涉及非线性或拿不准的题交您裁决——任一批标为 NL_LINEARIZABLE 或 NL_NOT_LINEARIZABLE、或任一批对题型低置信。LP、MILP、IP 之间的分歧不交裁决：两批标签相同就采用；不同时取目标值与参考答案一致的那一批的标签，两批都一致或都不一致时记为"线性、类别未定"（只从按题型分层的分析里剔除，不影响分析集合）。
- 另外按固定种子从自动结果里各随机抽 10 道请您复核（抽样核对里自动记 CORRECT 的 10 道、自动定下的题型 10 道）。哪一类复核里只要推翻了 1 道，就按固定种子再抽 10 道请您做第二轮复核；之后不再扩大。两轮的推翻率都会在论文里报告，推翻的题按您的裁决改。
- 裁决表分三页，按来源分开列：
  - **抽样核对**：{n['sheet_rows']['sample']} 行（结论裁决 {n['verdict_adjudicate']} 项、结论随机复核 {n['verdict_audit']} 项，同一行可能还要定题型）；
  - **全量筛查**：{n['sheet_rows']['screening']} 行（全量筛查发现 {n['verdict_screen']} 项，同一行可能还要定题型）；
  - **只定题型**：{n['sheet_rows']['type_only']} 行。
  - 题型合计：裁决 {n['type_adjudicate']} 项、随机复核 {n['type_audit']} 项。
- 按下面第 7 节的每条用时估计，合计约 **{n['hours_low']}–{n['hours_high']} 小时**。

## 2 每一行怎么做

1. 看"需要你定的项"一列：本行要定结论、题型，还是两者；是裁决、全量筛查发现，还是随机复核。
2. 读题面。长题在 `adjudication_readable.html` 里读更方便（内容相同、分同样三部分，另有两批脚本的全文）。
3. 看参考答案（有旧版本答案的也列出，仅供参考）、A 和 B 的状态、目标值、其他值、题型、置信度、模型摘要和疑点。"脚本提示"一列是比对脚本给出的候选，只供参考，由您决定。
4. 需要时打开两批的模型脚本（在本文件夹的 `models/A/`、`models/B/` 下，文件名以题号开头）。可以在本机用 Python/PuLP 重跑或修改：`python3 -m pip install pulp` 后运行 `python3 models/A/<题号>.py`。
5. 填黄色列（灰色的是本行不需要定的项，留空）：
   - **裁决：结论**（下拉）：五类见第 3 节；
   - **裁决：正确值**：见第 4 节；
   - **裁决：题型**（下拉）；标 NL_LINEARIZABLE 的另填**线性化后类型**（下拉：LP / MILP / IP）；
   - **裁决：一句理由**：一句话说明依据，例如"A 漏了第 3 条产能约束，B 与参考一致"；
   - 用时（分钟，可选）。
6. 不改蓝色列，不改文件名和页名，保存为 .xlsx。

## 3 结论五类

容差与实验的判分规则相同：|正确值 − 参考答案| ≤ max(1e-4, 1e-4 × |参考答案|)。

| 结论 | 含义 |
|---|---|
| CORRECT | 按题面最合理的理解建模，最优值与参考答案在容差内一致 |
| CORRECT_ROUNDED | 参考答案是正确最优值四舍五入（或截断）的结果，但超出了上面的容差 |
| INCORRECT | 题面清楚、数据齐全，但参考答案不是最优值，也不是舍入造成的 |
| AMBIGUOUS | 题面有两种或以上说得通的理解，最优值各不相同 |
| UNDERSPECIFIED | 题面缺少建模所需的数据，建不出完整模型 |

- 整数性：题面明确要求整数，或者变量是不可分割的个数（人、车、台、件、班次、次数等）而题面没说可以取小数，按整数处理；可分的量（吨、升、小时、金额、比例等）按连续处理。整数版本和连续版本最优值不同、参考答案只和其中一个一致、而两种理解都说得通时，选 AMBIGUOUS。
- 参考答案看起来像某个决策变量的值、而不是目标值：选 INCORRECT，理由里写明。
- 全量筛查发现的题：两批 agent 一致不等于它们一定对；如果您认为参考答案是对的（两批犯了同样的错），就选 CORRECT。

## 4 正确值怎么填

- CORRECT：可以留空；
- CORRECT_ROUNDED：填精确的最优值；
- INCORRECT：填正确的最优值；无解填 `infeasible`，无界填 `unbounded`；
- AMBIGUOUS：填您认为最合理那种理解下的值；
- UNDERSPECIFIED：留空。
- 用普通数字，不加千分位逗号，例如 `98765.25` 或 `0.4375`。

## 5 题型五类（只对 IndustryOR 题）

- **LP**：目标和约束都是线性的，所有决策变量连续；**IP**：线性，所有决策变量都是整数（含 0-1）；**MILP**：线性，既有连续变量又有整数或 0-1 变量。固定费用、启动成本、二选一、若…则…、至多/至少选 k 个等逻辑条件，教科书上本来就用 0-1 变量加线性约束写，直接标 MILP 或 IP。两边同乘恒正量、移项后是线性的约束（如"A 的产量至少占总产量的 30%"），按线性处理。
- **NL_LINEARIZABLE**：最直接的模型里有决策变量的非线性项（两个变量相乘或相除、max/min、绝对值、分段函数、取整、平方、开方、指数、对数等），但能**精确**线性化：改写后只有线性目标和约束（可加辅助变量），最优值完全相同，大 M 能从题面数据或变量上下界推出，用教科书标准技巧即可（含 0-1 因子的乘积、有界整数变量的非线性函数、max/min/绝对值、分段线性、线性分式目标的 Charnes–Cooper 变换、取整）。另填线性化后类型。
- **NL_NOT_LINEARIZABLE**：非线性且不能精确线性化，例如两个连续决策变量相乘（价格 × 销量）、连续变量的二次项、开方、指数、对数。用分段线性去近似光滑函数不算精确线性化。
- 一道题既有逻辑条件又有需要线性化的乘积：以需要线性化的非线性项为准。题面缺数据的题，仍按能看出的结构标题型。

## 6 随机复核

- 复核行（"需要你定的项"写着"随机复核"）的结论或题型已由自动规则定下。请和裁决一样独立判断：同意就选 CORRECT（结论）或与自动结果相同的题型；不同意就选您的结论或题型，并写理由。
- 第一轮复核里只要推翻 1 道（结论或题型分别计），协调人会按固定种子再给您 10 道同类的题做第二轮复核（另一张表）；第二轮之后不再扩大。

## 7 每条大约几分钟（估计，没有实测）

| 项 | 每条 |
|---|---|
| 抽样核对的结论裁决，MAMO | {m['verdict_adjudicate_mamo'][0]}–{m['verdict_adjudicate_mamo'][1]} 分钟 |
| 抽样核对的结论裁决，IndustryOR | {m['verdict_adjudicate_industryor'][0]}–{m['verdict_adjudicate_industryor'][1]} 分钟 |
| 全量筛查发现（IndustryOR） | {m['verdict_screen'][0]}–{m['verdict_screen'][1]} 分钟 |
| 题型裁决 | {m['type_adjudicate'][0]}–{m['type_adjudicate'][1]} 分钟 |
| 结论随机复核 | {m['verdict_audit'][0]}–{m['verdict_audit'][1]} 分钟 |
| 题型随机复核 | {m['type_audit'][0]}–{m['type_audit'][1]} 分钟 |

建议先做 2–3 行，把用时告诉协调人。

## 8 结论怎样用于实验打分（供参考，test 运行前已写定）

- CORRECT：保留原参考值；CORRECT_ROUNDED：换成精确值，另报用原值打分的结果；INCORRECT：换成更正值，另报用原值打分的结果；AMBIGUOUS、UNDERSPECIFIED：移出主分析，只留在全量敏感性分析。全量筛查发现的题经您裁决后按同样的规则处理；筛查没有标出的题保留原参考值。
- IndustryOR 题型为 NL_NOT_LINEARIZABLE 的题保留，但单独报告，不进主表。

## 9 必须遵守

1. **隔离**：本表和本文件夹含 test 题面和参考答案。看过 test 题面的人（包括您）在 test 运行之前不能参与 gene（实验用的专家规则）的起草、修改和审阅，也不要和写 gene 的人讨论具体题目。
2. **独立判断**：不要把题面粘贴进任何 AI 工具或在线服务（包括聊天机器人、在线求解器、在线翻译）。可以用本机的 Python/PuLP、Excel、计算器和纸笔。
3. **保密**：不转发本文件夹，不在公开渠道发题面。任务结束后按协调人要求删除本地副本。许可：MAMO ComplexLP 为 CC BY-SA 4.0，IndustryOR 为 CC BY-NC 4.0，这里只用于非商业的研究核对。
4. **交回**：填好的 `{XLSX_NAME}`（不改文件名）只发给协调人：[作者填写：协调人姓名和提交渠道]。
"""


def inline(s):
    s = html.escape(s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"`(.+?)`", r"<code>\1</code>", s)
    return s


def md_to_html(md):
    out, in_list, in_table = [], False, False
    for line in md.splitlines():
        s = line.rstrip()
        if s.startswith("|"):
            cells = [c.strip() for c in s.strip("|").split("|")]
            if all(set(c) <= set("-: ") for c in cells):
                continue
            tag = "th" if not in_table else "td"
            if not in_table:
                out.append("<table class='g'>")
                in_table = True
            out.append("<tr>" + "".join(f"<{tag}>{inline(c)}</{tag}>" for c in cells) + "</tr>")
            continue
        if in_table:
            out.append("</table>")
            in_table = False
        mm = re.match(r"^\s*(?:- |\d+\. )(.*)$", s)
        if mm:
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{inline(mm.group(1))}</li>")
            continue
        if in_list:
            out.append("</ul>")
            in_list = False
        if s.startswith("## "):
            out.append(f"<h2>{inline(s[3:])}</h2>")
        elif s.startswith("# "):
            out.append(f"<h1>{inline(s[2:])}</h1>")
        elif s:
            out.append(f"<p>{inline(s)}</p>")
    if in_list:
        out.append("</ul>")
    if in_table:
        out.append("</table>")
    return "\n".join(out)


# ------------------------------------------------------------------ xlsx

COLS = [
    # key, header, width, kind (given | fill | opt), dropdown
    ("case_id", "case_id｜题号", 18, "given", None),
    ("source", "source｜来源", 18, "given", None),
    ("benchmark", "benchmark｜基准", 14, "given", None),
    ("split", "split｜划分", 7, "given", None),
    ("todo", "todo｜需要你定的项", 20, "given", None),
    ("problem_text", "problem_text｜题面（长题看 HTML 阅读版）", 90, "given", None),
    ("reference", "reference｜参考答案", 14, "given", None),
    ("other_release", "other_release｜旧版本答案（仅部分题有，仅供参考）", 30, "given", None),
    ("hint", "hint｜脚本提示（候选，仅供参考）", 34, "given", None),
    ("AB", "AB｜A 与 B 的目标值是否一致", 12, "given", None),
]
for _X in C.BATCHES:
    COLS += [
        (f"{_X}_status", f"{_X}_status｜{_X}：求解状态", 12, "given", None),
        (f"{_X}_objective", f"{_X}_objective｜{_X}：目标值", 14, "given", None),
        (f"{_X}_alternatives", f"{_X}_alternatives｜{_X}：其他值（整数松弛 / 其他读法 / 题目所问量）", 22, "given", None),
        (f"{_X}_vs_reference", f"{_X}_vs_reference｜{_X}：与参考比", 16, "given", None),
        (f"{_X}_type", f"{_X}_type｜{_X}：题型", 14, "given", None),
        (f"{_X}_type_conf", f"{_X}_type_conf｜{_X}：题型把握", 9, "given", None),
        (f"{_X}_conf", f"{_X}_conf｜{_X}：模型把握", 9, "given", None),
        (f"{_X}_issue", f"{_X}_issue｜{_X}：疑点（歧义 / 缺数据 / 备注）", 34, "given", None),
        (f"{_X}_type_rationale", f"{_X}_type_rationale｜{_X}：题型依据", 30, "given", None),
        (f"{_X}_summary", f"{_X}_summary｜{_X}：模型摘要", 34, "given", None),
        (f"{_X}_script", f"{_X}_script｜{_X}：脚本（本文件夹内）", 26, "given", None),
    ]
COLS += [
    ("final_verdict", "final_verdict｜裁决：结论", 18, "fill", list(C.VERDICTS)),
    ("final_value", "final_value｜裁决：正确值", 16, "fill", None),
    ("final_type", "final_type｜裁决：题型", 20, "fill", list(C.TYPE_LABELS)),
    ("final_type_after_linearization", "final_type_after_linearization｜裁决：线性化后类型（仅 NL_LINEARIZABLE）", 16,
     "fill", list(C.POST_LIN)),
    ("reason", "reason｜裁决：一句理由", 40, "fill", None),
    ("minutes", "minutes｜用时（分钟，可选）", 10, "opt", None),
]


def build_xlsx(path, guide, rows_by_sheet, sheets=SHEETS):
    from openpyxl import Workbook
    from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.worksheet.datavalidation import DataValidation
    arial = "Arial"
    thin = Side(style="thin", color="BFBFBF")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    fills = {"given": PatternFill("solid", fgColor="1F3864"), "fill": PatternFill("solid", fgColor="BF8F00"),
             "opt": PatternFill("solid", fgColor="7F7F7F")}
    cell_fill = PatternFill("solid", fgColor="FFF2CC")
    cell_opt = PatternFill("solid", fgColor="F2F2F2")
    cell_na = PatternFill("solid", fgColor="D9D9D9")
    wb = Workbook()
    ws0 = wb.active
    ws0.title = "说明"
    ws0.column_dimensions["A"].width = 160
    for i, line in enumerate(guide.splitlines(), 1):
        c = ws0.cell(row=i, column=1, value=line)
        c.font = Font(name=arial, size=12 if line.startswith("#") else 10, bold=line.startswith("#"))
        c.alignment = Alignment(wrap_text=True, vertical="top")
    lists = wb.create_sheet("lists")
    lcol_of = {}
    lcol = 1
    for key, _, _, _, allowed in COLS:
        if allowed:
            for k, v in enumerate(allowed, 1):
                lists.cell(row=k, column=lcol, value=v)
            lcol_of[key] = (lists.cell(row=1, column=lcol).column_letter, len(allowed))
            lcol += 1
    for key, title in sheets:
        rows = rows_by_sheet[key]
        ws = wb.create_sheet(title)
        for j, (ckey, hdr, width, kind, _) in enumerate(COLS, 1):
            c = ws.cell(row=1, column=j, value=hdr)
            c.font = Font(name=arial, size=10, bold=True, color="FFFFFF")
            c.fill = fills[kind]
            c.alignment = Alignment(wrap_text=True, vertical="center")
            c.border = border
            ws.column_dimensions[c.column_letter].width = width
        ws.row_dimensions[1].height = 64
        for i, r in enumerate(rows, 2):
            for j, (ckey, _, _, kind, _) in enumerate(COLS, 1):
                val = r.get(ckey, "")
                if isinstance(val, str):
                    val = ILLEGAL_CHARACTERS_RE.sub("", val)
                    if ckey != "problem_text":
                        val = val[:32000]
                c = ws.cell(row=i, column=j, value=val)
                if isinstance(val, str) and val.startswith("="):
                    c.data_type = "s"            # text, never a formula
                c.font = Font(name=arial, size=10)
                c.alignment = Alignment(wrap_text=True, vertical="top")
                c.border = border
                c.number_format = "@"
                if kind == "fill":
                    needed = ((ckey in ("final_verdict", "final_value") and r["_needs_verdict"])
                              or (ckey in ("final_type", "final_type_after_linearization") and r["_needs_type"])
                              or ckey == "reason")
                    c.fill = cell_fill if needed else cell_na
                elif kind == "opt":
                    c.fill = cell_opt
        ws.freeze_panes = "B2"
        ws.auto_filter.ref = f"A1:{ws.cell(row=1, column=len(COLS)).column_letter}{max(2, len(rows) + 1)}"
        for j, (ckey, _, _, _, allowed) in enumerate(COLS, 1):
            if not allowed:
                continue
            L, n = lcol_of[ckey]
            dv = DataValidation(type="list", formula1=f"=lists!${L}$1:${L}${n}", allow_blank=True,
                                showErrorMessage=True, errorTitle="Invalid value", error="请从下拉列表中选择")
            colL = ws.cell(row=1, column=j).column_letter
            dv.add(f"{colL}2:{colL}{max(2, len(rows) + 1)}")
            ws.add_data_validation(dv)
    wb.move_sheet("lists", offset=len(sheets))      # order: 说明, three data sheets, lists (hidden)
    lists.sheet_state = "hidden"
    wb.active = 0
    wb.save(path)


# ------------------------------------------------------------------ html

def build_html(path, guide, rows_by_sheet, scripts, sheets=SHEETS):
    css = ("body{font-family:Arial,Helvetica,sans-serif;max-width:1100px;margin:24px auto;padding:0 16px;line-height:1.5;"
           "color:#1a1a1a;background:#fff}h1{font-size:22px}h2{font-size:17px;margin-top:22px}.warn{background:#fdecea;"
           "border:1px solid #e0a09a;padding:8px 12px}.case{border-top:2px solid #1F3864;padding:14px 0;margin-top:18px}"
           ".case h3{margin:0 0 4px;font-size:17px}.todo{background:#FFF2CC;padding:2px 6px;font-weight:bold}"
           ".sub{color:#555;font-size:13px}pre{white-space:pre-wrap;word-wrap:break-word;background:#f7f7f7;padding:8px;"
           "border:1px solid #e5e5e5;font-size:13px}table{border-collapse:collapse;width:100%;font-size:13px}"
           "td,th{border:1px solid #ccc;padding:4px 6px;vertical-align:top;text-align:left}th{background:#eef1f7}"
           "table.g{width:auto}details{margin:6px 0}summary{cursor:pointer;color:#1F3864}nav a{margin-right:6px;"
           "font-size:12px}.hint{background:#eef7ee;padding:6px 8px;border:1px solid #cfe3cf}"
           ".part{background:#1F3864;color:#fff;padding:6px 10px;margin-top:36px}")
    parts = ["<!doctype html><html lang='zh'><head><meta charset='utf-8'>",
             "<meta name='viewport' content='width=device-width, initial-scale=1'>",
             "<title>参考答案裁决（阅读版）</title>", f"<style>{css}</style></head><body>",
             "<p class='warn'>含 test 题面和参考答案。写或审阅 gene 的人不得打开本文件。阅读用；结论请填在 "
             f"{html.escape(XLSX_NAME)} 里（三页分别对应下面三部分）。</p>", md_to_html(guide)]
    fields = [("status", "求解状态"), ("objective", "目标值"), ("alternatives", "其他值"), ("vs_reference", "与参考比"),
              ("type", "题型"), ("type_conf", "题型把握"), ("conf", "模型把握"), ("issue", "疑点"),
              ("type_rationale", "题型依据"), ("summary", "模型摘要"), ("script", "脚本")]
    for k, (key, title) in enumerate(sheets, 1):
        rows = rows_by_sheet[key]
        parts.append(f"<h2 class='part'>{k}. {html.escape(title)}（{len(rows)} 行；对应 xlsx 的“{html.escape(title)}”页）</h2>")
        parts.append("<nav>" + "".join(f"<a href='#{html.escape(r['case_id'])}'>{html.escape(r['case_id'])}</a>"
                                       for r in rows) + "</nav>")
        for r in rows:
            cid = html.escape(r["case_id"])
            parts.append(f"<div class='case' id='{cid}'><h3>{cid}</h3>"
                         f"<div class='sub'>{html.escape(r['source'])} · {html.escape(r['benchmark'])} · "
                         f"{html.escape(r['split'])} · <span class='todo'>需要你定：{html.escape(r['todo'])}</span></div>")
            parts.append(f"<pre>{html.escape(r['problem_text'])}</pre>")
            parts.append(f"<p><b>参考答案：</b>{html.escape(r['reference'])}"
                         + (f"<br><b>旧版本答案：</b>{html.escape(r['other_release'])}" if r["other_release"] else "")
                         + "</p>")
            if r["hint"]:
                parts.append(f"<div class='hint'><b>脚本提示（候选，仅供参考）：</b>{html.escape(r['hint'])}</div>")
            parts.append(f"<p><b>A 与 B 的目标值：</b>{html.escape(r['AB'])}</p>")
            parts.append("<table><tr><th></th><th>A</th><th>B</th></tr>")
            for fk, zh in fields:
                a, b = r.get(f"A_{fk}", ""), r.get(f"B_{fk}", "")
                parts.append(f"<tr><th>{zh}</th><td>{html.escape(str(a)).replace(chr(10), '<br>')}</td>"
                             f"<td>{html.escape(str(b)).replace(chr(10), '<br>')}</td></tr>")
            parts.append("</table>")
            for rel in r["_scripts"]:
                parts.append(f"<details><summary>{html.escape(rel)}</summary>"
                             f"<pre>{html.escape(scripts.get(rel, ''))}</pre></details>")
            parts.append("</div>")
    parts.append("</body></html>")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(parts))


# ------------------------------------------------------------------ main

ROUND2_SHEETS = (("round2", "随机复核第二轮"),)
ROUND2_HEADER = """# 第二轮随机复核

第一轮随机复核里有自动结论被推翻（结论或题型分别计），按事先写定的规则再按固定种子抽 10 道同类的题请您复核；本轮之后不再扩大。做法与第一轮的"随机复核"行相同（见下面说明第 6 节）。本轮 {rows} 行：结论复核 {verdict_audit} 项、题型复核 {type_audit} 项，估计约 {hours_low}–{hours_high} 小时。

"""


def selection_round1(comp):
    """{case_id: (verdict item, type item)}; items: adjudicate / audit / screen / None."""
    sel = {}
    for cid, e in comp["cases"].items():
        rt = e["routing"]
        if rt["for_adjudicator"] != "Y":
            continue
        v = {"ADJUDICATE": "adjudicate", "AUDIT": "audit", "SCREEN_FLAG": "screen"}.get(rt["ref_route"])
        t = {"ADJUDICATE": "adjudicate", "AUDIT": "audit"}.get(rt["type_route"])
        sel[cid] = (v, t)
    return sel


def round1_overturns(comp, adj_dir, filled):
    """Which audits of round 1 overturned >= 1 case: ({"reference_check": [...], "type_label": [...]}, missing ids).
    Reads only the closed-vocabulary cells of the filled round-1 sheet (via export_for_ingest.read_sheets)."""
    import export_for_ingest as X
    adj = C.load_json(os.path.join(adj_dir, "adjudication_rows.json"))
    sheet, _, _ = X.read_sheets(filled, list(adj["sheets"].values()))
    over, missing = {"reference_check": [], "type_label": []}, []
    for r in adj["rows"]:
        cid, d = r["case_id"], sheet.get(r["case_id"])
        if r["ref_route"] == "AUDIT":
            v = (d or {}).get("final_verdict", "")
            if v in ("", "INVALID"):
                missing.append(cid)
            elif v != "CORRECT":
                over["reference_check"].append(cid)
        if r["type_route"] == "AUDIT":
            t = (d or {}).get("final_type", "")
            if t in ("", "INVALID"):
                missing.append(cid)
            elif t != r["auto_type"]:
                over["type_label"].append(cid)
    return over, sorted(set(missing))


def build_folder(a, comp, sel, out, sheets, round_no, comp_dir):
    refs = C.load_references(a.hidden)["cases"]
    texts = C.load_source_texts(a.hidden)
    groups = C.load_groups(a.package)["groups"]
    raw = load_raw_rows(a.results_root, groups)
    rows_by_sheet = {k: [] for k, _ in sheets}
    scripts, basis = {}, []
    for cid in sorted(sel):
        e = comp["cases"][cid]
        rt = e["routing"]
        v_item, t_item = sel[cid]
        if round_no == 2:
            sheet = "round2"
        elif v_item in ("adjudicate", "audit"):
            sheet = "sample"
        elif v_item == "screen":
            sheet = "screening"
        else:
            sheet = "type_only"
        items = []
        if v_item:
            items.append("结论（" + {"adjudicate": "裁决", "audit": "随机复核" + ("第二轮" if round_no == 2 else ""),
                                     "screen": "全量筛查发现"}[v_item] + "）")
        if t_item:
            items.append("题型（" + {"adjudicate": "裁决", "audit": "随机复核" + ("第二轮" if round_no == 2 else "")}[t_item]
                         + "）")
        hints = []
        rc = e.get("reference_check") or {}
        if v_item == "audit":
            hints.append("结论随机复核：两批都与参考一致，自动记为 CORRECT；请独立判断")
        elif v_item in ("adjudicate", "screen"):
            hints += hint_codes(rc.get("reasons", []))
        tl = e.get("type_label")
        if tl:
            lab = tl["auto_label"]
            if t_item == "audit":
                if tl["auto_kind"] == "AUTO_BY_REFERENCE":
                    hints.append(f"题型随机复核：两批标签不同（都属 LP/MILP/IP），按目标值与参考一致的那一批自动定为 {lab}；"
                                 "请独立判断")
                else:
                    hints.append(f"题型随机复核：两批都标 {lab}，自动定为该题型；请独立判断")
            elif t_item == "adjudicate":
                hints += hint_codes(tl["reasons"])
            elif lab:
                hints.append(f"题型已自动定为 {lab}，本行不用定题型")
        show_ref = sheet in ("sample", "screening") or (round_no == 2 and bool(v_item))
        per = rc.get("per_batch", {})
        row = {"case_id": cid, "source": SOURCE_ZH.get(sheet, "随机复核第二轮"), "benchmark": e["benchmark"],
               "split": e["split"], "todo": "；".join(items), "problem_text": texts[cid],
               "reference": refs[cid]["reference"]["raw"] if show_ref else "（本行只定题型）",
               "other_release": other_release_text(refs[cid]) if show_ref else "",
               "hint": "；".join(hints),
               "AB": {"AGREE": "一致", "DISAGREE": "不一致", "NA": "无法比较"}.get(e["ab_relation"], e["ab_relation"]),
               "_needs_verdict": bool(v_item), "_needs_type": bool(t_item), "_scripts": []}
        for X in C.BATCHES:
            rels, txt = copy_scripts(a.results_root, X, raw[X].get(cid), out, cid)
            scripts.update(txt)
            row["_scripts"] += rels
            row.update(batch_cells(X, e, raw[X].get(cid), per.get(X), rels, show_ref))
        rows_by_sheet[sheet].append(row)
        basis.append({"case_id": cid, "benchmark": e["benchmark"], "split": e["split"], "sheet": sheet,
                      "round": round_no, "ref_scope": rt["ref_scope"],
                      "ref_route": {"adjudicate": "ADJUDICATE", "audit": "AUDIT", "screen": "SCREEN_FLAG"}.get(v_item,
                                                                                                          rt["ref_route"]),
                      "type_route": {"adjudicate": "ADJUDICATE", "audit": "AUDIT"}.get(t_item, rt["type_route"]),
                      "needs_verdict": bool(v_item), "needs_type": bool(t_item),
                      "auto_type": (tl or {}).get("auto_label"), "auto_type_kind": (tl or {}).get("auto_kind")})

    cnt = collections.Counter()
    low = high = 0
    for b in basis:
        k = None
        if b["needs_verdict"]:
            if b["ref_route"] == "ADJUDICATE":
                k = "verdict_adjudicate_" + ("mamo" if b["benchmark"] == "mamo_complex_lp" else "industryor")
                cnt["verdict_adjudicate"] += 1
            elif b["ref_route"] == "AUDIT":
                k = "verdict_audit"
                cnt["verdict_audit"] += 1
            elif b["ref_route"] == "SCREEN_FLAG":
                k = "verdict_screen"
                cnt["verdict_screen"] += 1
            low, high = low + MINUTES[k][0], high + MINUTES[k][1]
        if b["needs_type"]:
            k = "type_adjudicate" if b["type_route"] == "ADJUDICATE" else "type_audit"
            cnt[k] += 1
            low, high = low + MINUTES[k][0], high + MINUTES[k][1]
    stats = {"round": round_no, "rows": len(basis), "sheet_rows": {k: len(v) for k, v in rows_by_sheet.items()},
             "verdict_adjudicate": cnt["verdict_adjudicate"], "verdict_screen": cnt["verdict_screen"],
             "verdict_audit": cnt["verdict_audit"], "type_adjudicate": cnt["type_adjudicate"],
             "type_audit": cnt["type_audit"], "minutes_low": low, "minutes_high": high,
             "hours_low": round(low / 60, 1), "hours_high": round(high / 60, 1)}
    if round_no == 1:
        guide = guide_text(stats)
    else:
        guide = ROUND2_HEADER.format(**stats) + guide_text({**stats, "sheet_rows": {"sample": 0, "screening": 0,
                                                                                     "type_only": 0}})
    xlsx = XLSX_NAME if round_no == 1 else XLSX_NAME.replace(".xlsx", "_round2.xlsx")
    with open(os.path.join(out, "ADJUDICATION_GUIDE_zh.md"), "w", encoding="utf-8") as f:
        f.write(guide)
    build_xlsx(os.path.join(out, xlsx), guide, rows_by_sheet, sheets)
    build_html(os.path.join(out, "adjudication_readable.html"), guide, rows_by_sheet, scripts, sheets)
    C.dump_json(os.path.join(out, "adjudication_rows.json"),
                {"schema": "orgene-r1/annotation_agent/adjudication_rows/v3", "adjudicator": C.ADJUDICATOR_CODE,
                 "round": round_no, "comparison_sha256": C.sha256_file(os.path.join(comp_dir, "comparison.json")),
                 "xlsx": xlsx, "sheets": {k: t for k, t in sheets}, "stats": stats, "rows": basis})
    C.write_manifest(out, skip_agent_outputs=False)
    from openpyxl import load_workbook
    wb = load_workbook(os.path.join(out, xlsx), read_only=True)
    ok = True
    for key, title in sheets:
        it = wb[title].iter_rows(values_only=True)
        hdr = [str(h or "").split("｜")[0] for h in next(it)]
        got = [dict(zip(hdr, r)) for r in it if any(v not in (None, "") for v in r)]
        want = rows_by_sheet[key]
        ok &= len(got) == len(want) and all(g["case_id"] == r["case_id"] and g["problem_text"] == r["problem_text"]
                                            for g, r in zip(got, want))
    print(f"adjudication sheet (round {round_no}): {len(basis)} rows "
          f"({json.dumps(stats['sheet_rows'], ensure_ascii=False)}); statements identical to source: {ok}")
    print("items:", json.dumps({k: v for k, v in stats.items() if k != "sheet_rows"}, ensure_ascii=False))
    for key, title in sheets:
        print(f"  {key}: {' '.join(r['case_id'] for r in rows_by_sheet[key]) or '(none)'}")
    print(f"wrote {out}")
    return ok


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--results-root", default=C.PKG)
    ap.add_argument("--package", default=C.PKG, help=argparse.SUPPRESS)
    ap.add_argument("--hidden", default=C.HIDDEN_DEFAULT)
    ap.add_argument("--comparison", default=None, help="directory of compare.py output (default <hidden>/comparison)")
    ap.add_argument("--out", default=None, help="default <hidden>/adjudication (round 2: <hidden>/adjudication_round2)")
    ap.add_argument("--round2", action="store_true", help="build the second audit round from the filled round-1 sheet")
    ap.add_argument("--filled", default=None, help="with --round2: the filled round-1 adjudication_C.xlsx")
    ap.add_argument("--adjudication", default=None, help="with --round2: the round-1 folder (default <hidden>/adjudication)")
    ap.add_argument("--force", action="store_true", help="overwrite an existing output folder")
    a = ap.parse_args()
    comp_dir = a.comparison or os.path.join(a.hidden, "comparison")
    comp = C.load_json(os.path.join(comp_dir, "comparison.json"))
    if not comp.get("complete"):
        sys.exit("comparison.json was made with --allow-incomplete; run compare.py on complete results first")
    if a.round2:
        if not a.filled:
            sys.exit("--round2 needs --filled <filled round-1 sheet>")
        adj_dir = a.adjudication or os.path.join(a.hidden, "adjudication")
        over, missing = round1_overturns(comp, adj_dir, a.filled)
        if missing:
            sys.exit(f"round-1 audit rows without a decision: {' '.join(missing)}; round 2 is decided on a complete round 1")
        kinds = [k for k, v in over.items() if v]
        out = a.out or os.path.join(a.hidden, "adjudication_round2")
        status = {"round1_overturned": over, "round2_needed_for": kinds,
                  "round1_sheet_sha256": C.sha256_file(a.filled),
                  "candidates": comp["audit"]["round2_candidates"]}
        print(f"round-1 audit overturns: reference {len(over['reference_check'])} {' '.join(over['reference_check'])}; "
              f"type {len(over['type_label'])} {' '.join(over['type_label'])}")
        if not kinds:
            os.makedirs(out, exist_ok=True)
            C.dump_json(os.path.join(out, "round2_status.json"), status)
            print("no round 2 needed (no overturn in round 1); wrote round2_status.json")
            return 0
        if os.path.exists(out) and [x for x in os.listdir(out) if x != "round2_status.json"] and not a.force:
            sys.exit(f"{out} exists and is not empty (use --force to overwrite)")
        if os.path.exists(out) and a.force:
            shutil.rmtree(out)
        os.makedirs(out, exist_ok=True)
        sel = {}
        for k, idx in (("reference_check", 0), ("type_label", 1)):
            if k in kinds:
                for cid in comp["audit"]["round2_candidates"][k]:
                    cur = list(sel.get(cid, (None, None)))
                    cur[idx] = "audit"
                    sel[cid] = tuple(cur)
        C.dump_json(os.path.join(out, "round2_status.json"), status)
        return 0 if build_folder(a, comp, sel, out, ROUND2_SHEETS, 2, comp_dir) else 1
    out = a.out or os.path.join(a.hidden, "adjudication")
    if os.path.exists(out) and os.listdir(out) and not a.force:
        sys.exit(f"{out} exists and is not empty (use --force to overwrite)")
    if os.path.exists(out) and a.force:
        shutil.rmtree(out)
    os.makedirs(out, exist_ok=True)
    return 0 if build_folder(a, comp, selection_round1(comp), out, SHEETS, 1, comp_dir) else 1


if __name__ == "__main__":
    sys.exit(main())
