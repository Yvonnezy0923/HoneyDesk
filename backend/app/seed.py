"""初始化：建表 + 支撑表 + 示例知识库索引（幂等，可重复执行）.

用法：
  docker compose run --rm backend python -m app.seed
  或本地：cd backend && python -m app.seed
"""
from __future__ import annotations

from datetime import datetime, timedelta

from .config import get_settings
from .database import session
from .models import business as bm
from .models import create_all
from .rag.service import get_rag
from .tools import registry as tools_reg


def _seed_stores(db) -> None:
    # 表已由 create_all() 保证存在（honey_system.stores）；按主键增查保证幂等
    if db.get(bm.Store, "store_1001") is None:
        db.add(bm.Store(id="store_1001", name="蜜方美妆旗舰店",
                        platform="amazon", market="US"))


def _seed_agents(db) -> None:
    agents = [
        dict(id="ops_query", name="运营 Agent", code="ops_query", scope="operations",
             description="销售/订单/退货/竞品多维度汇总与下钻，输出经营结论；可依据分析结果生成写审批或修正数据",
             reads=["sales_orders", "products", "competitors", "product_materials", "listings"],
             writes=[]),
        dict(id="ops_listing", name="Listing Agent", code="ops_listing", scope="operations",
             description="基于产品资料批量生成/优化 Listing（标题/五点/描述），写操作生成审批后落库",
             reads=["product_materials"], writes=["listings"]),
        dict(id="supply_query", name="供应链 Agent", code="supply_query", scope="supply",
             description="库存水位/安全库存核查、在途到货预估、缺货风险与补货优先级",
             reads=["inventory"], writes=[]),
        dict(id="ads_query", name="广告 Agent", code="ads_query", scope="ads",
             description="广告花费与预算执行、ROI/ACOS/ROAS 分析、转化下钻，以及出价 bid 与预算调优",
             reads=["ad_performance", "ad_budgets"], writes=[]),
    ]
    for a in agents:
        row = db.get(bm.AgentRecord, a["id"])
        if row is None:
            db.add(bm.AgentRecord(
                id=a["id"], name=a["name"], code=a["code"], scope=a["scope"],
                description=a["description"], reads=a["reads"], writes=a["writes"]))
        # 已存在的行同步场景化名称与业务能力描述（仅更新展示字段，保持 id/code/读写权限不变）
        elif (row.name != a["name"] or row.description != a["description"]):
            row.name = a["name"]
            row.description = a["description"]
    if db.get(bm.Setting, "embedding_backend_actual") is None:
        db.add(bm.Setting(key="embedding_backend_actual", value="pending"))


def _seed_sample_kb(db) -> None:
    """写入一份示例知识库文档并索引，保证 RAG 开箱可用."""
    doc = db.query(bm.KnowledgeDocument).filter_by(source="sample_brand").first()
    if doc:
        return
    text = (
        "我们的品牌【蜜方 HONEY】主营天然温和的美妆护肤产品，面向追求健康护肤的年轻女性。"
        "核心卖点：含玻尿酸、烟酰胺与维C，深层补水、提亮肤色；主打无动物实验、无尼泊金、低刺激配方。"
        "目标市场为北美（美国/加拿大），通常以套装与优惠组合促进复购。"
        "月度促销节奏：月初新品上架+站内优惠券，月中品类满减，月末清仓。"
        "Listing 优化要点：标题前80字符放核心关键词，五点覆盖材质/功效/适用人群/质保，描述强调成分与使用效果。"
    )
    from . import ids
    doc_id = ids.doc_id()
    rag = get_rag()
    # 切分为多段（每段 80 字左右），模拟语义 chunk
    step = 80
    chunks = [text[i:i + step] for i in range(0, len(text), step)]
    try:
        n = rag.ingest_chunks(doc_id, "蜜方品牌知识与Listing规范", "sample_brand",
                              "general", chunks)
    except Exception as e:  # noqa: BLE001
        n = 0
        doc_id = f"sample_brand-failed:{e}"[:40]
    db.add(bm.KnowledgeDocument(
        id=doc_id, title="蜜方品牌知识与Listing规范", doc_type="document",
        scope="general", source="sample_brand", chunk_count=n,
        status="ready" if n else "failed"))


def seed_support() -> None:
    """幂等初始化支撑表（店铺/Agent/设置/工具持久化），不依赖 Qdrant."""
    tools_reg.rebuild()
    with session() as db:
        _seed_stores(db)
        _seed_agents(db)
        # 持久化工具清单
        for t in tools_reg.list_tools():
            row = db.get(bm.ToolRecord, t["code"])
            if row is None:
                db.add(bm.ToolRecord(
                    id=t["code"], code=t["code"], name=t["name"],
                    table_name=t["table_name"], fields=t["fields"],
                    permission=t["permission"], description=t["description"],
                    agent_codes=t["agent_codes"]))


def run() -> None:
    create_all()
    print("[seed] 建表完成（业务 + 审计同库）")
    seed_support()
    with session() as db:          # 示例知识库（依赖 Qdrant，失败仍继续）
        _seed_sample_kb(db)
    print("[seed] 支撑表（店铺/Agent/工具/示例知识库）已就绪")
    print("[seed] 完成。若尚未导入业务数据，请执行 backend/db/seed_data.sql")


# ────────────────────────── P1 新表种子数据 ──────────────────────────
# 补货计划（replenishment_plans）与预警记录（alerts）由 Agent 动态写入。
# 为让老板全局视图 / 预警看板开箱即用，服务启动时在【表为空】的前提下幂等补一份
# 演示数据；表一旦有内容便绝不覆盖（Agent 运行后动态增长）。
_P1_ALERT_DEMO = [
    # (alert_type, scope, severity, title, message)
    ("inventory_shortage", "supply", "high", "库存告急",
     "近30天日均销波动，可售库存低于安全库存建议线，建议补货"),
    ("spend_surge", "ads", "high", "广告花费激增",
     "今日广告花费显著高于近7日均值，需核查投放词与素材"),
    ("conversion_drop", "ads", "high", "广告转化骤降",
     "今日出单明显低于近期日均，需核查 Listing 与竞品价格"),
    ("budget_depleted", "ads", "medium", "广告预算将耗尽",
     "当月广告花费已达月度预算 90%，请注意控制"),
    ("ctr_abnormal", "ads", "medium", "广告 CTR 异常偏低",
     "曝光充足但点击率低于阈值，需优化主图与标题"),
]


def seed_p1(now=None) -> dict:
    """P1 新表幂等补种子数据：仅当表为空时写入（预警记录 + 补货计划）."""
    from sqlalchemy import select, func
    from . import ids
    from datetime import date, timedelta
    from .models import business as bm

    seeded = {"alerts": 0, "replenishment_plans": 0}
    with session() as db:
        skus = [r[0] for r in db.execute(select(bm.Product.id)).all()]
        demo_skus = skus[:4] if skus else ["SKU-1001"]
        store = db.execute(select(bm.Store.id)).scalars().first() or "store_1001"

        # ── 预警记录：表为空时才补近 7 天若干条
        exists = db.execute(select(func.count()).select_from(bm.AlertRecord)).scalar() or 0
        if exists == 0:
            prev = date.today() - timedelta(days=6)
            for i, (atype, scope, sev, title, msg) in enumerate(_P1_ALERT_DEMO):
                d = prev + timedelta(days=i)
                sku = demo_skus[i % len(demo_skus)]
                alert = bm.AlertRecord(
                    id=ids.op_id().replace("OP", "ALT"),
                    alert_type=atype, scope=scope, store_id=store, sku=sku,
                    market="US", severity=sev, title=f"{title}：{sku}", message=msg,
                    evidence={"demo": True, "date": d.isoformat()},
                    status="new", source_task="seed_p1")
                # 让预警记录有可审计的时间戳（幂等补充演示数据）
                alert.created_at = __astime(d)
                alert.updated_at = __astime(d)
                db.add(alert)
                seeded["alerts"] += 1

        # ── 补货计划：表为空时补若干历史计划
        exists2 = db.execute(select(func.count()).select_from(bm.ReplenishmentPlan)).scalar() or 0
        if exists2 == 0 and skus:
            for i, sku in enumerate(demo_skus[:3]):
                plan = bm.ReplenishmentPlan(
                    store_id=store, sku=sku, market="US", warehouse="US-LAX",
                    plan_date=date.today() - timedelta(days=2),
                    suggested_qty=120 + i * 40,
                    suggested_arrival=date.today() + timedelta(days=14),
                    days_of_supply=12, avg_daily_sales=6.0, available=40,
                    in_transit=30, safety_stock=25, lead_days=14,
                    shortage_risk="medium",
                    assumptions={"target_days": 30, "demo": True},
                    status="confirmed", source_task="seed_p1")
                plan.created_at = __astime(date.today() - timedelta(days=2))
                plan.updated_at = __astime(date.today() - timedelta(days=2))
                db.add(plan)
                seeded["replenishment_plans"] += 1
    if seeded["alerts"] or seeded["replenishment_plans"]:
        print(f"[seed-p1] 补货计划/预警记录种子：{seeded}")
    return seeded


def __astime(d):
    from datetime import datetime
    return datetime(d.year, d.month, d.day, 9, 30, 0)


if __name__ == "__main__":
    run()