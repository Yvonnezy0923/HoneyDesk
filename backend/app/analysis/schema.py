"""数据语义模型：给出用户问题相关表的字段角色（维度/度量/其他），供 LLM 精准生成 SQL."""
from __future__ import annotations

from ..data import access

# 表 -> 维度列（可 group by，含日期类）
DIMENSION_COLS: dict[str, list[str]] = {
    "products": ["id", "name", "category", "brand", "status"],
    "product_materials": ["sku", "name", "target_market", "target_language"],
    "listings": ["sku", "market", "status", "language"],
    "sales_orders": ["sku", "channel", "order_date"],
    "competitors": ["sku", "competitor_name", "snapshot_date"],
    "inventory": ["sku", "warehouse"],
    "ad_performance": ["sku", "campaign", "stat_date"],
    "ad_budgets": ["sku"],
    "stores": ["name", "platform", "market"],
}

# 表 -> 度量列（可聚合数值）
MEASURE_COLS: dict[str, list[str]] = {
    "products": ["price", "cost"],
    "product_materials": [],
    "listings": [],
    "sales_orders": ["quantity", "revenue"],
    "competitors": ["price", "stock", "rating"],
    "inventory": ["available", "in_transit", "safety_stock"],
    "ad_performance": ["spend", "sales", "clicks", "impressions", "orders"],
    "ad_budgets": ["bid", "daily_budget"],
    "stores": [],
}

# 表间可关联关系：左表 -> {右表: (左表关联列, 右表关联列)}
# 语义：左表.左列 == 右表.右列。products.id 即 SKU，各业务表用 sku 关联。
RELATIONS: dict[str, dict[str, tuple[str, str]]] = {
    "products": {
        "sales_orders": ("id", "sku"),
        "product_materials": ("id", "sku"),
        "listings": ("id", "sku"),
        "competitors": ("id", "sku"),
        "inventory": ("id", "sku"),
        "ad_performance": ("id", "sku"),
        "ad_budgets": ("id", "sku"),
    },
}

# 表 -> 中文可读标签
TABLE_LABEL: dict[str, str] = {
    "products": "商品", "product_materials": "产品资料", "listings": "Listing",
    "sales_orders": "销售订单", "competitors": "竞品", "inventory": "库存",
    "ad_performance": "广告效果", "ad_budgets": "广告预算", "stores": "店铺",
}

# 列 -> 中文标签
FIELD_LABEL: dict[str, str] = {
    "id": "SKU/ID", "sku": "SKU", "name": "名称", "category": "类目",
    "brand": "品牌", "status": "状态", "price": "价格", "cost": "成本",
    "quantity": "销量", "revenue": "销售额", "order_date": "订单日期",
    "channel": "渠道", "competitor_name": "竞品", "snapshot_date": "快照日期",
    "stock": "竞品库存", "rating": "评分", "available": "可售库存",
    "in_transit": "在途", "safety_stock": "安全库存", "warehouse": "仓库",
    "campaign": "广告活动", "stat_date": "统计日期", "spend": "花费",
    "sales": "广告销售额", "clicks": "点击", "impressions": "曝光",
    "orders": "订单数", "bid": "出价", "daily_budget": "日预算",
    "target_market": "目标市场", "target_language": "语言", "market": "站点",
    "language": "语言", "platform": "平台", "budget_period": "预算周期",
}

# 表 -> 日期字段（用于时间范围过滤）
_DATE_FIELDS = {
    "sales_orders": "order_date",
    "competitors": "snapshot_date",
    "ad_performance": "stat_date",
}

# 汉字/英文 SKU 清洗后可能出现的别名（把 LLM 意图列名收敛到真实列）
COL_ALIASES = {
    "sale_date": "order_date", "date": None, "time": None,
    "sales_amount": "revenue", "amount": "revenue", "qty": "quantity",
    "ad_spend": "spend", "ad_sales": "sales", "ctr": None, "acos": None,
    "marketplace": None,
}


def language() -> str:
    return "zh"


def table_label(table: str) -> str:
    return TABLE_LABEL.get(table, table)


def field_label(table: str, col: str) -> str:
    return FIELD_LABEL.get(col, col)


def date_field(table: str) -> str | None:
    return _DATE_FIELDS.get(table)


def join_columns(a: str, b: str) -> tuple[str, str] | None:
    """返回 (A表关联列, B表关联列)，即 A.列 = B.列；两表不可关联返回 None."""
    r = RELATIONS.get(a, {}).get(b)
    if r:
        return (r[0], r[1])
    rc = RELATIONS.get(b, {}).get(a)
    if rc:
        return (rc[1], rc[0])  # RELATIONS[b][a]=(b左列,a右列) → 反转为 (a列,b列)
    return None


def joinable(tables: list[str]) -> list[tuple[str, str, str, str]]:
    """返回两两可关联的表对：(A, A列, B, B列)。用于喂给 LLM 说明关联能力."""
    out: list[tuple[str, str, str, str]] = []
    seen: set[tuple[str, str]] = set()
    for i, a in enumerate(tables):
        for b in tables[i + 1:]:
            c = join_columns(a, b)
            if c and (a, b) not in seen:
                out.append((a, c[0], b, c[1]))
                seen.add((a, b))
    return out


def normalize_col(table: str, col: str) -> str | None:
    """把 LLM/自然语言里的列名归一到真实列；未知列返回 None.
    先按代码名，再按中文标签反查，双保险."""
    if not col:
        return None
    s = str(col).strip().lower()
    real = COL_ALIASES.get(s, s)
    real_cols = (*DIMENSION_COLS.get(table, []), *MEASURE_COLS.get(table, []))
    if real in real_cols:
        return real
    # 中文标签 → 列
    for c in real_cols:
        if FIELD_LABEL.get(c, "").lower() == s:
            return c
    return None


def table_schema(table: str) -> list[dict]:
    """返回表的字段语义：{name, role(dimension|measure|other), kind(text|number|date), label}."""
    dims = set(DIMENSION_COLS.get(table, []))
    meas = set(MEASURE_COLS.get(table, []))
    date_cols = {date_field(table)} if date_field(table) else set()
    out = []
    for f in access.list_fields(table):
        name = f["name"]
        if name in ("id", "created_at", "updated_at", "store_id"):
            continue
        if name in dims:
            role, kind = "dimension", "date" if name in date_cols else "text"
        elif name in meas:
            role, kind = "measure", "number"
        else:
            role, kind = "other", "number"
        out.append({"name": name, "role": role, "kind": kind,
                    "label": field_label(table, name)})
    return out


def schema_context(tables: list[str]) -> str:
    """构建喂给 LLM 的语义模型文本（code(label)，仅展示维度/度量列，控制 token）。"""
    lines = []
    for t in tables:
        roles = table_schema(t)
        dims = [f"{c['name']}({c['label']})" for c in roles if c["role"] == "dimension"]
        meas = [f"{c['name']}({c['label']})" for c in roles if c["role"] == "measure"]
        lines.append(
            f"- {t}（{table_label(t)}）"
            f"｜维度(可分组): {', '.join(dims) or '无'}"
            f"｜度量(可聚合): {', '.join(meas) or '无'}"
        )
    rels = joinable(tables)
    if rels:
        lines.append(
            "关联关系（跨表需联表查询）: "
            + ", ".join(f"{a}.{ca} = {b}.{cb}" for a, ca, b, cb in rels)
        )
    return "\n".join(lines)