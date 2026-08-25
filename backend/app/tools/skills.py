"""技能插件模板：定义可注册到工具注册表的自定义能力（工具集 v2）.

两种注册方式：
  1) 继承 Skill 并实现 run()，再调用实例 .register()；write 型只登记元数据，
     同步执行回调用 None 替换，调用须转审批；
  2) 直接 registry.register_tool(..., execute=fn) 注册带回调的只读技能。
内置技能在 register_builtins() 中统一注册，由后端启动 lifespan 调用。
"""
from __future__ import annotations

from . import registry


class Skill:
    """技能插件基类模板."""
    permission: str = "read"    # read | write
    scope: str = "operations"
    table_name: str = ""

    def __init__(self, code: str, name: str, description: str = "",
                 agent_codes: list | None = None):
        self.code = code
        self.name = name
        self.description = description
        self.agent_codes = agent_codes

    def run(self, **kwargs):
        """技能主体逻辑（只读/安全技能应在此实现；写型技能留空并靠审批落地）."""
        raise NotImplementedError

    def register(self) -> dict:
        execute = self.run if self.permission == "read" else None
        return registry.register_tool(
            code=self.code, name=self.name, description=self.description,
            permission=self.permission, scope=self.scope,
            table_name=self.table_name, agent_codes=self.agent_codes,
            execute=execute)


def register_builtins() -> None:
    """注册内置示例技能（幂等：同名覆盖）."""
    if registry.CUSTOM_TOOLS.get("store_overview"):
        return

    def _store_overview(**kwargs):
        from sqlalchemy import select
        from ..database import session
        from ..models import business as bm
        with session() as db:
            rows = db.execute(select(bm.Store)).scalars().all()
        return [{"id": s.id, "name": s.name, "platform": s.platform,
                 "market": s.market, "currency": s.currency, "active": s.active}
                for s in rows][:20]

    registry.register_tool(
        code="store_overview", name="店铺概览",
        description="只读列出全部店铺（平台 / 市场 / 币种）",
        permission="read", scope="operations", table_name="stores",
        execute=_store_overview)