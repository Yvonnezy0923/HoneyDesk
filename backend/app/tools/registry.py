"""工具注册表：读工具（字段驱动）+ 写工具（声明式）+ 技能插件（运行时注册）.

工具集 v2（P1）：
  + 只读工具：由业务表字段自动扫描生成（P0 保留）；
  + 可写工具：声明式白名单，供 Agent 声明可写目标。真正的写入仍须经「审批」
    落库（execute 缺失），不脱离写操作审批约束；
  + 技能插件：register_tool() 注册自定义能力，带 execute 回调的只读/安全技能可被
    /api/tools/run 同步调用；无回调的写型技能仅作为元数据（走审批）。
"""
from __future__ import annotations

from typing import Callable

from ..data import access
from ..models.business import TABLE_META

READ_TOOLS: dict[str, dict] = {}
WRITE_TOOLS: dict[str, dict] = {}
CUSTOM_TOOLS: dict[str, dict] = {}


def rebuild() -> None:
    """根据业务表重建只读工具清单 + 预置可写工具声明."""
    global READ_TOOLS
    READ_TOOLS = {}
    for table in access.MODEL_MAP:
        meta = TABLE_META.get(table, {"name": table, "scope": "general", "label": ""})
        scope = meta.get("scope", "general")
        code = f"query_{table}"
        READ_TOOLS[code] = {
            "code": code,
            "name": f"查询{meta.get('name', table)}",
            "table_name": table,
            "permission": "read",
            "scope": scope,
            "description": f"只读查询【{meta.get('name', table)}】，支持按 SKU / 店铺 / 日期范围过滤",
            "agent_codes": _agent_codes_for_scope(scope),
            "fields": access.list_fields(table),
            "kind": "read",
        }
    global WRITE_TOOLS
    WRITE_TOOLS = {}
    for wt in _PRESET_WRITES:
        scope = wt["scope"]
        WRITE_TOOLS[wt["code"]] = {
            "code": wt["code"], "name": wt["name"],
            "table_name": wt["table_name"], "scope": scope,
            "permission": "write", "kind": "write",
            "description": wt["description"],
            "agent_codes": _agent_codes_for_scope(scope),
            "fields": access.list_fields(wt["table_name"]),
        }


# 预置可写工具（写操作不经工具自动执行，仍走审批流）
_PRESET_WRITES = [
    {"code": "write_listing", "name": "发布/更新 Listing", "table_name": "listings",
     "scope": "operations", "description": "将 Listing 生成为待发布记录（写入须人工审批）"},
    {"code": "write_replenishment", "name": "生成补货计划", "table_name": "replenishment_plans",
     "scope": "supply", "description": "提交补货计划记录（写入须人工审批）"},
    {"code": "write_bid", "name": "调整广告出价/预算", "table_name": "ad_budgets",
     "scope": "ads", "description": "提交出价/预算调整记录（写入须人工审批）"},
]


def _agent_codes_for_scope(scope: str) -> list[str]:
    return {
        "operations": ["ops_query", "ops_listing"],
        "supply": ["supply_query"],
        "ads": ["ads_query"],
        "general": ["ops_query", "ops_listing"],
    }.get(scope, [])


def register_tool(*, code: str, name: str, description: str = "",
                  permission: str = "read", scope: str = "operations",
                  table_name: str = "", agent_codes: list | None = None,
                  execute: Callable | None = None) -> dict:
    """注册自定义技能/工具（技能插件模板入口）.

    - permission="write" 或不提供 execute 时，仅登记元数据，调用方须将其写入诉求
      转为审批，不直接执行；
    - 仅读/安全型技能可携带 execute 回调，可被 /api/tools/run 同步调用。
    """
    code = (code or "").strip()
    if not code:
        return {"ok": False, "message": "工具 code 不能为空"}
    ags = [str(a) for a in (agent_codes or []) if a] or _agent_codes_for_scope(scope)
    CUSTOM_TOOLS[code] = {
        "code": code, "name": name or code, "description": description or "",
        "permission": permission, "scope": scope, "table_name": table_name,
        "agent_codes": ags, "fields": [], "kind": "custom",
        "executable": execute is not None,
        "_execute": execute,   # 内部回调，不随 API 输出
    }
    return {"ok": True, "tool": _public(CUSTOM_TOOLS[code])}


def call_tool(code: str, **kwargs) -> dict:
    """同步调用注册的自定义工具（仅 executable=True 的只读/安全技能）."""
    t = CUSTOM_TOOLS.get(code)
    if not t:
        return {"ok": False, "message": "工具不存在"}
    fn = t.get("_execute")
    if t.get("permission") == "write" or fn is None:
        return {"ok": False, "message": f"{t['name']} 为写操作，不可直接执行，请提交审批"}
    try:
        res = fn(**kwargs)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "message": str(e)}
    return {"ok": True, "result": res}


def list_tools() -> list[dict]:
    if not READ_TOOLS:
        rebuild()
    out = []
    for t in READ_TOOLS.values():
        out.append(dict(t))
    for t in WRITE_TOOLS.values():
        out.append(dict(t))
    for t in CUSTOM_TOOLS.values():
        out.append(_public(t))
    out.sort(key=lambda x: 0 if x.get("permission") == "write" else 1)
    return out


def update_tool(code: str, *, name: str = None, description: str = None,
                permission: str = None, scope: str = None, table_name: str = None,
                agent_codes: list = None) -> dict:
    """更新已有工具的元数据（名称/描述/权限/作用域等）。"""
    t = READ_TOOLS.get(code) or WRITE_TOOLS.get(code) or CUSTOM_TOOLS.get(code)
    if not t:
        return {"ok": False, "message": f"工具 {code} 不存在"}
    if name is not None:
        t["name"] = name
    if description is not None:
        t["description"] = description
    if permission is not None:
        t["permission"] = permission
    if scope is not None:
        t["scope"] = scope
    if table_name is not None:
        t["table_name"] = table_name
    if agent_codes is not None:
        t["agent_codes"] = agent_codes
    return {"ok": True, "tool": _public(t)}


def get_tool(code: str) -> dict:
    if not READ_TOOLS:
        rebuild()
    t = READ_TOOLS.get(code) or WRITE_TOOLS.get(code) or CUSTOM_TOOLS.get(code)
    return _public(t) if t else {}


def _public(t: dict) -> dict:
    return {k: v for k, v in t.items() if not k.startswith("_")}