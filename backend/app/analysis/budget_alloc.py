"""预算分配与出价调整策略（P2）：基于历史 ROI 与预算约束，给出主动式分配建议.

区别于 admonitor 的被动式异常降出价，本模块提供：
  + 按 SKU / 广告组聚合历史 ROI，计算最优预算分配比例；
  + 月度/季度预算分配建议，含预期 ROI 区间与风险提示；
  + 写操作产出为「更新 ad_budgets 表」的审批提案。
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select, func as sa_func

from ..database import session
from ..models import business as bm


def allocate_budget(*, total_budget: float | None = None,
                    store_id: str | None = None,
                    period: str = "monthly") -> dict:
    """基于历史 ROI 给出预算分配建议.

    Returns:
        {period, total_budget, allocations: [{sku, campaign, historical_roas,
          recommended_budget, expected_roi, weight, risk}],
         writes: [{table, record_key, record, reason, evidence, changes}]}
    """
    from collections import defaultdict

    # 1) 读取广告表现数据，按 SKU + 广告组聚合
    with session() as db:
        rows = db.execute(
            select(
                bm.AdPerformance.sku,
                bm.AdPerformance.campaign,
                sa_func.coalesce(sa_func.sum(bm.AdPerformance.spend), 0),
                sa_func.coalesce(sa_func.sum(bm.AdPerformance.sales), 0),
                sa_func.coalesce(sa_func.sum(bm.AdPerformance.orders), 0),
                sa_func.coalesce(sa_func.sum(bm.AdPerformance.clicks), 0),
                sa_func.coalesce(sa_func.sum(bm.AdPerformance.impressions), 0),
            ).where(
                (bm.AdPerformance.store_id == store_id) if store_id else True
            ).group_by(bm.AdPerformance.sku, bm.AdPerformance.campaign)
        ).all()

    if not rows:
        return {"allocations": [], "writes": [], "message": "暂无广告数据，无法生成预算分配建议"}

    # 2) 计算每个 SKU×Campaign 的 ROI
    sku_roi: dict[str, dict] = {}
    for r in rows:
        sku, campaign = r[0], r[1]
        spend = float(r[2] or 0)
        sales = float(r[3] or 0)
        orders = int(r[4] or 0)
        roas = sales / spend if spend > 0 else 0
        key = f"{sku}|{campaign}"
        sku_roi[key] = {
            "sku": sku, "campaign": campaign,
            "historical_spend": round(spend, 2),
            "historical_sales": round(sales, 2),
            "historical_orders": orders,
            "historical_roas": round(roas, 3),
        }

    # 3) 读取预算表
    with session() as db:
        budget_rows = db.execute(
            select(bm.AdBudget).where(
                (bm.AdBudget.store_id == store_id) if store_id else True
            )
        ).scalars().all()

    budget_map = {}
    for b in budget_rows:
        key = f"{b.sku}|{b.campaign}"
        budget_map[key] = {
            "id": b.id, "store_id": b.store_id, "market": b.market,
            "bid": float(b.bid or 0),
            "daily_budget": float(b.daily_budget or 0),
            "monthly_budget": float(b.monthly_budget or 0),
            "spent": float(b.spent or 0),
            "target_acos": float(b.target_acos or 0.3),
            "status": b.status,
        }

    # 4) 计算预算分配权重
    total_spend = sum(v["historical_spend"] for v in sku_roi.values())
    total_sales = sum(v["historical_sales"] for v in sku_roi.values())

    if total_budget is None:
        total_budget = total_spend * 1.15  # 默认按历史花费 +15% 建议

    allocations = []
    writes = []
    for key, v in sku_roi.items():
        # 权重 = ROAS 归一化 × 历史花费占比
        spend_weight = v["historical_spend"] / total_spend if total_spend > 0 else 0
        roas_score = v["historical_roas"]
        # 综合权重：ROAS 贡献 60%，历史花费占比 40%
        combined_weight = roas_score * 0.6 + spend_weight * 0.4
        weight_sum = sum(
            (sv["historical_roas"] * 0.6 + sv["historical_spend"] / max(total_spend, 1) * 0.4)
            for sv in sku_roi.values()
        )
        weight = combined_weight / weight_sum if weight_sum > 0 else 0

        recommended = round(total_budget * weight, 2)
        expected_roas = round(roas_score * 0.9, 2)  # 保守估计 90% 历史表现
        expected_roi = round(expected_roas * recommended, 2)

        # 风险评估
        risk = "low"
        risk_reasons = []
        if v["historical_spend"] < 10:
            risk = "high"
            risk_reasons.append("历史花费不足 $10，数据量少")
        elif v["historical_roas"] < 1:
            risk = "high"
            risk_reasons.append("历史 ROAS < 1，处于亏损状态")
        elif v["historical_orders"] < 5:
            risk = "medium"
            risk_reasons.append("历史出单数 < 5，转化不稳定")

        alloc = {
            "sku": v["sku"],
            "campaign": v["campaign"],
            "historical_spend": v["historical_spend"],
            "historical_roas": v["historical_roas"],
            "weight": round(weight, 3),
            "recommended_budget": recommended,
            "expected_roas": expected_roas,
            "expected_roi": expected_roi,
            "risk": risk,
            "risk_reasons": risk_reasons,
        }
        allocations.append(alloc)

        # 5) 为有预算记录的 SKU 生成写操作提案
        if key in budget_map:
            b = budget_map[key]
            old_budget = b["monthly_budget"]
            if abs(old_budget - recommended) / max(old_budget, 1) >= 0.05:  # 变化 ≥ 5% 才提案
                new_budget = round(recommended, 2)
                writes.append({
                    "table": "ad_budgets",
                    "record_key": f"{v['sku']}:{b.get('period', period)}",
                    "record": {
                        "id": b["id"], "store_id": b["store_id"],
                        "sku": v["sku"], "market": b["market"],
                        "platform": "amazon",
                        "budget_period": period,
                        "budget_type": "monthly",
                        "currency": "USD",
                        "bid": b["bid"],
                        "daily_budget": b["daily_budget"],
                        "monthly_budget": new_budget,
                        "spent": b["spent"],
                        "target_acos": b["target_acos"],
                        "status": b["status"],
                    },
                    "reason": (f"基于历史 ROI（{v['historical_roas']}）与预算约束，"
                               f"建议预算 ${old_budget:.0f} → ${new_budget:.0f}"),
                    "evidence": f"历史花费 ${v['historical_spend']}，销售额 ${v['historical_sales']}，"
                                f"ROAS {v['historical_roas']}，分配权重 {weight:.1%}",
                    "changes": {"monthly_budget": [old_budget, new_budget]},
                })

    allocations.sort(key=lambda a: a["weight"], reverse=True)

    return {
        "period": period,
        "total_budget": round(total_budget, 2),
        "total_historical_spend": round(total_spend, 2),
        "allocations": allocations,
        "writes": writes,
        "recommendation": {
            "top_sku": allocations[0]["sku"] if allocations else "",
            "top_budget": allocations[0]["recommended_budget"] if allocations else 0,
            "total_expected_roas": round(
                sum(a["expected_roas"] * a["weight"] for a in allocations), 2
            ) if allocations else 0,
            "risk_count": sum(1 for a in allocations if a["risk"] == "high"),
        },
    }