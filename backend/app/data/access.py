"""业务数据只读访问：供工具/Agent 查询业务表（全部参数化，防注入）."""
from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import select

from ..database import session
from ..models import business as m

MODEL_MAP = {
    "products": m.Product,
    "product_materials": m.ProductMaterial,
    "listings": m.Listing,
    "sales_orders": m.SalesOrder,
    "competitors": m.Competitor,
    "inventory": m.Inventory,
    "suppliers": m.Supplier,
    "inquiries": m.Inquiry,
    "replenishment_plans": m.ReplenishmentPlan,
    "alerts": m.AlertRecord,
    "ad_performance": m.AdPerformance,
    "ad_budgets": m.AdBudget,
    "stores": m.Store,
}
DATE_FIELDS = {"order_date", "snapshot_date", "stat_date"}

# 表 -> 业务范围（供知识库按 scope 隔离检索）
TABLE_META = {
    "products": {"scope": "products"},
    "product_materials": {"scope": "products"},
    "listings": {"scope": "products"},
    "sales_orders": {"scope": "operations"},
    "competitors": {"scope": "operations"},
    "inventory": {"scope": "supply"},
    "suppliers": {"scope": "supply"},
    "inquiries": {"scope": "supply"},
    "replenishment_plans": {"scope": "supply"},
    "alerts": {"scope": "supply"},
    "ad_performance": {"scope": "ads"},
    "ad_budgets": {"scope": "ads"},
    "stores": {"scope": "operations"},
}


def query_table(table: str, *, store_id: str | None = None, sku: str | None = None,
                date_from: date | None = None, date_to: date | None = None,
                limit: int = 100) -> list[dict]:
    """通用只读查询：字段级过滤 + 日期范围，返回记录列表."""
    model = MODEL_MAP.get(table)
    if model is None:
        raise KeyError(f"未公开的业务表：{table}")
    stmt = select(model).limit(limit)
    if store_id and hasattr(model, "store_id"):
        stmt = stmt.where(model.store_id == store_id)
    for f, val in (("sku", sku),):
        if val and hasattr(model, f):
            stmt = stmt.where(getattr(model, f) == val)
    for df, val in (("date_from", date_from), ("date_to", date_to)):
        if val is None:
            continue
        field = next((df2 for df2 in DATE_FIELDS if hasattr(model, df2)), None)
        if field:
            col = getattr(model, field)
            stmt = stmt.where(col >= val) if df == "date_from" else stmt.where(col <= val)
    with session() as db:
        rows = db.execute(stmt).scalars().all()
    return [_row_to_dict(r) for r in rows]


def first(table: str, **filters) -> dict | None:
    model = MODEL_MAP.get(table)
    if model is None:
        raise KeyError(table)
    stmt = select(model)
    for k, v in filters.items():
        if hasattr(model, k):
            stmt = stmt.where(getattr(model, k) == v)
    with session() as db:
        r = db.execute(stmt).scalars().first()
    return _row_to_dict(r) if r else None


def list_fields(table: str) -> list[dict]:
    model = MODEL_MAP.get(table)
    if model is None:
        return []
    return [{"name": c.name, "type": str(c.type), "nullable": c.nullable}
            for c in model.__table__.columns]


def _row_to_dict(r: Any) -> dict:
    from sqlalchemy.orm import class_mapper
    d: dict = {}
    for attr in class_mapper(r.__class__).column_attrs:
        key = attr.columns[0].name
        val = getattr(r, attr.key)
        if isinstance(val, (date,)):
            val = val.isoformat()
        d[key] = val
    return d