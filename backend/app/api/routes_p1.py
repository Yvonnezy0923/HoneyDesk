"""P1 新增 API：预警记录 / 联动事件流 / 老板全局视图 / 监控预警."""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from ..alerts import service as alerts_service
from ..scheduler import linkage
from ..scheduler import combo as combo_strategy
from ..dashboard import service as dashboard_service
from ..monitor import service as monitor_service

alerts = APIRouter(prefix="/api/alerts", tags=["alerts"])
linkage_router = APIRouter(prefix="/api/linkage", tags=["linkage"])
boss = APIRouter(prefix="/api/boss", tags=["boss"])
monitor = APIRouter(prefix="/api/monitor", tags=["monitor"])


# ────────────────────────── 预警记录 ──────────────────────────
@alerts.get("")
def list_alerts(scope: str | None = None, alert_type: str | None = None,
                status: str | None = None, sku: str | None = None):
    return {"alerts": alerts_service.list_alerts(scope, alert_type, status, sku)}


@alerts.get("/stats")
def alerts_stats():
    return alerts_service.stats()


class AlertStatusBody(BaseModel):
    status: str
    resolution: str = ""


@alerts.post("/{alert_id}/status")
def update_alert(alert_id: str, body: AlertStatusBody):
    return alerts_service.update_status(alert_id, body.status, body.resolution)


# ────────────────────────── 联动事件流 ──────────────────────────
@linkage_router.get("/events")
def linkage_events(limit: int = 100):
    return {"events": linkage.list_events(limit=limit)}


@linkage_router.get("/chains")
def linkage_chains(limit: int = 50):
    return {"chains": linkage.list_chains(limit=limit)}


@linkage_router.get("/stats")
def linkage_stats():
    return linkage.stats()


# ────────────────────────── 老板全局视图（FR-DB-09，只读） ──────────────────────────
@boss.get("/view")
def boss_view():
    return dashboard_service.boss_view()


# ────────────────────────── 监控预警规则 ──────────────────────────
class RuleBody(BaseModel):
    name: str
    enabled: bool = True
    table: str
    field: str
    dimension: str = "sku"
    aggregation: str = "avg"
    threshold_type: str = "fixed"
    comparison: str = "lt"
    threshold_value: float | None = None
    reference_field: str | None = None
    window: int | None = None
    stddev_multiplier: float | None = None
    direction: str | None = None
    pct_threshold: float | None = None
    severity: str = "medium"
    scope: str = "supply"
    message_template: str = ""


@monitor.get("/fields")
def monitor_fields():
    return {"tables": monitor_service.all_fields()}


@monitor.get("/rules")
def monitor_rules():
    return {"rules": monitor_service.list_rules()}


@monitor.get("/rules/{rule_id}")
def monitor_rule(rule_id: str):
    r = monitor_service.get_rule(rule_id)
    return {"rule": r} if r else {"error": "规则不存在"}


@monitor.post("/rules")
def monitor_create_rule(body: RuleBody):
    rule = monitor_service.save_rule(body.model_dump(exclude_none=True))
    return {"rule": rule}


@monitor.put("/rules/{rule_id}")
def monitor_update_rule(rule_id: str, body: RuleBody):
    rule = monitor_service.save_rule({**body.model_dump(exclude_none=True),
                                      "id": rule_id})
    return {"rule": rule}


@monitor.delete("/rules/{rule_id}")
def monitor_delete_rule(rule_id: str):
    ok = monitor_service.delete_rule(rule_id)
    return {"ok": ok}


@monitor.post("/rules/{rule_id}/evaluate")
def monitor_evaluate_rule(rule_id: str):
    triggered = monitor_service.evaluate_rule(rule_id)
    return {"triggered": triggered}


@monitor.post("/rules/evaluate-all")
def monitor_evaluate_all():
    triggered = monitor_service.evaluate_all_rules()
    return {"triggered": triggered}


@monitor.get("/rules/{rule_id}/data")
def monitor_rule_data(rule_id: str, days: int = 30):
    data = monitor_service.get_timeseries(rule_id, days)
    return data or {"error": "规则不存在或无数据"}


@monitor.get("/history")
def monitor_history(rule_id: str | None = None, limit: int = 100):
    return {"history": monitor_service.get_alert_history(rule_id, limit)}


@monitor.get("/frequency")
def monitor_get_frequency():
    return {"frequency": monitor_service.get_frequency()}


class FrequencyBody(BaseModel):
    frequency: str


@monitor.post("/frequency")
def monitor_set_frequency(body: FrequencyBody):
    freq = body.frequency
    if freq not in monitor_service.FREQ_HOURS:
        return {"error": f"无效频率，可选: {', '.join(monitor_service.FREQ_HOURS.keys())}"}
    monitor_service.set_frequency(freq)
    return {"ok": True, "frequency": freq}


# ────────────────────────── 组合策略（P2 跨场景） ──────────────────────────
combo = APIRouter(prefix="/api/combo", tags=["combo"])


@combo.get("/templates")
def combo_templates():
    return combo_strategy.list_templates()


class ComboExecuteBody(BaseModel):
    template_key: str
    target: str
    store_id: str = ""
    origin_agent: str = ""
    evidence: str = ""
    message: str = ""


@combo.post("/execute")
def combo_execute(body: ComboExecuteBody):
    return combo_strategy.execute_strategy(
        template_key=body.template_key, target=body.target,
        store_id=body.store_id, origin_agent=body.origin_agent,
        evidence=body.evidence, message=body.message)


@combo.get("/strategies")
def combo_strategies(limit: int = 50):
    return {"strategies": combo_strategy.list_strategies(limit=limit)}