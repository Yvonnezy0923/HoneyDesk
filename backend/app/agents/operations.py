"""查询问答 Agent（运营/供应链/广告共用）：意图 → 语义模型 → SQL → 图表 → 结论/追问.

P1 扩展（运营子 Agent）：按消息关键词分派选品洞察 / 邮件处理 / 竞品监控三类能力，
否则回退到原有查询问答链路。
"""
from __future__ import annotations

import re

from ..analysis import pipeline as analysis_pipeline
from .toolkit import execute_read


def run(intent, task_id: str, message: str = "", history: str = "") -> dict:
    intent.scope = "operations"
    msg = (message or "").lower()
    if _match_intent(msg, "selection"):
        return _selection_insight(exec_run_intent(intent), task_id, message)
    if _match_intent(msg, "email"):
        return _email_processing(intent, task_id, message)
    if _match_intent(msg, "competitor"):
        return _competitor_monitor(intent, task_id, message)
    params = intent.params
    tables = _pick_tables(intent)
    agent_code = intent.agent_code or "ops_query"

    data = analysis_pipeline.run(
        message, tables,
        {k: v for k, v in params.items() if k in ("sku", "date_from", "date_to", "store_id", "top_n")},
        agent_code=agent_code, task_id=task_id, history=history)

    analyses = data["analyses"]
    insight = data["insight"]
    answer = _render_answer(intent, analyses, top_n=params.get("top_n"))

    sources = []
    for a in analyses:
        sources.append({"table": a["table"], "sql": a.get("sql", ""),
                        "rows": len(a.get("rows") or [])})
    return {
        "answer": answer,
        "sources": sources,
        "proposed_writes": [],
        "artifact": None,
        "cost": data.get("cost", 0.0),
        "analyses": analyses,
        "insight": insight,
        "follow_ups": insight.get("follow_ups", []) or [],
    }


def _match_intent(msg: str, kind: str) -> bool:
    keys = {
        "selection": ("选品", "新品机会", "挖掘新品", "潜力", "蓝海", "推新", "选款", "选品洞察"),
        "email": ("邮件", "客服来信", "处理邮件", "回复邮件", "邮件诉求", "邮件整理", "建档邮件", "邮件摘要"),
        "competitor": ("竞品监控", "监控竞品", "竞品动态", "竞品变化", "竞品追踪", "盯竞品", "跟踪竞品", "竞品预警", "分析竞品"),
    }.get(kind, ())
    return any(k in msg for k in keys)


def exec_run_intent(intent):
    intent.agent_code = "ops_query"
    return intent


def _pick_tables(intent) -> list[str]:
    ts = [t for t in intent.params.get("tables", []) or [] if t not in
          ("document", "knowledge")]
    if ts:
        return ts
    return {
        "operations": ["sales_orders", "products", "competitors"],
        "supply": ["inventory"],
        "ads": ["ad_performance"],
    }.get(intent.scope, ["sales_orders"])


def _render_answer(intent, analyses: list, top_n=None) -> str:
    k = int(top_n) if (top_n and int(top_n) > 0) else 5
    lines = []
    for a in analyses:
        ch = a.get("chart")
        if ch:
            lines.append(
                f"\n### 📊 {ch['table_label']} · 按 {ch['dimension_label']} 分组"
                f"（{len(ch['categories'])} 项）")
            if ch["series"]:
                s0 = ch["series"][0]
                _total = sum(ch["series"][0]["data"])
                lines.append(f"指标 **{s0['name']}** 合计约 **{_total:,.0f}**，前 {k} 名：")
                top = sorted(zip(ch["categories"], s0["data"]),
                             key=lambda kv: kv[1], reverse=True)[:k]
                lines.append("\n".join(f"- {c}：{v:,.0f}" for c, v in top))
        else:
            rows = a.get("rows") or []
            # 原样记录已在下方数据表中完整展示，正文只给行指引，避免重复铺大表
            lines.append(f"\n### {a['table']} · 共 {len(rows)} 条（明细见下方数据表）")
    if not analyses:
        lines.append("\n未识别到可查询的业务表，请补充 SKU / 日期或检查导入的数据。")

    # 数据结论 / 下一步建议 / 追问由前端据 message.data.insight 渲染为独立卡片，正文不再重复
    return "\n".join(lines).strip()


# ══════════════════════════════ 选品洞察（运营子 Agent） ══════════════════════════════
def _selection_insight(intent, task_id: str, message: str) -> dict:
    from datetime import date, timedelta
    top_n = int(intent.params.get("top_n") or 5)
    today = date.today()
    date_to = intent.params.get("date_to") or today.isoformat()
    date_from = intent.params.get("date_from") or (today - timedelta(days=30)).isoformat()

    orders = execute_read("sales_orders", store_id=None, date_from=date_from,
                          date_to=date_to, agent_code="ops_query",
                          task_id=task_id, limit=8000).rows
    ads = execute_read("ad_performance", store_id=None, date_from=date_from,
                       date_to=date_to, agent_code="ops_query",
                       task_id=task_id, limit=5000).rows
    comps = execute_read("competitors", store_id=None,
                         date_from=(today - timedelta(days=2)).isoformat(),
                         date_to=today.isoformat(), agent_code="ops_query",
                         task_id=task_id, limit=6000).rows

    sale_by_sku: dict = {}
    for r in (orders or []):
        s = r.get("sku")
        if not s:
            continue
        d = sale_by_sku.setdefault(s, {"qty": 0, "revenue": 0.0})
        d["qty"] += int(r.get("quantity") or 0)
        d["revenue"] += float(r.get("revenue") or 0)
    ad_by_sku: dict = {}
    for r in (ads or []):
        s = r.get("sku")
        if not s:
            continue
        d = ad_by_sku.setdefault(s, {"spend": 0.0, "sales": 0.0})
        d["spend"] += float(r.get("spend") or 0)
        d["sales"] += float(r.get("sales") or 0)
    comp_by_sku: dict = {}
    for r in (comps or []):
        s = r.get("sku")
        if not s:
            continue
        d = comp_by_sku.setdefault(s, {"n": 0, "oos": 0})
        d["n"] += 1
        if r.get("out_of_stock"):
            d["oos"] += 1

    ranked: list[dict] = []
    for sku, s in sale_by_sku.items():
        ad = ad_by_sku.get(sku) or {}
        cp = comp_by_sku.get(sku) or {}
        acos = (ad["spend"] / ad["sales"]) if ad.get("sales") else 0
        score = s["qty"] + (cp.get("oos", 0) * 2) - (cp.get("n", 0) * 0.3)
        ranked.append({
            "sku": sku, "qty": s["qty"], "revenue": round(s["revenue"], 2),
            "acos": round(acos, 3), "comp_num": cp.get("n", 0),
            "comp_oos": cp.get("oos", 0), "score": round(score, 2),
        })
    ranked.sort(key=lambda x: x["score"], reverse=True)
    top = ranked[:top_n]

    lines = ["### 🎯 选品洞察（近 30 天）"]
    if not top:
        lines.append("\n本周期暂无足够的销售数据做选品判断。")
    else:
        lines.append("\n**潜力候选 SKU（综合销量 / 广告效率 / 竞品竞争度排序）：**")
        for i, r in enumerate(top, 1):
            flags = []
            if r["comp_oos"] > 0:
                flags.append(f"竞品缺货 {r['comp_oos']} 家（机会）")
            if r["comp_num"] == 0:
                flags.append("暂无直接竞品（蓝海）")
            if 0 < r["acos"] <= 0.35:
                flags.append("广告盈利")
            tail = f"（{'、'.join(flags)}）" if flags else ""
            lines.append(f"- **{i}. {r['sku']}**：销量 {r['qty']} · 营收 ${r['revenue']:,.0f}"
                         f" · 竞品 {r['comp_num']} 家{tail}")
        lines.append(f"\n> 建议重点观测前 {len(top)} 名，可结合 Listing 与补货计划落地。")
    answer = "\n".join(lines)
    return {
        "answer": answer,
        "sources": [{"table": "sales_orders", "rows": len(orders or [])},
                    {"table": "competitors", "rows": len(comps or [])},
                    {"table": "ad_performance", "rows": len(ads or [])}],
        "proposed_writes": [],
        "artifact": None if not top else {
            "title": "选品洞察报告", "type": "suggestion", "scope": "operations",
            "agent_code": "ops_query", "content": answer,
            "data": {"ranked": ranked[:int(top_n)], "date_from": date_from,
                     "date_to": date_to},
            "sources": [{"table": "sales_orders", "rows": len(orders or [])},
                        {"table": "competitors", "rows": len(comps or [])}]},
        "cost": 0.0,
        "analyses": [] if not top else [{
            "table": "选品潜力", "table_label": "选品洞察",
            "dimension_label": "SKU",
            "categories": [r["sku"] for r in top],
            "series": [{"name": "潜力分", "data": [r["score"] for r in top]}],
            "suggested": "bar", "types": ["bar", "line"],
        }],
        "insight": {
            "conclusion": (f"识别出 {len(top)} 个潜力 SKU" if top
                           else "暂无足够销售数据做选品判断"),
            "suggestions": ([s["sku"] + "：纳入新品观测并准备 Listing" for s in top][:5]),
        },
        "follow_ups": ["查看竞争度更低的 SKU", "为潜力 SKU 起草 Listing"],
    }


# ══════════════════════════════ 邮件处理（运营子 Agent） ══════════════════════════════
_EMAIL_SKU_RE = re.compile(r"(?i)(SKU[-–]?\d{3,6}|[A-Z]{1,3}[-–]?\d{3,6})")
_EMAIL_REQUEST = (
    ("退款", ("退款", "退钱", "refund")),
    ("退货", ("退货", "return")),
    ("补发", ("补发", "重发", "再寄", "resend")),
    ("换货", ("换货", "exchange")),
    ("改价", ("改价", "降价", "优惠", "打折", "discount", "price")),
    ("差评", ("差评", "负面评价", "差评威胁", "bad review")),
    ("发票", ("发票", "invoice")),
    ("资质", ("资质", "认证", "certificate", "coa", "msds")),
    ("缺货问询", ("缺货", "断货", "有货吗", "stock")),
    ("物流", ("物流", "快递", "到货", "shipping", "tracking")),
)


def _email_processing(intent, task_id: str, message: str) -> dict:
    parsed = _parse_email(message)
    sku = parsed.get("sku")
    product_name = ""
    if sku:
        prows = execute_read("products", store_id=None, sku=sku,
                             agent_code="ops_query", task_id=task_id, limit=5).rows
        if prows:
            product_name = prows[0].get("name") or ""

    req = parsed["request"]
    action = {
        "退款": "核实订单后按平台流程发起退款（写操作需审批）",
        "退货": "确认签收状态，生成退货单",
        "补发": "核查库存后安排补发（写操作需审批）",
        "换货": "核查库存后生成换货单",
        "改价": "评估毛利后提交改价审批",
        "差评": "联系买家安抚并推进解决，避免差评升级",
        "发票": "开具并回传电子发票",
        "资质": "调取并回传对应认证文件",
        "缺货问询": "告知补货到仓时间，可引导关注上架",
        "物流": "查询物流轨迹并告知最新节点",
    }.get(req, "按邮件诉求流转到对应处理人")

    lines = [
        "### 📧 邮件诉求整理",
        f"- **诉求类型**：{req or '待归类'}",
        f"- **建议动作**：{action}",
    ]
    if sku:
        lines.append(f"- **关联 SKU**：{sku}　（{product_name or '未匹配到商品资料'}）")
    if parsed.get("order_no"):
        lines.append(f"- **订单号**：{parsed['order_no']}")
    if parsed.get("urgent"):
        lines.append(f"- **紧迫度**：{parsed['urgent']}")
    answer = "\n".join(lines)
    return {
        "answer": answer,
        "sources": [],
        "proposed_writes": [],
        "artifact": {
            "title": "邮件处理工单", "type": "suggestion", "scope": "operations",
            "agent_code": "ops_query", "content": answer,
            "data": {"email_parse": parsed}, "sources": [],
        },
        "cost": 0.0,
        "analyses": [],
        "insight": {"conclusion": f"邮件已归类为「{req or '一般咨询'}」",
                    "suggestions": [action]},
        "follow_ups": ["查看该 SKU 近期订单", "进入审批处理补发/改价"],
    }


def _parse_email(text: str) -> dict:
    req = "一般咨询"
    for label, kw in _EMAIL_REQUEST:
        if any(k.lower() in (text or "").lower() for k in kw):
            req = label
            break
    m = _EMAIL_SKU_RE.search(text or "")
    sku = re.sub(r"[-–]", "", m.group(1)) if m else ""
    order = re.search(r"(?i)(ord[-–]?\d{5,}|ORD\d{5,})", text or "")
    urgent = "高" if any(k in (text or "").lower()
                         for k in ("urgent", "asap", "尽快", "急需")) else "中"
    return {"request": req, "sku": sku,
            "order_no": (order.group(1).upper() if order else ""), "urgent": urgent}


# ══════════════════════════════ 竞品监控（运营子 Agent） ══════════════════════════════
def _competitor_monitor(intent, task_id: str, message: str) -> dict:
    from datetime import date, timedelta
    import json
    from ..alerts import service as alerts_service
    from ..scheduler import linkage

    today = date.today()
    days = intent.params.get("days") or _days_scope(message or "")
    date_from = intent.params.get("date_from") or (today - timedelta(days=days)).isoformat()
    date_to = intent.params.get("date_to") or today.isoformat()
    comps = execute_read("competitors", store_id=None, date_from=date_from,
                         date_to=date_to, agent_code="ops_query",
                         task_id=task_id, limit=8000).rows

    # 按 SKU 聚合竞品价格首末、缺货、评分
    by_sku: dict = {}
    for r in (comps or []):
        s = r.get("sku")
        if not s:
            continue
        rec = by_sku.setdefault(s, {"first_price": None, "last_price": None,
                                    "n": 0, "oos": 0, "rating_min": None})
        rec["n"] += 1
        try:
            p = float(r.get("price") or 0)
        except (TypeError, ValueError):
            p = 0
        if rec["first_price"] is None:
            rec["first_price"] = p
        rec["last_price"] = p
        if r.get("out_of_stock"):
            rec["oos"] += 1
        rating = r.get("rating")
        if isinstance(rating, (int, float)):
            rec["rating_min"] = rating if rec["rating_min"] is None else min(rec["rating_min"], float(rating))

    signals: list[dict] = []
    for sku, rec in by_sku.items():
        fp = rec["first_price"] or 0
        lp = rec["last_price"] or 0
        if fp > 0 and lp < fp * 0.95:
            signals.append({"type": "price_drop", "severity": "medium",
                            "sku": sku, "msg": f"{sku} 竞品价格由 ${fp:.2f} 降至 ${lp:.2f}，注意价格战"})
        if rec["oos"] > 0:
            signals.append({"type": "competitor_oos", "severity": "low",
                            "sku": sku, "msg": f"{sku} 有 {rec['oos']} 家竞品缺货，具备承接份额的机会"})

    alert_records: list[dict] = []
    chains: list[str] = []
    for sig in signals[:6]:
        at = "price_mutation" if sig["type"] == "price_drop" else "competitor_oos"
        rec = alerts_service.write(
            alert_type=at, scope="operations", store_id="", sku=sig["sku"],
            market="US", severity=sig["severity"], title=sig["msg"],
            message=sig["msg"], evidence={"type": sig["type"]}, source_task=task_id)
        alert_records.append({"alert_id": rec.get("id"), "sku": sig["sku"],
                              "type": sig["type"]})
    price_drop = [s for s in signals if s["type"] == "price_drop"]
    if price_drop:
        root = linkage.publish(
            event_type="price_mutation", target=price_drop[0]["sku"],
            store_id="", origin_agent="ops_query",
            message=f"竞品监控：{len(price_drop)} 个 SKU 检测到竞品降价，发起运营核查",
            evidence=json.dumps(price_drop[:5], ensure_ascii=False),
            suggested_actions=[{"agent": "ops_query", "action": "评估是否需要应对调价"},
                               {"agent": "ads_query", "action": "检查广告是否仍具竞争力"}])
        if root.get("ok"):
            chains.append(root["chain_id"])

    lines = ["### 👀 竞品监控（近 %d 天）" % days]
    if not by_sku:
        lines.append("\n暂无竞品快照数据，无法监控。")
    else:
        lines.append(f"- 📊 共监测 **{len(by_sku)}** 个 SKU 的竞品动态，检出"
                     f" **{len(signals)}** 条信号。")
        for sig in signals[:10]:
            tag = "🔴" if sig["severity"] == "high" else ("🟠" if sig["severity"] == "medium" else "🟢")
            lines.append(f"- {tag} **{sig['sku']}**：{sig['msg']}")
        if not signals:
            lines.append("\n✅ 本周期竞品价格与库存稳定，无异常。")
        lines.append(f"\n> 已落 {len(alert_records)} 条竞品预警记录"
                     f"{'，并发起价格联动核查' if chains else ''}。")
    answer = "\n".join(lines)
    return {
        "answer": answer,
        "sources": [{"table": "competitors", "rows": len(comps or [])}],
        "proposed_writes": [],
        "artifact": None if not by_sku else {
            "title": "竞品监控报告", "type": "report", "scope": "operations",
            "agent_code": "ops_query", "content": answer,
            "data": {"signals": signals[:15], "days": days}, "sources": []},
        "cost": 0.0,
        "analyses": [],
        "insight": {"conclusion": (f"检出 {len(signals)} 条竞品信号" if signals
                                   else "竞品动态平稳"),
                    "suggestions": [s["msg"] for s in signals[:5]]},
        "follow_ups": ["查看全部预警记录", "深挖价格战 SKU 的广告表现"],
        "linkage_chains": chains,
    }


def _days_scope(message: str) -> int:
    for k, n in (("年", 365), ("月", 30), ("周", 7)):
        if k in (message or ""):
            return n
    return 14