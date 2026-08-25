"""监控预警规则服务：规则 CRUD / 评估引擎 / 时序数据 / 字段列表.

规则存储：利用已有 settings 表（key='monitor_rules' → JSON 数组）。
预警记录：写入已有 alerts 表（AlertRecord），无需新增表。
"""
from __future__ import annotations

import json
import math
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import select, func, text

from ..database import session
from ..models import business as bm
from ..models import audit as am
from ..alerts import service as alerts_service
from .. import ids

_SETTINGS_KEY = "monitor_rules"
_FREQ_SETTINGS_KEY = "monitor_frequency"
_DEFAULT_FREQUENCY = "1h"
_DEFAULT_SPARKLINE_DAYS = 30
_BUSINESS_SCHEMA = "honey_desk"


def _qual(tbl: str) -> str:
    return f"`{_BUSINESS_SCHEMA}`.`{tbl}`"

# 表 → 时间字段映射
TIME_FIELDS: dict[str, str] = {
    "sales_orders": "order_date",
    "competitors": "snapshot_date",
    "ad_performance": "stat_date",
    "inventory": "created_at",
    "ad_budgets": "created_at",
    "products": "created_at",
    "product_materials": "created_at",
    "listings": "created_at",
    "replenishment_plans": "created_at",
    "alerts": "created_at",
}

# 表 → 中文标签
TABLE_LABELS: dict[str, str] = {
    "products": "商品", "product_materials": "产品资料", "listings": "Listing",
    "sales_orders": "销售订单", "competitors": "竞品", "inventory": "库存",
    "ad_performance": "广告效果", "ad_budgets": "广告预算", "stores": "店铺",
    "replenishment_plans": "补货计划", "alerts": "预警记录",
}

# 字段 → 中文标签
FIELD_LABELS: dict[str, str] = {
    "id": "SKU/ID", "sku": "SKU", "name": "名称", "category": "类目",
    "brand": "品牌", "status": "状态", "price": "价格", "cost": "成本",
    "quantity": "销量", "revenue": "销售额", "order_date": "订单日期",
    "channel": "渠道", "competitor_name": "竞品", "snapshot_date": "快照日期",
    "stock": "竞品库存", "rating": "评分", "available": "可售库存",
    "in_transit": "在途", "reserved": "已预留", "damaged": "破损",
    "safety_stock": "安全库存", "reorder_point": "补货点",
    "stock_valuation": "库存货值", "days_of_supply": "可售天数",
    "avg_daily_sales": "日均销量", "warehouse": "仓库",
    "campaign": "广告活动", "stat_date": "统计日期", "spend": "花费",
    "sales": "广告销售额", "clicks": "点击", "impressions": "曝光",
    "orders": "订单数", "ctr": "点击率", "cpc": "单次点击成本",
    "acos": "广告花费占比", "roas": "投产比",
    "bid": "出价", "daily_budget": "日预算", "monthly_budget": "月预算",
    "spent": "已花费", "target_acos": "目标ACOS",
    "out_of_stock": "竞品缺货", "review_count": "评价数", "monthly_sales": "预估月销",
    "unit_price": "成交单价", "shipping_fee": "物流佣金",
    "sub_category": "子类目", "series": "产品线",
}

# 维度字段（规则按此字段分组评估）
DIMENSION_FIELDS: dict[str, str] = {
    "products": "id", "product_materials": "sku", "listings": "sku",
    "sales_orders": "sku", "competitors": "sku", "inventory": "sku",
    "ad_performance": "sku", "ad_budgets": "sku",
    "replenishment_plans": "sku", "alerts": "sku",
}

# 可监控的表及其字段（排除主键、日期、文本大字段）
MONITORABLE_TABLES: dict[str, list[str]] = {
    "products": ["price", "cost"],
    "sales_orders": ["quantity", "revenue", "unit_price", "shipping_fee"],
    "competitors": ["price", "stock", "rating", "review_count", "monthly_sales", "out_of_stock"],
    "inventory": ["available", "in_transit", "reserved", "damaged",
                  "safety_stock", "reorder_point", "stock_valuation",
                  "days_of_supply", "avg_daily_sales"],
    "ad_performance": ["spend", "sales", "clicks", "impressions", "orders",
                       "ctr", "cpc", "acos", "roas"],
    "ad_budgets": ["bid", "daily_budget", "monthly_budget", "spent", "target_acos"],
}

# 聚合方式建议
AGG_SUGGEST = {
    "spend": "sum", "sales": "sum", "clicks": "sum", "impressions": "sum",
    "orders": "sum", "quantity": "sum", "revenue": "sum",
    "ctr": "avg", "cpc": "avg", "acos": "avg", "roas": "avg",
    "price": "avg", "cost": "avg", "rating": "avg", "target_acos": "avg",
    "available": "avg", "in_transit": "avg", "reserved": "avg", "damaged": "avg",
    "safety_stock": "avg", "reorder_point": "avg", "stock_valuation": "avg",
    "days_of_supply": "avg", "avg_daily_sales": "avg", "monthly_sales": "avg",
    "bid": "avg", "daily_budget": "avg", "monthly_budget": "avg",
    "spent": "avg", "review_count": "avg",
    "out_of_stock": "max", "unit_price": "avg", "shipping_fee": "sum",
}

# ============================================================
# 规则 CRUD
# ============================================================


def _load_rules() -> list[dict]:
    with session() as db:
        s = db.execute(
            select(bm.Setting).where(bm.Setting.key == _SETTINGS_KEY)).scalar()
    if s and s.value:
        try:
            return json.loads(s.value)
        except (json.JSONDecodeError, TypeError):
            return []
    return []


def _save_rules(rules: list[dict]) -> None:
    with session() as db:
        existing = db.execute(
            select(bm.Setting).where(bm.Setting.key == _SETTINGS_KEY)).scalar()
        if existing:
            existing.value = json.dumps(rules, ensure_ascii=False)
        else:
            db.add(bm.Setting(key=_SETTINGS_KEY,
                              value=json.dumps(rules, ensure_ascii=False)))


def list_rules() -> list[dict]:
    rules = _load_rules()
    for r in rules:
        _set_display_labels(r)
    return rules


def get_rule(rule_id: str) -> dict | None:
    for r in _load_rules():
        if r["id"] == rule_id:
            _set_display_labels(r)
            return r
    return None


def save_rule(rule: dict) -> dict:
    rules = _load_rules()
    now = datetime.utcnow().isoformat()
    rule_id = rule.get("id") or _new_rule_id()
    existing = next((r for r in rules if r["id"] == rule_id), None)
    if existing:
        existing.update(rule)
        existing["id"] = rule_id
        existing["updated_at"] = now
    else:
        rule["id"] = rule_id
        rule["created_at"] = now
        rule["updated_at"] = now
        rule["last_triggered_at"] = None
        rules.append(rule)
    _save_rules(rules)
    result = get_rule(rule_id)
    return result or rule


def delete_rule(rule_id: str) -> bool:
    rules = _load_rules()
    before = len(rules)
    rules[:] = [r for r in rules if r["id"] != rule_id]
    if len(rules) < before:
        _save_rules(rules)
        return True
    return False


def _new_rule_id() -> str:
    return f"rule_{ids.short_id()}"


def _set_display_labels(r: dict) -> None:
    tbl = r.get("table", "")
    r["table_label"] = TABLE_LABELS.get(tbl, tbl)
    fld = r.get("field", "")
    r["field_label"] = FIELD_LABELS.get(fld, fld)
    dim = r.get("dimension", "")
    r["dimension_label"] = FIELD_LABELS.get(dim, dim)


# ============================================================
# 字段列表
# ============================================================


def all_fields() -> list[dict]:
    """返回所有可监控字段列表 [{table, table_label, fields:[{name, label, agg, type}]}]."""
    out = []
    for tbl, fields in MONITORABLE_TABLES.items():
        items = []
        for f in fields:
            items.append({
                "name": f,
                "label": FIELD_LABELS.get(f, f),
                "suggested_agg": AGG_SUGGEST.get(f, "avg"),
                "time_field": TIME_FIELDS.get(tbl, "created_at"),
                "dimension": DIMENSION_FIELDS.get(tbl, "sku"),
            })
        out.append({
            "table": tbl,
            "table_label": TABLE_LABELS.get(tbl, tbl),
            "fields": items,
        })
    return out


# ============================================================
# 时序数据（Sparkline）
# ============================================================


def get_timeseries(rule_id: str, days: int = _DEFAULT_SPARKLINE_DAYS) -> dict | None:
    """获取某规则的时序数据，返回 {dates, values, threshold, outliers}."""
    rule = get_rule(rule_id)
    if not rule:
        return None
    return _query_timeseries(rule, days)


def _query_timeseries(rule: dict, days: int) -> dict:
    tbl = rule["table"]
    field = rule["field"]
    time_field = TIME_FIELDS.get(tbl, "created_at")
    agg = rule.get("aggregation", AGG_SUGGEST.get(field, "avg"))
    date_from = (date.today() - timedelta(days=days)).isoformat()

    # 用 raw SQL 查询时序
    if agg == "latest":
        # 按日期取最新一条记录的值
        sql = text(f"""
            SELECT DATE({time_field}) as dt, {field} as val
            FROM {_qual(tbl)}
            WHERE {time_field} >= :date_from
            ORDER BY dt ASC
        """)
    else:
        sql = text(f"""
            SELECT DATE({time_field}) as dt, {agg}({field}) as val
            FROM {_qual(tbl)}
            WHERE {time_field} >= :date_from
            GROUP BY DATE({time_field})
            ORDER BY dt ASC
        """)

    from ..database import engine
    with engine.connect() as conn:
        rows = conn.execute(sql, {"date_from": date_from}).fetchall()

    dates = [str(r[0]) for r in rows if r[0] is not None]
    values = [float(r[1]) for r in rows if r[1] is not None]

    # 阈值计算
    threshold = _threshold_value(rule)
    outliers = []
    if threshold is not None:
        comp = rule.get("comparison", "lt")
        for i, v in enumerate(values):
            if _compare(v, threshold, comp):
                outliers.append({"index": i, "date": dates[i], "value": v})

    return {
        "dates": dates,
        "values": values,
        "threshold": threshold,
        "threshold_label": _threshold_label(rule),
        "outliers": outliers,
    }


def _threshold_value(rule: dict) -> float | None:
    tt = rule.get("threshold_type", "fixed")
    if tt == "fixed":
        v = rule.get("threshold_value")
        return float(v) if v is not None else None
    if tt in ("moving_avg", "zscore"):
        # 动态阈值需计算后返回，这里返回 None 表示动态
        return None
    if tt == "field_ratio":
        return rule.get("threshold_value")
    return None


def _threshold_label(rule: dict) -> str:
    tt = rule.get("threshold_type", "fixed")
    if tt == "fixed":
        comp = {"lt": "<", "lte": "≤", "gt": ">", "gte": "≥", "eq": "="}.get(
            rule.get("comparison", "lt"), "")
        tv = rule.get("threshold_value")
        return f"{comp} {tv}" if tv is not None else ""
    if tt == "moving_avg":
        w = rule.get("window", 7)
        sd = rule.get("stddev_multiplier", 2)
        dir_label = {"above": "高于", "below": "低于", "both": "偏离"}.get(
            rule.get("direction", "both"), "")
        return f"{w}日滑动平均{dir_label}{sd}σ"
    if tt == "field_ratio":
        ref = FIELD_LABELS.get(rule.get("reference_field", ""), rule.get("reference_field", ""))
        tv = rule.get("threshold_value")
        return f"{rule.get('field_label', '')} / {ref} ≥ {tv}" if tv else ""
    if tt == "pct_change":
        p = rule.get("pct_threshold", 50)
        return f"环比变化 > {p}%"
    return ""


# ============================================================
# 规则评估引擎
# ============================================================


def evaluate_all_rules() -> list[dict]:
    """评估所有启用的规则，写入触发的预警记录，返回触发列表."""
    rules = _load_rules()
    triggered: list[dict] = []
    for rule in rules:
        if not rule.get("enabled", True):
            continue
        try:
            alerts = _evaluate_single(rule)
            triggered.extend(alerts)
        except Exception as e:
            print(f"[monitor] 规则 {rule.get('id')} 评估失败: {e}")
    return triggered


def evaluate_rule(rule_id: str) -> list[dict]:
    """评估单条规则，返回触发预警列表."""
    rule = get_rule(rule_id)
    if not rule:
        return []
    return _evaluate_single(rule)


def _evaluate_single(rule: dict) -> list[dict]:
    tbl = rule["table"]
    field = rule["field"]
    dim = rule.get("dimension", DIMENSION_FIELDS.get(tbl, "sku"))
    time_field = TIME_FIELDS.get(tbl, "created_at")
    agg = rule.get("aggregation", AGG_SUGGEST.get(field, "avg"))
    tt = rule.get("threshold_type", "fixed")
    comp = rule.get("comparison", "lt")
    sev = rule.get("severity", "medium")
    scope = rule.get("scope", "supply")
    msg_tpl = rule.get("message_template", "")

    triggered: list[dict] = []

    if tt == "fixed":
        tv = rule.get("threshold_value")
        if tv is None:
            return []
        threshold = float(tv)
        dim_values = _query_dim_values(tbl, field, dim, time_field, agg)
        for dv in dim_values:
            val = dv["value"]
            if val is not None and _compare(val, threshold, comp):
                fmt_kw = {k: v for k, v in dv.items() if k not in ('value',)}
                msg = msg_tpl.format(
                    **fmt_kw, value=round(val, 2), threshold=threshold,
                    field_label=FIELD_LABELS.get(field, field),
                ) if msg_tpl else f"{dv.get(dim, '')} {field} {val:.2f} 触发阈值 {threshold:.2f}"
                triggered.append(_write_alert(rule, dv, field, msg, sev, scope))

    elif tt == "moving_avg":
        window = rule.get("window", 7)
        sd = float(rule.get("stddev_multiplier", 2))
        direction = rule.get("direction", "both")
        dim_values = _query_dim_values_with_history(
            tbl, field, dim, time_field, agg, window)
        for dv in dim_values:
            hist = dv.get("history", [])
            if len(hist) < 2:
                continue
            mean = sum(hist) / len(hist)
            std = _stddev(hist, mean)
            latest = dv["value"]
            if latest is None:
                continue
            triggered_flag = False
            if direction in ("above", "both") and latest > mean + sd * std:
                triggered_flag = True
            if direction in ("below", "both") and latest < mean - sd * std:
                triggered_flag = True
            if triggered_flag:
                fmt_kw = {k: v for k, v in dv.items() if k not in ('value', 'history')}
                msg = msg_tpl.format(
                    **fmt_kw, value=round(latest, 2), mean=round(mean, 2),
                    std=round(std, 2), sd_mult=sd,
                    field_label=FIELD_LABELS.get(field, field),
                ) if msg_tpl else (
                    f"{dv.get(dim, '')} {field} {latest:.2f} "
                    f"偏离均值 {mean:.2f} ± {sd:.2f}×{std:.2f}")
                triggered.append(_write_alert(rule, dv, field, msg, sev, scope))

    elif tt == "field_ratio":
        ref_field = rule.get("reference_field")
        tv = rule.get("threshold_value")
        if not ref_field or tv is None:
            return []
        threshold = float(tv)
        dim_values = _query_dim_ratio(tbl, field, ref_field, dim, time_field)
        for dv in dim_values:
            ratio = dv.get("ratio")
            if ratio is not None and _compare(ratio, threshold, comp):
                fmt_kw = {k: v for k, v in dv.items() if k not in ('value', 'ratio', 'ref_value')}
                msg = msg_tpl.format(
                    **fmt_kw, ratio=round(ratio, 2), threshold=threshold,
                    field_label=FIELD_LABELS.get(field, field),
                    ref_label=FIELD_LABELS.get(ref_field, ref_field),
                ) if msg_tpl else (
                    f"{dv.get(dim, '')} {field}/{ref_field} = {ratio:.2f} ≥ {threshold:.2f}")
                triggered.append(_write_alert(rule, dv, field, msg, sev, scope))

    return triggered


def _write_alert(rule: dict, dv: dict, field: str,
                 message: str, severity: str, scope: str) -> dict:
    dim = rule.get("dimension", "sku")
    dim_val = str(dv.get(dim, ""))
    alert_type = f"monitor_{rule.get('id', 'unknown')[:12]}"
    # 查同一规则同一维度是否有未处理的预警 → 刷时间，不重复新增
    existing = _find_unresolved_alert(alert_type, dim_val)
    if existing:
        _touch_alert_timestamp(existing["id"])
        # 更新规则的 last_triggered_at
        rules = _load_rules()
        for r in rules:
            if r["id"] == rule.get("id"):
                r["last_triggered_at"] = datetime.utcnow().isoformat()
                break
        _save_rules(rules)
        return {"updated": True, "alert_id": existing["id"], "dim": dim_val}
    rec = alerts_service.write(
        alert_type=alert_type,
        scope=scope,
        store_id=dv.get("store_id", ""),
        sku=dim_val if dim else "",
        severity=severity,
        title=message[:200],
        message=message,
        evidence={
            "rule_id": rule.get("id"),
            "rule_name": rule.get("name", ""),
            "table": rule.get("table"),
            "field": field,
            "value": dv.get("value"),
            "threshold": rule.get("threshold_value"),
        },
        source_task="monitor_hourly",
    )
    # 更新规则的 last_triggered_at
    rules = _load_rules()
    for r in rules:
        if r["id"] == rule.get("id"):
            r["last_triggered_at"] = datetime.utcnow().isoformat()
            break
    _save_rules(rules)
    return {"alert_id": rec.get("id"), "dim": dim_val, "message": message[:80]}


def _find_unresolved_alert(alert_type: str, dim_val: str) -> dict | None:
    """查找同一规则同一维度未处理的预警（status != 'resolved'）."""
    with session() as db:
        row = db.execute(
            select(bm.AlertRecord).where(
                bm.AlertRecord.alert_type == alert_type,
                bm.AlertRecord.sku == dim_val,
                bm.AlertRecord.status != "resolved",
            ).limit(1)
        ).scalars().first()
        if row:
            return {c.name: getattr(row, c.name) for c in row.__table__.columns}
        return None


def _touch_alert_timestamp(alert_id: str) -> None:
    """将预警记录的 created_at 刷到最新时间."""
    with session() as db:
        r = db.get(bm.AlertRecord, alert_id)
        if r:
            r.created_at = datetime.utcnow()


# ============================================================
# 数据查询辅助
# ============================================================


def _query_dim_values(tbl: str, field: str, dim: str,
                      time_field: str, agg: str) -> list[dict]:
    """查询每个维度（如 sku）的最新聚合值."""
    from ..database import engine
    date_from = (date.today() - timedelta(days=30)).isoformat()
    if agg == "latest":
        sql = text(f"""
            SELECT t.{dim}, t.{field} as value
            FROM {_qual(tbl)} t
            INNER JOIN (
                SELECT {dim}, MAX({time_field}) as max_t
                FROM {_qual(tbl)}
                WHERE {time_field} >= :date_from
                GROUP BY {dim}
            ) sub ON t.{dim} = sub.{dim} AND t.{time_field} = sub.max_t
        """)
    else:
        sql = text(f"""
            SELECT {dim}, {agg}({field}) as value
            FROM {_qual(tbl)}
            WHERE {time_field} >= :date_from
            GROUP BY {dim}
        """)
    with engine.connect() as conn:
        rows = conn.execute(sql, {"date_from": date_from}).fetchall()
    return [{dim: str(r[0]), "value": float(r[1]) if r[1] is not None else None}
            for r in rows if r[0] is not None]


def _query_dim_values_with_history(tbl: str, field: str, dim: str,
                                   time_field: str, agg: str,
                                   window: int) -> list[dict]:
    """查询每个维度的历史值序列（用于滑动平均评估）."""
    from ..database import engine
    date_from = (date.today() - timedelta(days=window + 7)).isoformat()
    dims = _query_dim_values(tbl, field, dim, time_field, agg)
    out = []
    for dv in dims:
        dim_val = dv[dim]
        if not dim_val:
            continue
        if agg == "latest":
            sql = text(f"""
                SELECT {field}
                FROM {_qual(tbl)}
                WHERE {dim} = :dim_val AND {time_field} >= :date_from
                ORDER BY {time_field} DESC
                LIMIT {window}
            """)
        else:
            sql = text(f"""
                SELECT DATE({time_field}) as dt, {agg}({field}) as val
                FROM {_qual(tbl)}
                WHERE {dim} = :dim_val AND {time_field} >= :date_from
                GROUP BY DATE({time_field})
                ORDER BY dt ASC
            """)
        with engine.connect() as conn:
            rows = conn.execute(sql, {"dim_val": dim_val,
                                      "date_from": date_from}).fetchall()
        if agg == "latest":
            hist = [float(r[0]) for r in rows if r[0] is not None]
        else:
            hist = [float(r[1]) for r in rows if r[1] is not None]
        if hist:
            dv["history"] = hist
            out.append(dv)
    return out


def _query_dim_ratio(tbl: str, field: str, ref_field: str,
                     dim: str, time_field: str) -> list[dict]:
    """查询每个维度的两个字段比值."""
    from ..database import engine
    date_from = (date.today() - timedelta(days=30)).isoformat()
    sql = text(f"""
        SELECT {dim},
               AVG({field}) as val_a,
               AVG({ref_field}) as val_b
        FROM {_qual(tbl)}
        WHERE {time_field} >= :date_from
        GROUP BY {dim}
    """)
    with engine.connect() as conn:
        rows = conn.execute(sql, {"date_from": date_from}).fetchall()
    out = []
    for r in rows:
        a = float(r[1]) if r[1] is not None else 0
        b = float(r[2]) if r[2] is not None else 0
        if b > 0:
            out.append({dim: str(r[0]), "value": a, "ref_value": b,
                        "ratio": a / b})
    return out


# ============================================================
# 预警历史
# ============================================================


def get_alert_history(rule_id: str | None = None,
                      limit: int = 100) -> list[dict]:
    """从 alerts 表查询监控预警历史."""
    alert_type_prefix = f"monitor_{rule_id[:12]}" if rule_id else "monitor_"
    from ..alerts import service as alerts_service
    all_alerts = alerts_service.list_alerts(limit=limit * 3)
    matched = []
    for a in all_alerts:
        if a.get("alert_type", "").startswith(alert_type_prefix):
            matched.append(a)
    return matched[:limit]


# ============================================================
# 数学辅助
# ============================================================


def _compare(val: float, threshold: float, comp: str) -> bool:
    if comp == "lt":
        return val < threshold
    if comp == "lte":
        return val <= threshold
    if comp == "gt":
        return val > threshold
    if comp == "gte":
        return val >= threshold
    if comp == "eq":
        return abs(val - threshold) < 1e-9
    return False


def _stddev(vals: list[float], mean: float) -> float:
    if len(vals) < 2:
        return 0.0
    variance = sum((x - mean) ** 2 for x in vals) / (len(vals) - 1)
    return math.sqrt(variance)


# ============================================================
# 评估频率
# ============================================================


def get_frequency() -> str:
    with session() as db:
        s = db.execute(
            select(bm.Setting).where(bm.Setting.key == _FREQ_SETTINGS_KEY)).scalar()
    if s and s.value:
        return s.value
    return _DEFAULT_FREQUENCY


def set_frequency(freq: str) -> None:
    with session() as db:
        existing = db.execute(
            select(bm.Setting).where(bm.Setting.key == _FREQ_SETTINGS_KEY)).scalar()
        if existing:
            existing.value = freq
        else:
            db.add(bm.Setting(key=_FREQ_SETTINGS_KEY, value=freq))


FREQ_HOURS = {"1h": 1, "2h": 2, "6h": 6, "12h": 12, "24h": 24, "72h": 72}


# ============================================================
# 预置规则种子
# ============================================================


def seed_default_rules() -> int:
    """写入预置规则（仅首次运行时）。"""
    existing = _load_rules()
    if existing:
        return 0
    now = datetime.utcnow().isoformat()
    rules = [
        {
            "name": "库存告急",
            "enabled": True,
            "table": "inventory",
            "field": "days_of_supply",
            "dimension": "sku",
            "aggregation": "avg",
            "threshold_type": "fixed",
            "comparison": "lt",
            "threshold_value": 5,
            "severity": "high",
            "scope": "supply",
            "message_template": "{sku} 可售天数仅 {value} 天，低于安全线 {threshold} 天",
        },
        {
            "name": "广告花费激增",
            "enabled": True,
            "table": "ad_performance",
            "field": "spend",
            "dimension": "sku",
            "aggregation": "sum",
            "threshold_type": "moving_avg",
            "comparison": "gt",
            "window": 7,
            "stddev_multiplier": 3,
            "direction": "above",
            "severity": "high",
            "scope": "ads",
            "message_template": "{sku} 广告花费 {value:.2f} 均值 {mean:.2f}±{sd_mult}σ={std:.2f}，触发激增预警",
        },
        {
            "name": "广告转化骤降",
            "enabled": True,
            "table": "ad_performance",
            "field": "orders",
            "dimension": "sku",
            "aggregation": "sum",
            "threshold_type": "moving_avg",
            "comparison": "lt",
            "window": 7,
            "stddev_multiplier": 2,
            "direction": "below",
            "severity": "high",
            "scope": "ads",
            "message_template": "{sku} 转化 {value} 单，低于均值 {mean} 的 {sd_mult}σ 下线",
        },
        {
            "name": "预算耗尽风险",
            "enabled": True,
            "table": "ad_budgets",
            "field": "spent",
            "dimension": "sku",
            "aggregation": "avg",
            "threshold_type": "field_ratio",
            "comparison": "gte",
            "reference_field": "monthly_budget",
            "threshold_value": 0.9,
            "severity": "medium",
            "scope": "ads",
            "message_template": "{sku} 已花费 {ratio:.0%} 月预算，触发预算耗尽预警",
        },
        {
            "name": "竞品缺货机会",
            "enabled": True,
            "table": "competitors",
            "field": "out_of_stock",
            "dimension": "sku",
            "aggregation": "max",
            "threshold_type": "fixed",
            "comparison": "gt",
            "threshold_value": 0,
            "severity": "low",
            "scope": "operations",
            "message_template": "{sku} 有竞品缺货，具备承接份额机会",
        },
        {
            "name": "CTR 异常偏低",
            "enabled": True,
            "table": "ad_performance",
            "field": "ctr",
            "dimension": "sku",
            "aggregation": "avg",
            "threshold_type": "fixed",
            "comparison": "lt",
            "threshold_value": 0.0015,
            "severity": "medium",
            "scope": "ads",
            "message_template": "{sku} CTR {value:.4f} 低于阈值 {threshold}",
        },
    ]
    for r in rules:
        r["id"] = _new_rule_id()
        r["created_at"] = now
        r["updated_at"] = now
        r["last_triggered_at"] = None
    _save_rules(rules)
    return len(rules)