"""采购比价分析（P2）：按 SKU 聚合供应商报价，输出比价表与推荐.

基于供应商表 + 询价表，以 TCO（总拥有成本）模型计算综合成本排行。
"""
from __future__ import annotations

from datetime import date

from ..data import access


def compare_prices(*, sku: str | None = None, store_id: str | None = None,
                   market: str | None = None) -> dict:
    """按 SKU 执行采购比价，返回比价表与推荐.

    Returns:
        {sku, market, comparisons: [{supplier, unit_price, moq, lead_days,
          shipping_cost, tco, total_cost, quality_rating, on_time_rate, score}],
         recommendation: {supplier, reason, score}}
    """
    from collections import defaultdict

    # 1) 读取询价表，按 SKU 分组
    inquiry_rows = access.query_table(
        "inquiries", store_id=store_id, sku=sku, limit=2000)
    if not inquiry_rows:
        return {"comparisons": [], "recommendation": None,
                "message": "暂无询价数据，请先导入供应商报价"}

    # 按 SKU 聚合
    by_sku: dict[str, list[dict]] = defaultdict(list)
    for r in inquiry_rows:
        s = r.get("sku", "")
        if r.get("status") in ("valid", "pending"):
            by_sku[s].append(r)

    if not by_sku:
        return {"comparisons": [], "recommendation": None,
                "message": "暂无有效询价记录"}

    # 2) 读取供应商信息
    supplier_rows = access.query_table("suppliers", store_id=store_id, limit=500)
    suppliers = {s["id"]: s for s in supplier_rows}

    # 3) 按 SKU 计算比价
    all_comparisons: list[dict] = []
    for s, quotes in by_sku.items():
        evaluations = []
        for q in quotes:
            sup = suppliers.get(q.get("supplier_id", ""), {})
            # TCO = 单价 × MOQ + 运费 + 打样/模具分摊（假设按 MOQ 分摊）
            moq = int(q.get("moq") or sup.get("min_order_qty") or 0) or 1
            unit_price = float(q.get("unit_price") or 0)
            shipping = float(q.get("shipping_cost") or sup.get("shipping_cost") or 0)
            sample = float(q.get("sample_cost") or 0)
            tooling = float(q.get("tooling_cost") or 0)
            total_cost = unit_price * moq + shipping + sample + tooling
            tco = round(total_cost / moq, 2)

            quality = float(q.get("quality_rating") or sup.get("quality_rating") or 0)
            on_time = float(q.get("on_time_rate") or sup.get("on_time_rate") or 0)
            return_rate = float(q.get("return_rate") or sup.get("return_rate") or 0)

            # 综合评分：TCO 权重 0.5 + 质量 0.25 + 准时率 0.15 + 退货率惩罚 0.1
            tco_score = max(0, 100 - tco * 10)
            quality_score = quality * 20
            on_time_score = on_time * 0.15
            return_penalty = return_rate * 10
            score = round(tco_score * 0.5 + quality_score * 0.25 + on_time_score * 0.15
                          - return_penalty * 0.1, 1)

            evaluations.append({
                "supplier_id": q.get("supplier_id", ""),
                "supplier_name": sup.get("name", ""),
                "unit_price": unit_price,
                "moq": moq,
                "lead_days": int(q.get("lead_days") or sup.get("lead_days") or 0),
                "shipping_cost": shipping,
                "total_cost": round(total_cost, 2),
                "tco": tco,
                "quality_rating": quality,
                "on_time_rate": on_time,
                "return_rate": return_rate,
                "payment_terms": q.get("payment_terms") or sup.get("payment_terms") or "",
                "score": score,
                "_price_valid_to": q.get("price_valid_to"),
            })

        evaluations.sort(key=lambda e: e["score"], reverse=True)
        best = evaluations[0] if evaluations else None
        all_comparisons.append({
            "sku": s,
            "market": market or "US",
            "comparisons": evaluations,
            "recommendation": {
                "supplier_name": best["supplier_name"],
                "unit_price": best["unit_price"],
                "tco": best["tco"],
                "score": best["score"],
                "reason": _recommend_reason(best, evaluations),
            } if best else None,
        })

    return {
        "comparisons": all_comparisons,
        "recommendation": all_comparisons[0]["recommendation"] if all_comparisons else None,
    }


def _recommend_reason(best: dict, all_evals: list[dict]) -> str:
    reasons = []
    reasons.append(f"综合评分 {best['score']} 分（最高）")
    if best["tco"] <= min(e["tco"] for e in all_evals):
        reasons.append("TCO 最低")
    if best["quality_rating"] >= 4:
        reasons.append(f"质量评分 {best['quality_rating']}")
    if best["on_time_rate"] >= 0.9:
        reasons.append(f"准时交付率 {best['on_time_rate']:.0%}")
    return "；".join(reasons)