"""查询分析链路编排：语义模型 → 聚合识别 → SQL 生成/执行 → 图表 → 结论/追问."""
from __future__ import annotations

from ..data import access
from . import aggregate, sqlgen, chart as chart_mod, insight

_ALLOWED_TABLES = tuple(access.MODEL_MAP.keys())
_FILTER_KEYS = ("sku", "date_from", "date_to", "store_id", "top_n")


def run(message: str, tables: list[str], params: dict,
        agent_code: str = "ops_query", task_id: str = "", history: str = "") -> dict:
    """对每张相关表执行分析，返回
    {analyses:[{table, sql, sql_params, chart, rows, dimension_label, measures, raw}],
     insight:{conclusion,suggestions,follow_ups}, cost}"""
    tables = [t for t in tables if t in _ALLOWED_TABLES]
    specs = aggregate.recognize(message, tables)

    # 用户指定了"前 N 名/款"时，聚合查询与图表都只取前 N，防止超出提问范围
    try:
        top_n = int(params.get("top_n")) if params.get("top_n") else None
    except (TypeError, ValueError):
        top_n = None
    limit = top_n if (top_n and top_n > 0) else 50
    qparams = {k: v for k, v in params.items() if k in _FILTER_KEYS and k != "top_n"}

    analyses = []
    for spec in specs:
        res = sqlgen.build_and_execute(
            spec,
            params=qparams,
            agent_code=agent_code, task_id=task_id, limit=limit)
        res["chart"] = chart_mod.build_chart(res)
        analyses.append(res)

    ins = insight.analyze(message, analyses, history,
                          agent_code=agent_code, task_id=task_id)
    return {"analyses": analyses, "insight": ins, "cost": 0.0}