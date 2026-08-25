"""广告 Agent（P1）：广告深度分析 + 异常预警 + 降出价联动建议.

行为分流（与 supply.py 对称）：
  + 纯查询/分析 → 复用运营查询分析链路（锁定 ads 作用域）；
  + 异常预警（花费激增/转化骤降/预算耗尽/CTR 异常）→ 扫描广告数据：
      - 预警记录（记录类）直接落库留痕；
      - 花费开销异常的 SKU 提出「降低出价」写操作 → 独立审批；
      - 发起「广告异常」联动 → 运营核查 Listing/竞品 + 供应链查库存。
    由此满足联动矩阵「广告：花费激增/转化骤降 → 运营核查 + 供应链查库存」，
    且写操作（出价调整）独立审批（联动审批隔离 AC-AP-05 / AC-AD-05）。
"""
from __future__ import annotations

import json
from datetime import date

from ..alerts import service as alerts_service
from ..analysis import admonitor
from ..analysis import budget_alloc
from ..scheduler import linkage
from .operations import run as _ops_run
from .toolkit import execute_read

ALERT_KEYS = ("预警", "监控", "异常", "告急", "花费激增", "转化骤降", "预算耗尽",
              "ctr", "花费", "虚高")
ANALYSIS_KEYS = ("分析", "复盘", "对比", "趋势", "acos", "roas", "roi", "转化",
                 "环比", "同比", "汇总", "下钻", "素材", "adgroup", "campaign")
BID_KEYS = ("出价", "调价", "降出价", "降价", "调低")
BUDGET_ALLOC_KEYS = ("预算分配", "预算建议", "调预算", "分配预算", "预算优化", "预算策略", "月度预算")

_MAX_WRITES = 3                       # 一次最多提出出价调整写审批数（防审批风暴）
_ANOMALY_BID_TABLE = {                # 异常类型 → 是否产生降出价写操作
    "spend_surge": True,
    "conversion_drop": True,
    "budget_depleted": True,
}
_ANOMALY_SEVERITY = {
    "spend_surge": "high", "conversion_drop": "high",
    "ctr_abnormal": "medium", "budget_depleted": "medium",
}
_ANOMALY_TITLES = {
    "spend_surge": "广告花费激增", "conversion_drop": "广告转化骤降",
    "ctr_abnormal": "广告 CTR 异常", "budget_depleted": "广告预算将耗尽",
}


def run(intent, task_id: str, message: str = "", history: str = "") -> dict:
    intent.scope = "ads"
    msg = (message or "").lower()
    want_budget = any(k in msg for k in BUDGET_ALLOC_KEYS)
    if want_budget:
        intent.agent_code = "ads_query"
        return _budget_alloc_ops(intent, task_id, message)
    want_alert = intent.work_mode == "alert" or any(k in msg for k in ALERT_KEYS)
    want_analysis = intent.work_mode == "analysis" or any(k in msg for k in ANALYSIS_KEYS)
    want_bid = any(k in msg for k in BID_KEYS)
    if (want_analysis and not want_alert) or not (want_alert or want_bid):
        intent.agent_code = "ads_query"
        return _ops_run(intent, task_id, message, history)

    intent.agent_code = "ads_query"
    return _ads_ops(intent, task_id, message)


def _ads_ops(intent, task_id: str, message: str) -> dict:
    params = intent.params
    sku = params.get("sku")
    store_id = params.get("store_id")
    days = _days_from(intent, message)

    # 1) 深度分析：读取广告数据，聚合 ACOS/ROAS/花费/转化
    perf = execute_read("ad_performance", store_id=store_id or None, sku=sku,
                        agent_code="ads_query", task_id=task_id, limit=2000)
    rows = perf.rows
    aggregate = _aggregate(rows)

    # 2) 异常预警：花费激增/转化骤降/预算耗尽/CTR 异常
    anomalies, _recent = admonitor.detect_anomalies(days=days, store_id=store_id or "",
                                                    sku=sku)
    anomalies = anomalies or []

    writes: list[dict] = []
    alert_records: list[dict] = []
    chains: list[str] = []

    # 3) 落预警记录 & 提出降出价写审批 & 发起联动
    proposed_sks = [a["sku"] for a in anomalies if _ANOMALY_BID_TABLE.get(a["type"])]
    for a in anomalies[:_MAX_WRITES]:
        rec = alerts_service.write(
            alert_type=a["type"], scope="ads", store_id=store_id or "",
            sku=a["sku"], market="US", severity=_ANOMALY_SEVERITY.get(a["type"], "medium"),
            title=a.get("title") or _ANOMALY_TITLES.get(a["type"], "广告异常"),
            message=a["message"], evidence=_evidence_for(a), source_task=task_id)
        alert_records.append({"alert_id": rec.get("id"), "sku": a["sku"],
                              "type": a["type"], "severity": a.get("severity")})
        if a["sku"] in proposed_sks:
            bid_w = admonitor.propose_bid_action(
                sku=a["sku"], store_id=store_id or "", market="US",
                evidence=f"广告异常联动：{a['message']}", source_task=task_id)
            if bid_w:
                writes.append(bid_w)

    # 4) 联动事件（广告异常 → 运营核查 Listing/竞品 + 供应链查库存）
    if anomalies:
        root = linkage.publish(
            event_type=anomalies[0]["type"], target=anomalies[0]["sku"],
            store_id=store_id or "", origin_agent="ads_query",
            message=(f"检测到 {len(anomalies)} 个广告异常，发起联动核查："
                     f"{_sku_preview(anomalies)}"),
            evidence=json.dumps(_evidence_summary(anomalies), ensure_ascii=False),
            suggested_actions=[{"agent": "ops_query", "action": "核查 Listing/竞品"},
                               {"agent": "supply_query", "action": "检查库存是否断货影响转化"}])
        parent = root.get("event", {}).get("id") if root.get("ok") else ""
        if parent:
            for a in anomalies:
                sub = linkage.publish(
                    event_type=f"check_{a['type']}_{a['sku']}", target=a["sku"],
                    store_id=store_id or "", origin_agent="ops_query",
                    parent_event_id=parent, mode="auto",
                    message=f"联动核查：{a['title']}（{a['sku']}）",
                    evidence=json.dumps(a, ensure_ascii=False))
                if sub.get("ok"):
                    chains.append(sub["chain_id"])
                if a["sku"] in proposed_sks:
                    sub2 = linkage.publish(
                        event_type=f"stock_check_{a['sku']}", target=a["sku"],
                        store_id=store_id or "", origin_agent="supply_query",
                        parent_event_id=parent, mode="auto",
                        message=f"联动核查库存是否断货影响转化：{a['sku']}")
                    if sub2.get("ok"):
                        chains.append(sub2["chain_id"])

    answer, artifact = _render(intent, message, aggregate, rows, anomalies,
                               writes, alert_records)
    return {
        "answer": answer,
        "sources": [{"table": "ad_performance", "rows": len(rows)}],
        "proposed_writes": _dedupe_writes(writes),
        "artifact": artifact,
        "cost": 0.0,
        "analyses": [{"table": "ad_performance", "rows": rows,
                      "chart": _build_chart(aggregate)}],
        "insight": _insight(anomalies, writes, aggregate),
        "follow_ups": ["查看全部广告异常", "预览待审批的降出价建议",
                       "深挖转化骤降 SKU 的 Listing 表现", "查看预警记录"],
        "linkage_chains": chains,
    }


def _budget_alloc_ops(intent, task_id: str, message: str) -> dict:
    """预算分配与出价调整建议（P2）：基于历史 ROI 给出分配策略."""
    params = intent.params
    store_id = params.get("store_id", "")
    total_budget = params.get("budget")
    if total_budget:
        total_budget = float(total_budget)
    result = budget_alloc.allocate_budget(
        total_budget=total_budget, store_id=store_id, period="monthly")
    answer, artifact = _render_budget_alloc(result, message)
    return {
        "answer": answer,
        "sources": [{"table": "ad_performance", "rows": len(result.get("allocations", []))}],
        "proposed_writes": result.get("writes", []),
        "artifact": artifact,
        "cost": 0.0,
        "analyses": [],
        "insight": {
            "conclusion": (f"预算分配完成，推荐主投 {result['recommendation']['top_sku']}，"
                           f"预期综合 ROAS {result['recommendation']['total_expected_roas']}")
            if result.get("recommendation") else "暂无足够数据完成预算分配",
            "suggestions": [f"确认 {len(result['writes'])} 项预算调整并审批"]
            if result.get("writes") else ["导入更多广告数据后再生成分配建议"],
        },
        "follow_ups": ["预览待审批的预算调整", "按广告组查看分配详情",
                       "调整总预算后重新分配"],
    }


def _render_budget_alloc(result, message) -> tuple[str, dict | None]:
    lines = []
    if not result.get("allocations"):
        lines.append("暂无广告数据，无法生成预算分配建议。请先导入广告数据与预算设置。")
        return "\n".join(lines), None
    rec = result["recommendation"]
    lines.append("### 预算分配与出价调整建议")
    lines.append(f"- 预算周期：**{result['period']}** | 可用预算总额：**${result['total_budget']:,.0f}**")
    lines.append(f"- 历史投放总额：**${result['total_historical_spend']:,.0f}**")
    if rec:
        lines.append(f"- 推荐主投 SKU：**{rec['top_sku']}**（分配 ${rec['top_budget']:,.0f}）")
        lines.append(f"- 预期综合 ROAS：**{rec['total_expected_roas']}**")
        lines.append(f"- 高风险 SKU 数：**{rec['risk_count']}** 个")
    lines.append("")
    for a in result["allocations"]:
        risk_tag = {"high": "🔴 高风险", "medium": "🟠 中风险", "low": "✅"}.get(a["risk"], "")
        lines.append(
            f"- **{a['sku']}**（{a['campaign'] or '通用'}）{risk_tag}："
            f"建议预算 **${a['recommended_budget']:,.0f}** | "
            f"历史 ROAS {a['historical_roas']} | 权重 {a['weight']:.1%}")
        if a.get("risk_reasons"):
            for rr in a["risk_reasons"]:
                lines.append(f"  - ⚠️ {rr}")
    if result.get("writes"):
        lines.append(f"\n本次提出 **{len(result['writes'])}** 项预算调整写操作待审批，"
                     f"审批后落库生效。")
        lines.append("\n> ⚠️ 预算调整均为写操作，需你逐条审批后才落库。")
    return "\n".join(lines), {
        "title": "广告预算分配策略报告",
        "type": "strategy", "scope": "ads", "agent_code": "ads_query",
        "content": "\n".join(lines),
        "data": {k: v for k, v in result.items() if k in (
            "allocations", "recommendation", "total_budget", "period")},
        "sources": [{"table": "ad_performance", "rows": len(result["allocations"])}],
    }


def _aggregate(rows: list[dict]) -> dict:
    spend = sales = clicks = imps = orders = 0.0
    for r in rows or []:
        spend += float(r.get("spend") or 0)
        sales += float(r.get("sales") or 0)
        clicks += float(r.get("clicks") or 0)
        imps += float(r.get("impressions") or 0)
        orders += float(r.get("orders") or 0)
    return {
        "spend": spend, "sales": sales, "clicks": int(clicks),
        "impressions": int(imps), "orders": int(orders),
        "ctr": clicks / imps if imps else 0,
        "cpc": spend / clicks if clicks else 0,
        "acos": spend / sales if sales else 0,
        "roas": sales / spend if spend else 0,
        "records": len(rows or []),
    }


def _days_from(intent, message: str) -> int:
    for k in ("周", "星期"):
        if k in message:
            return 7
    if "月" in message:
        return 30
    if "年" in message:
        return 365
    from ..scheduler.intents import parse_relative_dates
    df, _dt = parse_relative_dates(message or "")
    if df:
        try:
            d0 = date.fromisoformat(df)
            return max(1, (date.today() - d0).days)
        except ValueError:
            pass
    return 7


def _evidence_for(a: dict) -> dict:
    return {"message": a.get("message"), "type": a.get("type"),
            "severity": a.get("severity")}


_EVIDENCE_PREVIEW_N = 30      # 写入联动证据的异常明细上限（防 evidence 字段溢出）


def _evidence_summary(anomalies: list) -> dict:
    """联动根事件的 evidence 用汇总而非全量明细，避免 1406 Data too long."""
    return {
        "total": len(anomalies),
        "count_by_type": _count_by_type(anomalies),
        "anomalies": [_evidence_for(a) for a in anomalies[:_EVIDENCE_PREVIEW_N]],
    }


def _count_by_type(anomalies: list) -> dict:
    out: dict = {}
    for a in anomalies or []:
        out[a.get("type")] = out.get(a.get("type"), 0) + 1
    return out


def _sku_preview(anomalies: list) -> str:
    skus = [str(a.get("sku")) for a in anomalies if a.get("sku")]
    head = ", ".join(skus[:_EVIDENCE_PREVIEW_N])
    return f"{head} 等 {len(skus)} 个" if len(skus) > _EVIDENCE_PREVIEW_N else ", ".join(skus)


def _render(intent, message, agg, rows, anomalies, writes, alert_records) -> tuple[str, dict | None]:
    lines = []
    if not rows:
        lines.append("本区间暂无广告投放数据，未能完成分析与预警。请检查是否已导入广告数据。")
        return "\n".join(lines), None
    lines.append("### 📢 广告投放分析（近 7 天）")
    if agg["records"]:
        lines.append(
            f"- 💰 投放花费 **${agg['spend']:,.0f}**，带来销售额 **${agg['sales']:,.0f}**，"
            f"ROAS **{agg['roas']:.2f}** / ACOS **{agg['acos'] * 100:.1f}%**")
        lines.append(
            f"- 🖱️ 曝光 {agg['impressions']:,} · 点击 {agg['clicks']:,} · "
            f"CTR {agg['ctr'] * 100:.2f}% · CPC ${agg['cpc']:.2f} · 出单 {agg['orders']} 单")
    if anomalies:
        lines.append("\n**⚠️ 异常预警：**")
        shown = anomalies[:_EVIDENCE_PREVIEW_N]
        for a in shown:
            tag = {"high": "🔴", "medium": "🟠", "low": "🟡"}.get(a.get("severity"), "🟠")
            lines.append(f"- {tag} **{a.get('title', a['type'])}**（{a['sku']}）：{a['message']}")
        if len(anomalies) > len(shown):
            lines.append(f"- … 另有 {len(anomalies) - len(shown)} 条同类异常，共 {len(anomalies)} 条（详见预警记录）。")
        lines.append(f"- 本次提出 **{len(writes)}** 项降出价写操作待审批、"
                     f"**{len(alert_records)}** 条预警已落库，并发起 Agent 联动（运营核查 + 供应链查库存）。")
        lines.append("\n> ⚠️ 出价调整为写操作，需你逐条审批后才落库（联动审批隔离）。")
    else:
        lines.append("\n✅ 未发现明显广告异常。")
    return "\n".join(lines), {
        "title": "广告投放分析与异常预警报告",
        "type": "report", "scope": "ads", "agent_code": "ads_query",
        "content": "\n".join(lines),
        "data": {"aggregate": agg, "anomalies": anomalies,
                 "message": message[:200]},
        "sources": [{"table": "ad_performance", "rows": len(rows)}],
    }


def _insight(anomalies, writes, agg) -> dict:
    n = len(anomalies)
    if n:
        conclusion = f"存在 {n} 个广告异常，已落预警并联动运营/供应链核查"
    elif agg["records"]:
        conclusion = (f"广告投放整体健康：ROAS {agg['roas']:.1f}，本次未发现明显异常")
    else:
        conclusion = "无足够广告数据"
    suggestions = [f"{w['table']}：{w['reason'][:40]}" for w in writes][:5]
    if not suggestions and n:
        suggestions = ["核查异常 SKU 的 Listing 与竞品表现",
                       "检查供应链库存是否断货影响转化"]
    return {"conclusion": conclusion, "suggestions": suggestions}


def _build_chart(agg: dict):
    if not agg["records"]:
        return None
    return {
        "table": "ad_performance", "table_label": "广告投放",
        "dimension_label": "指标",
        "categories": ["花费 $", "销售额 $", "CTR %", "ACOS %", "ROAS"],
        "series": [{"name": "数值", "data": [
            round(agg["spend"]), round(agg["sales"]),
            round(agg["ctr"] * 100, 2), round(agg["acos"] * 100, 2), round(agg["roas"], 2)]}],
        "suggested": "bar",
        "types": ["bar", "line", "pie"],   # 5 项单维度指标，支持柱/折/饼切换
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