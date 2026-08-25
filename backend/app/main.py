"""HoneyDesk 蜜方 · 后端入口（FastAPI）."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .models import create_all, migrate_columns
from .tools import registry as tools_registry
from .api import routes_chat, routes, routes_p1


@asynccontextmanager
async def lifespan(app: FastAPI):
    from .logging_config import setup_logging
    setup_logging()                        # 每日日志落盘（log/agent/ + log/engine/，保留近10天）
    create_all()                       # 建表（幂等）
    try:
        migrate_columns()              # 新列轻量迁移
    except Exception:  # noqa: BLE001
        pass
    tools_registry.rebuild()           # 字段驱动工具
    # 工具集 v2：注册内置技能插件（幂等，失败不阻断启动）
    try:
        from .tools import skills as _skills
        _skills.register_builtins()
    except Exception:  # noqa: BLE001
        pass
    # 幂等 seed 支撑表（店铺/Agent/设置/工具持久化），失败不阻断启动
    try:
        from . import seed
        seed.seed_support()
    except Exception:  # noqa: BLE001
        pass
    # P1 新表（补货计划/预警记录）幂等补种子数据，用户无需手动操作
    try:
        from . import seed as _p1
        _p1.seed_p1()
    except Exception:  # noqa: BLE001
        pass
    # 每日业务数据补充：从最新数据补齐到今天，保证时序分析始终有当日/昨日数据
    try:
        from .data import supply
        supply.supply_missing_daily()
    except Exception:  # noqa: BLE001
        pass
    # 监控预警：预置规则种子 + 启动调度器
    try:
        from .monitor import service as _monitor_svc
        from .monitor import scheduler as _monitor_sched
        _monitor_svc.seed_default_rules()
        _monitor_sched.start()
    except Exception:  # noqa: BLE001
        pass
    yield


settings = get_settings()
app = FastAPI(title="HoneyDesk 蜜方 · Multi-Agent 工作台", version="0.1.0",
              lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(routes_chat.router)
for r in (routes.approvals, routes.artifacts, routes.dashboard, routes.audit,
          routes.knowledge, routes.tools, routes.tasks, routes.settings_router,
          routes.import_router, routes.memories, routes.compliance, routes_p1.alerts,
          routes_p1.linkage_router, routes_p1.boss, routes_p1.monitor,
          routes_p1.combo):
    app.include_router(r)


@app.get("/api/health")
def health() -> dict:
    embed = None
    try:
        from .ml.embedder import get_embedder
        embed = get_embedder()
        embed_backend = type(embed).__name__
    except Exception:  # noqa: BLE001
        embed_backend = "unavailable"
    return {"ok": True, "service": "honeydesk-backend",
            "embedding_backend": embed_backend}