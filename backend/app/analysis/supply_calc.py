"""供应链计算：补货量试算 + 缺货风险评估（P1）.

基于：现有库存 / 在途 / 安全库存 / 近30天日均销 / 采购在途天数。
缺货判定：available ≤ safety_stock × 1.2 视为风险（AC-SC-W1 口径）。
补货量：建议 = max(0, 日均销 × (在途天数 + 目标可售天数) − (在售 + 在途 − 安全库存))。
"""
from __future__ import annotations

from datetime import date, timedelta


def calc_replenishment(inv_rows: list[dict], target_days: int = 30) -> list[dict]:
    out = []
    for r in inv_rows or []:
        ads = float(r.get("avg_daily_sales") or 0)
        avail = int(r.get("available") or 0)
        in_transit = int(r.get("in_transit") or 0)
        safety = int(r.get("safety_stock") or 0)
        lead = int(r.get("replenish_lead_days") or 0)
        reorder = int(r.get("reorder_point") or 0)
        dos = int(avail / ads) if ads else 999
        threshold = safety * 1.2
        if avail <= threshold * 0.6 and safety:
            risk = "high"
        elif avail <= threshold:
            risk = "medium"
        elif avail < reorder:
            risk = "low"
        else:
            risk = "ok"
        suggested = int(max(ads * (lead + target_days) - (avail + in_transit - safety), 0))
        out.append({
            "store_id": r.get("store_id", ""),
            "sku": r.get("sku", ""),
            "market": r.get("market", "US"),
            "warehouse": r.get("warehouse", ""),
            "available": avail,
            "in_transit": in_transit,
            "safety_stock": safety,
            "reorder_point": reorder,
            "lead_days": lead,
            "avg_daily_sales": round(ads, 2),
            "days_of_supply": dos,
            "shortage_risk": risk,
            "suggested_qty": suggested,
            "suggested_arrival": (date.today() + timedelta(days=lead)).isoformat(),
        })
    return out


def shortage_rows(inv_rows, target_days: int = 30) -> list[dict]:
    return [p for p in calc_replenishment(inv_rows, target_days)
            if p["shortage_risk"] in ("high", "medium") and p["suggested_qty"] > 0]