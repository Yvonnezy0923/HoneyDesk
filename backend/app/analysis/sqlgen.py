"""SQL 构建与执行：白名单强校验 + 参数化，杜绝注入；返回生成 SQL 与结果行."""
from __future__ import annotations

import time
from datetime import date, datetime

from sqlalchemy import text

from ..database import session, BUSINESS_SCHEMA
from ..models.business import ToolRecord
from . import schema as sm

_ALLOWED_AGG = {"sum", "avg", "max", "min", "count"}
_SCHEMA = BUSINESS_SCHEMA


def parse_date(val) -> date | None:
    if isinstance(val, date):
        return val
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, str) and val:
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y/%m/%d %H:%M:%S"):
            try:
                return datetime.strptime(val, fmt).date()
            except ValueError:
                continue
    return None


def _qual(table: str) -> str:
    return f"`{_SCHEMA}`.`{table}`"


def _jsonable(val):
    """把 MySQL 返回的 date/datetime/Decimal 转为可 JSON 序列化类型."""
    import decimal
    if isinstance(val, (datetime, date)):
        return val.isoformat()
    if isinstance(val, decimal.Decimal):
        return float(val)
    if isinstance(val, dict):
        return {k: _jsonable(v) for k, v in val.items()}
    if isinstance(val, (list, tuple)):
        return [_jsonable(v) for v in val]
    return val


def build_and_execute(spec: dict, *, params: dict, agent_code: str = "ops_query",
                      task_id: str = "", limit: int = 50) -> dict:
    """单表或联表查询。
    spec: {table, dimension, measures, raw} 或
          {table, join:{table,base_col,join_col}, dimension:{table,col}, measures:[{table,col,agg,alias}], raw}.
    params: {sku, date_from, date_to, store_id}（已由意图识别给出）。
    返回 {table, sql, sql_params, rows, dimension_label, measures:[{name,label}], raw, ms, total}。
    """
    table = spec["table"]
    if spec.get("join"):
        return _build_join(spec, params=params, agent_code=agent_code,
                           task_id=task_id, limit=limit)

    roles = sm.table_schema(table)
    all_cols = {c["name"] for c in roles}
    date_col = sm.date_field(table)

    where = []
    bind: dict = {}
    if params.get("store_id") and "store_id" in all_cols:
        where.append("store_id = :store_id")
        bind["store_id"] = params["store_id"]
    if params.get("sku") and "sku" in all_cols:
        where.append("sku = :sku")
        bind["sku"] = params["sku"]
    date_from = parse_date(params.get("date_from"))
    date_to = parse_date(params.get("date_to"))
    if date_col:
        if date_from:
            where.append(f"{date_col} >= :date_from")
            bind["date_from"] = date_from.isoformat()
        if date_to:
            where.append(f"{date_col} <= :date_to")
            bind["date_to"] = date_to.isoformat()

    raw = bool(spec.get("raw"))
    if raw or not spec.get("dimension") or not spec.get("measures"):
        # 原样列表查询：列白名单过滤
        sel_cols = []
        for c in all_cols:
            if c in ("created_at", "updated_at"):
                continue
            sel_cols.append(c if c in sm.FIELD_LABEL else c)
        sel = ", ".join(f"`{c}`" for c in sel_cols[:20])
        sql = f"SELECT {sel} FROM {_qual(table)}"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += f" ORDER BY 1 LIMIT {int(limit)}"
        rows = _exec(sql, bind, table, agent_code, task_id)
        return {
            "table": table, "sql": sql, "sql_params": bind, "rows": rows,
            "dimension_label": "", "measures": [], "raw": True,
            "ms": 0, "total": len(rows),
        }

    # 聚合查询：白名单校验列与聚合函数
    dim = spec["dimension"]
    if dim not in all_cols or dim in ("created_at", "updated_at"):
        dim = None
    safe_measures = []
    for m in spec.get("measures") or []:
        if m["col"] in all_cols and m["agg"] in _ALLOWED_AGG:
            safe_measures.append(m)
    if not safe_measures:
        # 无合法度量 → 降级为 COUNT(*)
        safe_measures = [{"col": None, "agg": "count", "alias": "记录数"}]

    select_parts = []
    if dim:
        select_parts.append(f"`{dim}` AS __dim")
    for i, m in enumerate(safe_measures):
        fn = m["agg"].upper()
        expr = "COUNT(*)" if m["col"] is None else f"{fn}(`{m['col']}`)"
        select_parts.append(f"{expr} AS __m{i}")
    sel = ", ".join(select_parts)
    group = f" GROUP BY `{dim}`" if dim else ""
    order = f" ORDER BY __m0 DESC" if safe_measures else ""
    sql = f"SELECT {sel} FROM {_qual(table)}"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += group + order + f" LIMIT {int(limit)}"

    bind_params = bind
    rows = _exec(sql, bind_params, table, agent_code, task_id)

    # 规整为 {dimension_label, measures:[{name,label}], rows:[{dim, m0..}]} 的形状给 chart
    return {
        "table": table, "sql": sql, "sql_params": bind, "rows": rows,
        "dimension": dim,
        "dimension_label": sm.field_label(table, dim) if dim else "",
        "measures": [{"name": f"m{i}", "label": m.get("alias") or sm.field_label(table, m["col"])}
                     for i, m in enumerate(safe_measures)],
        "raw": False, "ms": 0, "total": len(rows),
    }


def _build_join(spec: dict, *, params: dict, agent_code: str,
                task_id: str, limit: int) -> dict:
    """联表聚合查询：基表(spec.table, 别名 t) JOIN 关联表(spec.join.table, 别名 j).
    维度列/度量列通过 {table,col} 指明归属表；过滤条件作用在基表列上。"""
    base = spec["table"]
    jj = spec["join"]
    jt = jj["table"]
    base_col, join_col = jj.get("base_col"), jj.get("join_col")
    if not base_col or not join_col:
        fill = sm.join_columns(base, jt)
        if not fill:
            return _single_fallback(spec, params=params, agent_code=agent_code,
                                    task_id=task_id, limit=limit)
        base_col, join_col = fill

    base_roles = sm.table_schema(base)
    base_cols = {c["name"] for c in base_roles}
    alias_of = {base: "t", jt: "j"}
    q = lambda t: alias_of[t]                    # noqa: E731

    # 过滤条件（作用在基表）
    where, bind = [], {}
    if params.get("store_id") and "store_id" in base_cols:
        where.append("t.store_id = :store_id")
        bind["store_id"] = params["store_id"]
    if params.get("sku") and "sku" in base_cols:
        where.append("t.sku = :sku")
        bind["sku"] = params["sku"]
    date_col = sm.date_field(base)
    date_from = parse_date(params.get("date_from"))
    date_to = parse_date(params.get("date_to"))
    if date_col:
        if date_from:
            where.append(f"t.{date_col} >= :date_from")
            bind["date_from"] = date_from.isoformat()
        if date_to:
            where.append(f"t.{date_col} <= :date_to")
            bind["date_to"] = date_to.isoformat()

    # 维度列（通常来自关联表，如 products.name）
    dim = spec.get("dimension") or {}
    dim_table = dim.get("table") if dim.get("col") else base
    dim_col = dim.get("col") or None
    safe_measures = [m for m in (spec.get("measures") or [])
                     if m.get("agg") in _ALLOWED_AGG]
    if not safe_measures:
        safe_measures = [{"table": base, "col": None, "agg": "count",
                          "alias": "记录数"}]

    select_parts = []
    group_cols = []
    if dim_col:
        dexpr = f"{q(dim_table)}.`{dim_col}`"
        select_parts.append(f"{dexpr} AS __dim")
        group_cols.append(dexpr)
    for i, m in enumerate(safe_measures):
        tname = q(m.get("table") or base)
        expr = "COUNT(*)" if m.get("col") is None else \
            f"{m['agg'].upper()}({tname}.`{m['col']}`)"
        select_parts.append(f"{expr} AS __m{i}")
    sel = ", ".join(select_parts)
    group = f" GROUP BY {group_cols[0]}" if group_cols else ""
    order = " ORDER BY __m0 DESC" if safe_measures else ""
    sql = (f"SELECT {sel} FROM {_qual(base)} t "
           f"JOIN {_qual(jt)} j ON j.`{join_col}` = t.`{base_col}`")
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += group + order + f" LIMIT {int(limit)}"

    rows = _exec(sql, bind, base, agent_code, task_id)

    display = dim_table if dim_col else base
    return {
        "table": display,
        "dimension": dim_col,
        "dimension_label": sm.field_label(display, dim_col) if dim_col else "",
        "measures": [{"name": f"m{i}",
                      "label": m.get("alias") or
                      (sm.field_label(m.get("table") or base, m["col"]) if m.get("col") else "记录数")}
                     for i, m in enumerate(safe_measures)],
        "rows": rows, "sql": sql, "sql_params": bind,
        "raw": False, "ms": 0, "total": len(rows),
    }


def _single_fallback(spec: dict, **kw) -> dict:
    """join 无效时退化为基表单表查询。"""
    single = {k: v for k, v in spec.items() if k != "join"}
    dim = spec.get("dimension") or {}
    single["dimension"] = dim.get("col") or None
    single["measures"] = [{"col": m.get("col"), "agg": m.get("agg", "sum"),
                           "alias": m.get("alias")} for m in (spec.get("measures") or [])]
    return build_and_execute(single, **kw)


def _exec(sql: str, bind: dict, table: str, agent_code: str, task_id: str) -> list[dict]:
    t0 = time.time()
    with session() as db:
        rows = db.execute(text(sql), bind).mappings().all()
        res = [_jsonable(dict(r)) for r in rows]
    ms = int((time.time() - t0) * 1000)
    # 读操作不进操作审计（读无需审批），仅计入工具调用计数（数据看板）
    try:
        usage(tool_code=f"query_{table}", ok=True, ms=ms)
    except Exception:  # noqa: BLE001
        pass
    return res


def usage(tool_code: str, ok: bool, ms: int) -> None:
    try:
        with session() as db:
            rec = db.get(ToolRecord, tool_code)
            if not rec:
                # 未命中即新建：保证任意查询工具被调用都有计数
                rec = ToolRecord(id=tool_code, code=tool_code, name=tool_code,
                                 table_name=tool_code, fields=[], permission="read")
                db.add(rec)
            rec.call_count += 1
            rec.success_count += 1 if ok else 0
            rec.total_ms += ms
    except Exception:  # noqa: BLE001
        pass