"""聚合规格识别：LLM 结合语义模型判断如何分组/聚合，支持跨表联表查询；失败则用规则兜底."""
from __future__ import annotations

from ..llm import LLMConfig, chat_json
from . import schema as sm

_AGG_ALIASES = {"sum": "sum", "total": "sum", "求和": "sum", "加总": "sum",
                "avg": "avg", "average": "avg", "均值": "avg",
                "max": "max", "最高": "max", "min": "min", "最低": "min",
                "count": "count", "数量": "count", "个数": "count"}
_ALLOWED_AGG = {"sum", "avg", "max", "min", "count"}
# 联表兜底时，优先作为“事实/基表”承载度量的表（销量/花费等）
_FACT_TABLES = ("sales_orders", "ad_performance", "competitors", "inventory")


def recognize(message: str, tables: list[str]) -> list[dict]:
    """返回每张表或联表的聚合规格：
    单表: {table, dimension(列名|None), measures:[{col,agg,alias}], raw}
    联表: {table(基表), join:{table,base_col,join_col},
           dimension:{table,col}|None, measures:[{table,col,agg,alias}], raw}
    仅使用真正存在于表里的维度/度量列，非法字段一律忽略；被联表覆盖的表不再重复输出单表。
    """
    if not tables:
        return []
    try:
        cfg = LLMConfig.from_db()
        if cfg.configured:
            specs = _llm(message, tables, cfg)
            if specs:
                return specs
    except Exception:  # noqa: BLE001
        pass
    return _fallback(tables)


def _llm(message: str, tables: list[str], cfg) -> list[dict] | None:
    ctx = sm.schema_context(tables)
    sys = (
        "你是数据分析师，根据给定的表语义模型判断用户问题需要如何查询与分析，重点判断是否需要联表。\n"
        "输出 JSON：{\"tables\":[\n"
        "  单表项：{\"table\":\"真实表名\",\"raw\":boolean,\"dimension\":\"分组列或null\","
        "\"measures\":[{\"col\":\"度量列\",\"agg\":\"sum|avg|max|min|count\",\"alias\":\"中文别名\"}]}\n"
        "  或联表项：{\"table\":\"基表\",\"join_table\":\"关联表\",\"dimension\":\"关联表里的分组列\","
        "\"measures\":[{\"col\",\"agg\",\"alias\"}]}\n"
        "]}\n"
        "联表判定：当问题要把一张表的文字维度（如商品名称 name）与另一张表的度量（如销量 quantity、"
        "销售额 revenue）关联呈现时（例如\"哪些产品卖得最好\"），必须输出联表项：\n"
        "  - table=提供度量的\"事实表\"（如 sales_orders、ad_performance），join_table=提供分组文字维度的表（如 products）；\n"
        "  - dimension 填 join_table 里展示所需的列（如 name）；measures 用 table 的度量列（如 quantity）。\n"
        "  - 已用联表项表示的一对表，不要再分别输出这两张表的单表项。\n"
        "通用规则：raw 为 true 时 dimension 与 measures 填 []（如\"列出/哪些/库存低于\"的明细）；\n"
        "dimension 和 col 必须用圆括号左侧的英文列名（如 sku、name、revenue、stat_date）；度量列必须数值；\n"
        "单表且未清晰指定时，维度选最有业务意义的 SKU/时间列，度量选 1~2 个关键指标。\n"
        "只输出 JSON。"
    )
    user = f"用户问题：{message}\n\n相关表语义模型与关联关系：\n{ctx}"
    data = chat_json(cfg, sys, user, temperature=0)
    return _validate(data.get("tables") or [], tables)


def _validate(items: list, tables: list[str]) -> list[dict]:
    result = []
    used: set[str] = set()
    table_set = set(tables)
    for it in items or []:
        raw = bool(it.get("raw"))
        base = it.get("table")
        if base not in table_set:
            continue
        jt = it.get("join_table")
        if jt and jt in table_set and raw is False:
            jc = sm.join_columns(base, jt)
            if jc:
                spec = _build_join_spec(it, base, jt, jc)
                if spec and (spec.get("dimension") or spec.get("measures")):
                    result = [r for r in result if r["table"] not in (base, jt)]
                    result.append(spec)
                    used.update({base, jt})
                continue
        if base in used:
            continue
        result.append(_build_single_spec(it, base, raw))
        used.add(base)
    return result or _fallback(tables)


def _build_join_spec(it: dict, base: str, jt: str, jc: tuple[str, str]) -> dict:
    spec = {
        "table": base,
        "join": {"table": jt, "base_col": jc[0], "join_col": jc[1]},
        "dimension": None, "measures": [], "raw": False,
    }
    dim_at = _resolve_col(it.get("dimension"), [jt, base])
    if dim_at:
        spec["dimension"] = {"table": dim_at[0], "col": dim_at[1]}
    spec["measures"] = _norm_measures(it.get("measures"), [base, jt])
    return spec


def _build_single_spec(it: dict, t: str, raw: bool) -> dict:
    spec = {"table": t, "dimension": None, "measures": [], "raw": raw}
    if raw:
        return spec
    dim = sm.normalize_col(t, it.get("dimension"))
    spec["dimension"] = dim
    spec["measures"] = _norm_measures(it.get("measures"), [t])
    return spec


def _norm_measures(measure_list, tables: list[str]) -> list[dict]:
    """把 LLM 的度量列表归结为 {table,col,agg,alias}，仅保留真实度量列."""
    raw_list = measure_list or []
    if raw_list and isinstance(raw_list[0], str):
        raw_list = [{"col": raw_list[0]}]
    out = []
    for m in raw_list:
        res = _resolve_col(m.get("col") if isinstance(m, dict) else m, tables)
        if not res:
            continue
        t, col = res
        if col not in {c["name"] for c in sm.table_schema(t) if c["role"] == "measure"}:
            continue
        agg = _AGG_ALIASES.get(str(m.get("agg") or "sum").lower(), "sum")
        if agg not in _ALLOWED_AGG:
            agg = "sum"
        alias = m.get("alias") if isinstance(m, dict) else sm.field_label(t, col)
        out.append({"table": t, "col": col, "agg": agg, "alias": alias})
    return out


def _resolve_col(col, tables: list[str]):
    """按顺序在候选表里找真实列，返回 (表, 列) 或 None."""
    if not col:
        return None
    for t in tables:
        real = sm.normalize_col(t, col)
        if real:
            return (t, real)
    return None


def _fallback(tables: list[str]) -> list[dict]:
    """无 LLM 兜底：优先 products + 事实表联表（名称×销量），其余表按 SKU 求和."""
    out = []
    if "products" in tables:
        fact = next((x for x in tables if x in _FACT_TABLES), None)
        if fact:
            jc = sm.join_columns(fact, "products")
            meas = [c["name"] for c in sm.table_schema(fact) if c["role"] == "measure"]
            if jc and meas:
                out.append({
                    "table": fact,
                    "join": {"table": "products", "base_col": jc[0], "join_col": jc[1]},
                    "dimension": {"table": "products", "col": "name"},
                    "measures": [{"table": fact, "col": meas[0], "agg": "sum",
                                  "alias": sm.field_label(fact, meas[0])}],
                    "raw": False,
                })
                tables = [t for t in tables if t not in (fact, "products")]
    for t in tables:
        roles = sm.table_schema(t)
        meas = [c["name"] for c in roles if c["role"] == "measure"]
        dim = "sku" if any(c["name"] == "sku" for c in roles if c["role"] == "dimension") else None
        measures = [{"col": m, "agg": "sum", "alias": sm.field_label(t, m)} for m in meas[:2]]
        out.append({"table": t, "dimension": dim, "measures": measures, "raw": not measures})
    return out


def _fallback_selected(tables: list[str]) -> list[dict]:
    return _fallback(tables)