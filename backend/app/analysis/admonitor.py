"""广告监控计算：异常识别（P1）+ 出价调整建议（写操作，走审批流）."""
from __future__ import annotations

from datetime import date

from ..database import session
from ..models import business as bm

# 异常阈值（可后续放入配置）
SPEND_SURGE_RATIO = 3.0        # 单日花费相对区间日均 ≥3 倍 → 花费激增
CONVERSION_DROP_RATIO = 0.5    # 转化相对 7 天均值 ≤50% → 转化骤降
CTR_LOW = 0.0015               # 点击率低于阈值 → CTR 异常
BUDGET_DEPLETED_RATIO = 0.9    # 花费已达月度预算 90% → 预算将耗尽


def detect_anomalies(days: int = 7, store_id: str = "",
                     sku: str | None = None) -> tuple[list[dict], list[dict]]:
    """扫描最近 days 天的广告数据，返回 (anomalies, recent_rows).

    anomaly: {sku, store_id, market, type, severity, title, message, evidence}
    这里的识别结果由广告 Agent 落为预警记录并触发联动。
    """
    from sqlalchemy import select, func
    from ..data import access
    rows = access.query_table(
        "ad_performance", store_id=store_id or None, sku=sku,
        limit=2000)
    return _detect_from_rows(rows, days)


def _detect_from_rows(rows: list[dict], days: int = 7) -> tuple[list[dict], list[dict]]:
    from collections import defaultdict
    today = date.today()
    anomalies: list[dict] = []
    # 按 SKU 聚合统计
    by_sku: dict[str, dict] = {}
    for r in rows or []:
        s = r.get("sku", "")
        by_sku.setdefault(s, {"spend": 0, "sales": 0, "clicks": 0, "impressions": 0,
                              "orders": 0, "daily": 0, "budget": None,
                              "rows": []})
        g = by_sku[s]
        g["rows"].append(r)
        stat_date = str(r.get("stat_date") or "1970-01-01")[:10]
        is_today = stat_date == today.isoformat()
        if is_today:
            g["today_spend"] = g.get("today_spend", 0) + float(r.get("spend") or 0)
            g["today_orders"] = g.get("today_orders", 0) + int(r.get("orders") or 0)
        g["spend"] += float(r.get("spend") or 0)
        g["sales"] += float(r.get("sales") or 0)
        g["clicks"] += int(r.get("clicks") or 0)
        g["impressions"] += int(r.get("impressions") or 0)
        g["orders"] += int(r.get("orders") or 0)
        g["daily"] += 1

    for s, g in by_sku.items():
        g["rows"].sort(key=lambda x: str(x.get("stat_date") or ""))
        curve = [float(r.get("spend") or 0) for r in g["rows"][-days:]]
        spend_daily_mean = (sum(curve) / len(curve)) if curve else 0
        orders_curve = [int(r.get("orders") or 0) for r in g["rows"][-days:]]
        orders_mean = (sum(orders_curve) / len(orders_curve)) if orders_curve else 0
        impressions = g["impressions"]
        clicks = g["clicks"]
        ctr = clicks / impressions if impressions else 0
        spend = g["spend"]
        todays = g.get("today_spend") or 0
        today_orders = g.get("today_orders") or 0

        # 1) 花费激增：今日花费显著高于日均
        if todays > 0 and spend_daily_mean > 0 and todays >= spend_daily_mean * SPEND_SURGE_RATIO:
            anomalies.append(_mk("spend_surge", s, "high",
                                 f"广告花费激增：今日 ${todays:,.0f} 为区间日均 ${spend_daily_mean:,.0f} 的 "
                                 f"{todays / spend_daily_mean:.1f} 倍"))
        # 2) 转化骤降：今日订单显著低于日均
        if orders_mean > 1 and today_orders <= orders_mean * CONVERSION_DROP_RATIO:
            anomalies.append(_mk("conversion_drop", s, "high",
                                 f"转化骤降：今日 {today_orders} 单，近期日均 {orders_mean:,.0f} 单"))
        # 3) CTR 异常偏低（曝光高但点击少）
        if impressions >= 2000 and ctr < CTR_LOW:
            anomalies.append(_mk("ctr_abnormal", s, "medium",
                                 f"CTR 异常偏低：{ctr * 100:.2f}%（曝光 {impressions:,}，点击 {clicks:,}）"))
        # 4) 预算将耗尽：相对该 SKU 月度预算
        budget = _budget_for_sku(s, g["rows"])
        if budget and budget > 0 and spend >= budget * BUDGET_DEPLETED_RATIO:
            anomalies.append(_mk("budget_depleted", s, "medium",
                                 f"预算将耗尽：已花费 ${spend:,.0f} / 月预算 ${budget:,.0f}"))

    recent_rows = rows[-days:]
    return anomalies, recent_rows


def _mk(alert_type, sku, severity, message):
    return {
        "type": alert_type, "sku": sku, "severity": severity,
        "message": message,
        "title": _TITLES.get(alert_type, "广告异常"),
    }


_TITLES = {
    "spend_surge": "广告花费激增",
    "conversion_drop": "广告转化骤降",
    "ctr_abnormal": "广告 CTR 异常",
    "budget_depleted": "广告预算将耗尽",
}


def _budget_for_sku(sku: str, rows: list[dict]) -> float | None:
    store_id = next((r.get("store_id") for r in rows if r.get("store_id")), "")
    market = next((r.get("market") for r in rows if r.get("market")), "US")
    try:
        from sqlalchemy import select
        with session() as db:
            row = db.execute(
                select(bm.AdBudget).where(bm.AdBudget.sku == sku).limit(1)
            ).scalars().first()
        return float(row.monthly_budget or 0) if row else None
    except Exception:  # noqa: BLE001
        return None


def propose_bid_action(*, sku: str, store_id: str = "", market: str = "US",
                       action: str = "reduce", ratio: float = 0.80,
                       evidence: str = "", source_task: str = "") -> dict | None:
    """为广告预算表提出一次出价调整（写操作），返回 proposed_write 供审批.

    这是「数据库唯一交互对象」的标准写操作示例：不连接广告平台，仅更新本系统内
    广告预算表 bid 字段，进入审批流后落库。
    """
    from sqlalchemy import select
    with session() as db:
        row = db.execute(
            select(bm.AdBudget).where(bm.AdBudget.sku == sku)
        ).scalars().first()
        if row is None:
            return None
        old_bid = float(row.bid or 0)
        if old_bid <= 0:
            return None
        new_bid = round(old_bid * ratio, 2)
        rec = {
            "id": row.id, "store_id": row.store_id, "sku": row.sku,
            "market": row.market, "platform": row.platform,
            "budget_period": row.period, "budget_type": row.budget_type,
            "currency": row.currency, "bid": new_bid,
            "daily_budget": row.daily_budget, "monthly_budget": row.monthly_budget,
            "spent": row.spent, "target_acos": row.target_acos, "status": row.status,
        }
        store_id = store_id or row.store_id
        market = market or row.market
    return {
        "table": "ad_budgets",
        "record_key": f"{sku}:{rec['budget_period']}",
        "record": rec,
        "reason": (f"处于库存告急/缺货风险联动，为减缓出货速度降低该 SKU 出价 "
                   f"(¥{old_bid:.2f} → ¥{new_bid:.2f})"),
        "evidence": evidence or f"广告预算表 {sku} 出价调整建议",
        "changes": {"bid": [old_bid, new_bid]},
    }