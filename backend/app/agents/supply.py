"""供应链 Agent（P1）：库存/物流查询 + 补货建议 + 库存预警 + Agent 联动.

行为分流：
  + 纯查询 → 复用运营查询分析链路（锁定 supply 作用域）；
  + 补货/缺货/预警 → 读取库存，计算补货量与缺货风险：
      - 预警记录（记录类）直接落库留痕；
      - 补货计划（写操作）→ 独立审批；
      - 触发「库存告急」联动 → 广告 Agent 降低该 SKU 出价（写操作 → 独立审批）。
    由此满足 AC-AD-05（三路响应并行且各写操作分别生成审批任务）与
    联动审批隔离（AC-AP-05）。
"""
from __future__ import annotations

import json

from ..alerts import service as alerts_service
from ..analysis import supply_calc
from ..analysis import admonitor
from ..analysis import procurement as procurement_analysis
from ..scheduler import linkage
from .operations import run as _ops_run
from .toolkit import execute_read

REPLENISH_KEYS = ("补货", "建议进", "补库存", "备货")
PROCUREMENT_KEYS = ("采购", "比价", "询价", "供应商", "报价", "采购比价")
ALERT_KEYS = ("预警", "告急", "缺货", "库存告急", "断货", "监控")

_MAX_WRITES = 3   # 一次最多提出补货计划/出价调整写审批数（防止审批风暴）


def run(intent, task_id: str, message: str = "", history: str = "") -> dict:
    intent.scope = "supply"
    msg = (message or "").lower()
    want_alert = intent.work_mode == "alert" or any(k in msg for k in ALERT_KEYS)
    want_replenish = want_alert or any(k in msg for k in REPLENISH_KEYS)
    want_procurement = any(k in msg for k in PROCUREMENT_KEYS)
    if want_procurement and not want_alert:
        intent.agent_code = "supply_query"
        return _procurement_ops(intent, task_id, message)
    if want_replenish or want_alert:
        intent.agent_code = "supply_query"
        return _supply_ops(intent, task_id, message)
    intent.agent_code = "supply_query"
    return _ops_run(intent, task_id, message, history)


def _supply_ops(intent, task_id: str, message: str) -> dict:
    params = intent.params
    sku = params.get("sku")
    res = execute_read("inventory", sku=sku, agent_code="supply_query",
                       task_id=task_id, limit=100)
    rows = res.rows
    plans = supply_calc.calc_replenishment(rows)
    shortages = _dedupe_by_sku([
        p for p in plans if p["shortage_risk"] in ("high", "medium")
        and p["suggested_qty"] > 0])[:_MAX_WRITES]

    writes: list[dict] = []
    alert_records: list[dict] = []
    chains: list[str] = []

    for p in shortages:
        alert_records.append(_emit_alert(p, task_id))
        writes.append(_replenish_write(p, task_id))
        bid_w = admonitor.propose_bid_action(
            sku=p["sku"], store_id=p["store_id"], market=p["market"],
            evidence=f"库存告急联动：{p['sku']} 可售 {p['available']} / 安全库存 {p['safety_stock']}",
            source_task=task_id)
        if bid_w:
            writes.append(bid_w)

    # 联动事件：根事件 + 每 SKU 响应子事件（补货 & 广告降出价）
    if shortages:
        root = linkage.publish(
            event_type="inventory_shortage", target=shortages[0]["sku"],
            store_id=shortages[0]["store_id"],
            origin_agent="supply_query",
            message=(f"检测到 {len(shortages)} 个 SKU 库存告急，发起联动："
                     f"{', '.join(p['sku'] for p in shortages)}"),
            evidence=json.dumps([{ "sku": p["sku"], "available": p["available"],
                                   "safety_stock": p["safety_stock"] } for p in shortages],
                                ensure_ascii=False),
            suggested_actions=[{"agent": "supply_query", "action": "生成补货计划"},
                               {"agent": "ads_query", "action": "降低出价建议"}])
        parent = root.get("event", {}).get("id") if root.get("ok") else ""
        for p in shortages:
            for svc, a_type, label in (("supply_query", "补货建议", "生成补货计划"),
                                       ("ads_query", "广告降出价", "降低该SKU广告出价（审批）")):
                sub = linkage.publish(
                    event_type=f"{'replenish_' + str(p['sku'])}" if svc == "supply_query"
                    else f"bid_reduce_{p['sku']}",
                    target=p["sku"], store_id=p["store_id"], origin_agent=svc,
                    parent_event_id=parent, mode="auto",
                    message=f"{label}：{p['sku']}（可售 {p['available']}）",
                    evidence=json.dumps(p, ensure_ascii=False))
                if sub.get("ok"):
                    chains.append(sub["chain_id"])

    answer, artifact = _render(intent, plans, shortages, message, writes, alert_records)
    return {
        "answer": answer,
        "sources": [{"table": "inventory", "rows": len(rows)}],
        "proposed_writes": _dedupe_writes(writes),
        "artifact": artifact,
        "cost": 0.0,
        "analyses": [{"table": "inventory", "rows": rows,
                      "chart": _build_chart(plans)}],
        "insight": _insight(plans, shortages, writes),
        "follow_ups": ["查看全部库存水位", "预览待审批的补货计划",
                       "生成广告降出价审批", "查看预警记录"],
        "linkage_chains": chains,
    }


def _emit_alert(p: dict, task_id: str) -> dict:
    return alerts_service.write(
        alert_type="inventory_shortage", scope="supply",
        store_id=p["store_id"], sku=p["sku"], market=p["market"],
        severity="high" if p["shortage_risk"] == "high" else "medium",
        title=f"库存告急：{p['sku']}",
        message=(f"{p['sku']} 可售 {p['available']} 件，安全库存 {p['safety_stock']}，"
                 f"预计可用 {p['days_of_supply']} 天，建议补货 {p['suggested_qty']} 件"),
        evidence={k: p.get(k) for k in ("available", "in_transit", "safety_stock",
                                        "avg_daily_sales", "days_of_supply", "suggested_qty")},
        source_task=task_id)


def _replenish_write(p: dict, task_id: str) -> dict:
    return {
        "table": "replenishment_plans",
        "record_key": f"{p['sku']}:{p['warehouse'] or 'DEFAULT'}",
        "record": {
            "store_id": p["store_id"], "sku": p["sku"], "market": p["market"],
            "warehouse": p["warehouse"],
            "plan_date": _today_iso(),
            "suggested_qty": p["suggested_qty"],
            "suggested_arrival": p["suggested_arrival"],
            "days_of_supply": p["days_of_supply"],
            "avg_daily_sales": p["avg_daily_sales"],
            "available": p["available"], "in_transit": p["in_transit"],
            "safety_stock": p["safety_stock"], "lead_days": p["lead_days"],
            "shortage_risk": p["shortage_risk"],
            "assumptions": {"target_days": 30,
                            "lead_days": p["lead_days"],
                            "avg_days": p["avg_daily_sales"]},
            "status": "draft", "source_task": task_id,
        },
        "reason": (f"{p['sku']} 库存告急（{p['shortage_risk']}）：可售 {p['available']} < "
                   f"安全库存建议线 {int(p['safety_stock'] * 1.2)}"),
        "evidence": f"近30天日均销 {p['avg_daily_sales']}，在途 {p['in_transit']}，采购在途 {p['lead_days']} 天",
    }


def _procurement_ops(intent, task_id: str, message: str) -> dict:
    """采购比价（P2）：按 SKU 聚合供应商报价，输出比价表与推荐."""
    params = intent.params
    sku = params.get("sku")
    store_id = params.get("store_id")

    result = procurement_analysis.compare_prices(
        sku=sku, store_id=store_id, market=params.get("market", "US"))

    comparisons = result.get("comparisons", [])
    recommendation = result.get("recommendation")
    answer, artifact = _render_procurement(comparisons, recommendation, message)
    return {
        "answer": answer,
        "sources": [{"table": "inquiries", "rows": sum(len(c["comparisons"]) for c in comparisons)},
                     {"table": "suppliers", "rows": len(comparisons)}],
        "proposed_writes": [],
        "artifact": artifact,
        "cost": 0.0,
        "analyses": [],
        "insight": {
            "conclusion": recommendation["supplier_name"] if recommendation else "暂无比价数据",
            "suggestions": [f"推荐供应商：{recommendation['supplier_name']}（TCO ${recommendation['tco']}）"]
            if recommendation else ["请先导入供应商和询价数据"],
        },
        "follow_ups": ["查看全部供应商报价", "对比其他 SKU 采购价格",
                       "按供应商筛选比价结果"],
    }


def _render_procurement(comparisons, recommendation, message) -> tuple[str, dict | None]:
    lines = []
    if not comparisons:
        lines.append("暂无询价数据，无法完成比价。请先导入供应商和询价数据。")
        return "\n".join(lines), None
    lines.append("### 采购比价分析")
    total_skus = len(comparisons)
    total_quotes = sum(len(c["comparisons"]) for c in comparisons)
    lines.append(f"- 共比对 **{total_skus}** 个 SKU，**{total_quotes}** 条报价")
    if recommendation:
        lines.append(f"- 综合推荐：**{recommendation['supplier_name']}**（TCO "
                     f"**${recommendation['tco']}**，综合评分 **{recommendation['score']}**）")
        lines.append(f"- 推荐理由：{recommendation['reason']}")
    lines.append("")
    for c in comparisons:
        lines.append(f"**{c['sku']}** 比价表：")
        for e in c["comparisons"]:
            is_best = recommendation and e["supplier_name"] == recommendation["supplier_name"]
            tag = " ⭐ 推荐" if is_best else ""
            lines.append(
                f"  - {e['supplier_name']}{tag}：单价 ${e['unit_price']} | "
                f"TCO ${e['tco']} | 交期 {e['lead_days']}天 | "
                f"质量 {e['quality_rating']} | 评分 {e['score']}")
        if c.get("recommendation"):
            lines.append(f"  → 推荐：{c['recommendation']['supplier_name']}（评分 {c['recommendation']['score']}）")
        lines.append("")
    lines.append("\n> 比价结果基于已导入的供应商与询价数据，仅供参考。具体采购决策请结合实际确认。")
    return "\n".join(lines), {
        "title": "采购比价分析报告",
        "type": "report", "scope": "supply", "agent_code": "supply_query",
        "content": "\n".join(lines),
        "data": {"comparisons": comparisons, "recommendation": recommendation,
                 "message": message[:200]},
        "sources": [{"table": "inquiries", "rows": total_quotes}],
    }


def _dedupe_writes(writes: list) -> list:
    seen, out = set(), []
    for w in writes or []:
        key = (w["table"], w.get("record_key", ""))
        if key in seen:
            continue
        seen.add(key)
        out.append(w)
    return out


def _dedupe_by_sku(plans: list) -> list:
    seen, out = set(), []
    for p in plans:
        s = p.get("sku")
        if s in seen:
            continue
        seen.add(s)
        out.append(p)
    return out


def _render(intent, plans, shortages, message, writes, alert_records) -> tuple[str, dict | None]:
    lines = []
    if not plans:
        lines.append("本仓库暂无库存记录，未能生成补货建议。请检查是否已导入库存数据。")
        return "\n".join(lines), None
    risk = {"high": [], "medium": [], "low": []}
    for p in plans:
        risk.setdefault(p["shortage_risk"], []).append(p["sku"])
    lines.append(f"### 🧮 供应链补货分析")
    lines.append("- 📦 共核查 **{0}** 条库存（按近30天日均销测算）".format(len(plans)))
    if risk.get("high"):
        lines.append(f"- 🔴 **高危缺货**：{', '.join(risk['high'])}")
    if risk.get("medium"):
        lines.append(f"- 🟠 **中危**：{', '.join(risk['medium'])}")
    lines.append(f"- 📊 本次建议提交 **{len(writes)}** 项写操作待审批，其中"
                 f" **{len(alert_records)}** 条预警记录已落库"
                 f"{'，并触发 Agent 联动（广告降出价建议）' if any(w['table'] == 'ad_budgets' for w in writes) else ''}。")
    if shortages:
        lines.append("\n**高危/中危 SKU 补货建议：**")
        for p in shortages:
            lines.append(
                f"- {p['sku']}：建议补货 **{p['suggested_qty']}** 件，预计到货 {p['suggested_arrival']}，"
                f"当前可售 {p['available']} 件（{p['days_of_supply']}天）")
        lines.append("\n> 补货计划与广告出价调整均为**写操作**，需你逐条审批后才会落库（联动审批隔离）。")
    else:
        lines.append("\n✅ 暂无缺货风险，无需补货。")
    return "\n".join(lines), {
        "title": "供应链补货与库存风险报告",
        "type": "report", "scope": "supply", "agent_code": "supply_query",
        "content": "\n".join(lines),
        "data": {"plans": plans, "shortages": shortages,
                 "message": message[:200]},
        "sources": [{"table": "inventory", "rows": len(plans)}],
    }


def _insight(plans, shortages, writes) -> dict:
    n_short = len(shortages)
    conclusion = (f"存在 {n_short} 个 SKU 缺货/缺货风险，已发起联动" if shortages
                  else "库存充足，暂无缺货风险")
    suggestions = [f"{w['table']}：{w['reason'][:40]}" for w in writes][:5]
    if not suggestions and shortages:
        suggestions = ["为缺货 SKU 生成补货计划并审批"]
    return {"conclusion": conclusion, "suggestions": suggestions}


def _build_chart(plans):
    return {
        "table": "replenishment_plans", "table_label": "补货计划",
        "dimension_label": "SKU",
        "categories": [p["sku"] for p in plans],
        "series": [{"name": "建议补货量", "data": [p["suggested_qty"] for p in plans]}],
        "suggested": "bar",
        "types": ["bar", "line"],      # 维度多为 SKU（>10 类），不提供饼图
    }


def _today_iso() -> str:
    from datetime import date
    return date.today().isoformat()