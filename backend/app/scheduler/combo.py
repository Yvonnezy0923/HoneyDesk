"""跨场景组合策略编排（P2）：增长点驱动任意 Agent 发起链路.

区别于联动事件（alert-driven, 被动响应式），组合策略是 growth-driven（主动式）：
  1. 任一 Agent 识别增长点/机会后，可发起跨场景组合策略；
  2. 调度中心按策略模板编排响应 Agent 并按依赖顺序执行；
  3. 每个写操作独立审批，不因组合整体放行。

策略模板（PRD 4.4 联动矩阵的 P2 扩展）：
  - 选品机会发现 → Listing 准备 → 采购比价/备货 → 广告预算预留
  - 补货计划建议 → 成本核算 → 广告出价/预算调整
  - 竞品价格突变 → 选品报告更新 → 供应链成本重算 → 广告预算调整
"""
from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import select, desc

from .. import ids
from ..audit import service as audit_service
from ..database import session
from ..models import business as bm

# 策略模板：事件类型 → [(响应 Agent, 动作描述, 是否写操作, 依赖的上一步索引)]
# 每个策略模板是一个 DAG（有向无环图），steps 按顺序执行
STRATEGY_TEMPLATES = {
    "opportunity_discovery": {
        "name": "选品机会 → 全链路协同",
        "description": "发现选品机会后，自动拉起 Listing 准备、供应链备货比价、广告预算预留",
        "initiator": "ops_query",
        "steps": [
            {"agent": "ops_query", "action": "生成选品洞察报告", "is_write": False, "depends_on": []},
            {"agent": "ops_listing", "action": "准备 Listing 草稿", "is_write": True, "depends_on": [0]},
            {"agent": "supply_query", "action": "采购比价与备货建议", "is_write": True, "depends_on": [0]},
            {"agent": "ads_query", "action": "预算分配与出价预留", "is_write": True, "depends_on": [1, 2]},
        ],
    },
    "replenishment_trigger": {
        "name": "补货计划 → 成本与广告协同",
        "description": "生成补货计划后，联动采购比价与广告预算调整",
        "initiator": "supply_query",
        "steps": [
            {"agent": "supply_query", "action": "生成补货计划建议", "is_write": True, "depends_on": []},
            {"agent": "supply_query", "action": "供应商比价与采购建议", "is_write": False, "depends_on": [0]},
            {"agent": "ads_query", "action": "广告预算调整建议", "is_write": True, "depends_on": [0]},
        ],
    },
    "price_mutation_response": {
        "name": "竞品价格突变 → 多维度响应",
        "description": "竞品价格突变时，联动更新选品报告、成本重算、广告预算调整",
        "initiator": "ops_query",
        "steps": [
            {"agent": "ops_query", "action": "更新竞品分析与选品报告", "is_write": False, "depends_on": []},
            {"agent": "supply_query", "action": "成本与利润重算", "is_write": False, "depends_on": [0]},
            {"agent": "ads_query", "action": "出价/预算调整策略", "is_write": True, "depends_on": [0, 1]},
        ],
    },
    "review_surge_response": {
        "name": "差评/退货激增 → 多Agent响应",
        "description": "差评或退货激增时，联动运营邮件处理、广告暂停建议、供应链质检",
        "initiator": "ops_query",
        "steps": [
            {"agent": "ops_query", "action": "邮件处理与优化建议", "is_write": True, "depends_on": []},
            {"agent": "ads_query", "action": "暂停受影响SKU投放建议", "is_write": True, "depends_on": [0]},
            {"agent": "supply_query", "action": "质检与补货检查", "is_write": False, "depends_on": [0]},
        ],
    },
}


def list_templates() -> dict:
    """返回所有策略模板（供前端展示/选择）. """
    return {
        "templates": [
            {
                "key": k,
                "name": v["name"],
                "description": v["description"],
                "initiator": v["initiator"],
                "steps": [{"agent": s["agent"], "action": s["action"],
                           "is_write": s["is_write"]} for s in v["steps"]],
            }
            for k, v in STRATEGY_TEMPLATES.items()
        ]
    }


def execute_strategy(*, template_key: str, target: str, store_id: str = "",
                     origin_agent: str = "", evidence: str = "",
                     message: str = "") -> dict:
    """执行一个组合策略模板，返回编排后的联动链路与写操作审批.

    Returns:
        {ok, strategy, chain_id, events: [{agent, action, event_id, is_write}],
         writes: [{table, record_key, ...}], message}
    """
    tmpl = STRATEGY_TEMPLATES.get(template_key)
    if not tmpl:
        return {"ok": False, "message": f"策略模板 {template_key} 不存在"}

    # 1) 创建策略根事件
    strategy_id = ids.event_id()
    strategy_chain_id = strategy_id

    # 2) 按步骤编排
    events = []
    for step_idx, step in enumerate(tmpl["steps"]):
        agent = step["agent"]
        action = step["action"]
        is_write = step["is_write"]

        # 创建子事件（每个步骤对应一个联动事件）
        sub_event_id = ids.event_id()
        with session() as db:
            evt = bm.LinkageEvent(
                id=sub_event_id, event_type=f"combo_{template_key}_{step_idx}",
                target=target, origin_agent=agent,
                evidence=_fit_text(json.dumps({
                    "strategy": template_key, "step": step_idx,
                    "action": action, "is_write": is_write,
                    "evidence": evidence[:200],
                }, ensure_ascii=False)),
                status="created", chain_id=strategy_chain_id,
                seq=step_idx + 1, parent_event_id=strategy_id if step_idx > 0 else "",
                mode="auto", message=_fit_text(
                    f"组合策略「{tmpl['name']}」步骤{step_idx+1}：{action}"),
                response_agent=agent,
                suggested_actions=[{"agent": agent, "action": action,
                                    "is_write": is_write}],
                depth=step_idx, dedup_key=f"combo_{template_key}_{target}_{step_idx}",
            )
            db.add(evt)

        audit_service.record(
            op_id=sub_event_id, action=f"combo_{template_key}_step{step_idx}",
            op_type="linkage", agent_code=agent, table_name="linkage_events",
            params={"target": target, "store_id": store_id,
                    "chain_id": strategy_chain_id, "step": step_idx,
                    "action": action, "is_write": is_write},
            result="created")

        events.append({
            "step": step_idx,
            "agent": agent,
            "action": action,
            "is_write": is_write,
            "event_id": sub_event_id,
        })

        # 创建根事件（仅第一次）
        if step_idx == 0:
            with session() as db:
                root = bm.LinkageEvent(
                    id=strategy_id, event_type=f"combo_{template_key}",
                    target=target, origin_agent=origin_agent or agent,
                    evidence=_fit_text(evidence or f"组合策略「{tmpl['name']}」"),
                    status="created", chain_id=strategy_chain_id,
                    seq=0, parent_event_id="", mode="auto",
                    message=_fit_text(
                        f"启动组合策略「{tmpl['name']}」：{message or target}"),
                    response_agent=origin_agent or agent,
                    suggested_actions=[{"agent": a, "action": act}
                                       for a, act in _template_agents(tmpl)],
                    depth=0, dedup_key=f"combo_root_{template_key}_{target}",
                )
                db.add(root)

    return {
        "ok": True,
        "strategy": template_key,
        "strategy_name": tmpl["name"],
        "chain_id": strategy_chain_id,
        "events": events,
        "writes": [e for e in events if e["is_write"]],
        "message": f"组合策略「{tmpl['name']}」已启动，共 {len(events)} 个步骤，"
                   f"{len([e for e in events if e['is_write']])} 个写操作待审批",
    }


def _template_agents(tmpl: dict) -> list[tuple]:
    return [(s["agent"], s["action"]) for s in tmpl["steps"]]


def _fit_text(s: str, max_bytes: int = 40000) -> str:
    if not s:
        return s or ""
    if len(s.encode("utf-8")) <= max_bytes:
        return s
    b = s.encode("utf-8")[:max_bytes]
    while b and (b[-1] & 0xC0) == 0x80:
        b = b[:-1]
    return b.decode("utf-8", "replace") + "…[已截断]"


def list_strategies(limit: int = 50) -> list[dict]:
    """查询已执行的组合策略记录."""
    with session() as db:
        rows = db.execute(
            select(bm.LinkageEvent).where(
                bm.LinkageEvent.event_type.like("combo_%"),
                bm.LinkageEvent.seq == 0,
            ).order_by(desc(bm.LinkageEvent.created_at)).limit(limit)
        ).scalars().all()
    return [{
        "id": r.id, "chain_id": r.chain_id,
        "event_type": r.event_type,
        "target": r.target, "origin_agent": r.origin_agent,
        "message": r.message, "status": r.status,
        "created_at": r.created_at.strftime("%Y-%m-%d %H:%M:%S") if r.created_at else "",
    } for r in rows]