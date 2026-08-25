"""图表配置生成：根据查询结果的数据形态自动匹配图表类型，产出前端可渲染的归一化数据."""
from __future__ import annotations

from . import schema as sm

MAX_PIE_CATEGORIES = 10


def build_chart(res: dict) -> dict | None:
    """res 为 sqlgen.build_and_execute 的返回。
    返回 {table, table_label, categories, series:[{name,data}], suggested, types}；无法成图返回 None.
    """
    if res.get("raw") or not res.get("dimension"):
        return None
    rows = [r for r in (res.get("rows") or []) if r.get("__dim") is not None]
    if not rows:
        return None
    measures = res.get("measures") or []
    categories = [str(r["__dim"]) for r in rows]
    series = []
    for i, m in enumerate(measures):
        key = f"__m{i}"  # 与 sqlgen 生成的列别名一致
        series.append({"name": m.get("label", ""), "data": [_num(r.get(key)) for r in rows]})

    date_dim = _is_date_dim(res.get("dimension"))
    single = len(series) == 1
    if date_dim:
        suggested = "line"
        types = ["line", "bar", "area"] + (["stack"] if not single else [])
    else:
        if single and len(categories) <= MAX_PIE_CATEGORIES:
            suggested = "pie"
            types = ["pie", "bar", "line"]
        elif single:
            suggested = "bar"
            types = ["bar", "line"]
        else:
            suggested = "bar"
            types = ["bar", "line", "stack"]

    return {
        "table": res["table"],
        "table_label": sm.table_label(res["table"]),
        "dimension_label": res.get("dimension_label") or res["dimension"],
        "categories": categories,
        "series": series,
        "suggested": suggested,
        "types": types,
    }


def _num(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _is_date_dim(dim: str | None) -> bool:
    return bool(dim) and any(k in dim.lower() for k in ("date", "time"))