"""每日业务数据动态补充（服务启动时调用）：补齐缺失日期，保持与历史一致的规模.

背景：种子数据是一次性静态导入。为了让时间序列分析 / 异常捕获 / 增长挖掘始终有“今天
乃至昨天”的数据，每次服务启动时扫描各时间序列表的最新日期，把 最新日 到 今天 之间
缺失的每一天按历史日均规模补足。

覆盖：
  - sales_orders   （order_date）   逐日补齐，约 6 单/日
  - competitors    （snapshot_date）逐日补齐，约 4 条/日
  - ad_performance （stat_date）    逐日补齐，约 5 条/日
  - inventory      （无日期键）      就地刷新至当日库存水位
  - ad_budgets     （budget_period） 若当月预算缺失则补当月

幂等：按“该日期是否已有数据”判定，绝不删除或覆盖历史；重复执行安全。
"""
from __future__ import annotations

import datetime as dt
import random

from sqlalchemy import func, select

from ..database import session
from ..models import business as bm

R = random.Random()
_DAILY = [  # (模型, 日期列)  —— 需逐日补齐的业务时序表
    (bm.SalesOrder, "order_date"),
    (bm.Competitor, "snapshot_date"),
    (bm.AdPerformance, "stat_date"),
]

_COMPETITORS = ["LumineGlow", "BeautyPro", "VelvetSkin", "EcoGlam", "RadiantLab", "PureAura"]
_CAMPAIGNS = [f"Campaign-{i}" for i in range(1, 41)]
_ADGROUPS = ["auto-group", "broad-group", "exact-group", "sponsored-product", "brand-defense"]
_ADTYPES = ["auto", "manual", "broad", "phrase", "exact"]
_MATCHES = ["auto", "broad", "phrase", "exact"]


def _latest(model, col) -> dt.date | None:
    with session() as db:
        return db.execute(select(func.max(getattr(model, col)))).scalar()


def _missing_dates(model, col, today: dt.date | None = None) -> list[dt.date]:
    last = _latest(model, col)
    if last is None:                                   # 表为空：交给初始化种子，不凭空全量补
        return []
    today = today or dt.date.today()
    if last >= today:
        return []
    out, d = [], last + dt.timedelta(days=1)
    while d <= today:
        out.append(d)
        d += dt.timedelta(days=1)
    return out


def _load_axis(db):
    """读取跨表一致的键：店铺(含市场/币种/平台) 与 商品(sku→价格)."""
    stores = db.execute(select(bm.Store)).scalars().all()
    store_rows = [[s.id, s.market, s.currency, s.platform] for s in stores]
    prods = db.execute(select(bm.Product.id, bm.Product.price)).all()
    return store_rows, [p[0] for p in prods], {p[0]: p[1] for p in prods}


def _fill_sales_orders(db, day, stores, skus, prices, rng):
    n = max(2, int(rng.gauss(6.0, 2.0)))               # 约 6 单/日，匹配历史规模
    used = set()
    for _ in range(n):
        sid, market, cur, platform = rng.choice(stores)
        sku = rng.choice(skus)
        base = prices.get(sku, 10.0)
        qty = rng.choices([1, 1, 1, 2, 3], weights=[.5, .2, .15, .1, .05])[0]
        unit = round(base * rng.uniform(.9, 1.2), 2)
        ship = round(unit * rng.uniform(.08, .2), 2)
        fulfilled = rng.choices(["fba", "fbm", "tiktok_shipping"], weights=[.7, .2, .1])[0]
        st = rng.choices(["completed", "refunded", "returned", "pending"],
                         weights=[.9, .04, .04, .02])[0]
        while True:
            oid = f"{platform.upper()}-{day:%Y%m%d}-{rng.randint(10000, 99999)}"
            if oid not in used:
                used.add(oid)
                break
        db.add(bm.SalesOrder(id=oid, store_id=sid, sku=sku, order_date=day,
                             market=market, channel=platform, platform=platform,
                             currency=cur, quantity=qty, unit_price=unit,
                             revenue=round(unit * qty, 2), shipping_fee=ship,
                             fulfillment=fulfilled, order_status=st))


def _fill_competitors(db, day, stores, skus, prices, rng):
    n = max(2, int(rng.gauss(4.0, 1.4)))               # 约 4 条/日
    for _ in range(n):
        sid, _m0, _c0, _p0 = rng.choice(stores)
        sku = rng.choice(skus)
        base = prices.get(sku, 10.0)
        market = rng.choice(["US", "US", "CA", "DE", "UK"])
        platp = "amazon" if market in ("US", "CA", "DE") else "walmart"
        price = round(base * rng.uniform(.9, 1.2), 2)
        stock = rng.choices([0, rng.randint(1, 500)], weights=[.2, .8])[0]
        db.add(bm.Competitor(store_id=sid, sku=sku, market=market, platform=platp,
                             competitor_name=rng.choice(_COMPETITORS),
                             competitor_sku=f"CMP-{sku[-3:]}-{rng.randint(0, 4)}",
                             price=price, snapshot_date=day, stock=stock,
                             out_of_stock=1 if stock == 0 else 0,
                             rating=round(rng.uniform(3.4, 4.9), 1),
                             review_count=rng.randint(0, 5000),
                             monthly_sales=rng.randint(0, 3000),
                             listing_days=rng.randint(30, 1800),
                             price_trend=rng.choices(["up", "down", "stable"],
                                                     weights=[.3, .2, .5])[0]))


def _fill_ads(db, day, stores, skus, prices, rng):
    n = max(2, int(rng.gauss(5.0, 1.5)))               # 约 5 条/日
    for _ in range(n):
        sid, market, cur, platform = rng.choice(stores)
        sku = rng.choice(skus)
        base = prices.get(sku, 10.0)
        imps = rng.randint(500, 20000)
        clicks = int(imps * rng.uniform(.005, .04))
        cpc = round(rng.uniform(.2, 1.8), 2)
        spend = round(clicks * cpc, 2)
        orders = rng.choices([0, 0, rng.randint(1, 3), rng.randint(1, 8)],
                             weights=[.4, .2, .25, .15])[0]
        ad_sku = round(base * rng.uniform(.4, 1.0), 2)
        sales = round(base * orders, 2)
        ctr = round(clicks / imps, 4) if imps else 0
        roas = round(sales / spend, 2) if spend else 0
        acos = round(spend / sales, 3) if sales else 0
        db.add(bm.AdPerformance(store_id=sid, sku=sku, market=market, platform=platform,
                                campaign=rng.choice(_CAMPAIGNS), ad_group=rng.choice(_ADGROUPS),
                                target_type=rng.choice(_ADTYPES), match_type=rng.choice(_MATCHES),
                                stat_date=day, currency=cur, spend=spend, sales=sales,
                                ad_sku_sales=ad_sku, clicks=clicks, impressions=imps,
                                orders=orders, ctr=ctr, cpc=cpc, acos=acos, roas=roas,
                                status=rng.choices(["enabled", "paused", "archived"],
                                                   weights=[.85, .1, .05])[0]))


def _refresh_inventory(db, rng):
    """就地刷新当日库存水位：不新增行（inventory 无日期键），模拟每日进出库流动."""
    today = dt.date.today()
    rows = db.execute(select(bm.Inventory)).scalars().all()
    moved = 0
    for r in rows:
        if rng.random() < 0.5:
            r.available = max(0, r.available + rng.randint(-60, 80))
            r.in_transit = max(0, r.in_transit + rng.randint(-30, 60))
            r.reserved = max(0, r.reserved + rng.randint(-5, 15))
            r.damaged = max(0, r.damaged + rng.randint(0, 3))
            d = max(1, int(r.avg_daily_sales or 1))
            r.days_of_supply = max(1, int(r.available // d))
            moved += 1
        if rng.random() < 0.15:
            r.last_inbound_at = today
    return moved


def _ensure_current_month_budget(db, rng):
    """若当月 ad_budgets 缺失则补当月预算行（预算按月，非逐日）."""
    today = dt.date.today()
    period = f"{today.year}-{today.month:02d}"
    exist = db.execute(select(func.count()).select_from(bm.AdBudget)
                       .where(bm.AdBudget.period == period)).scalar()
    if exist:
        return 0
    stores = db.execute(select(bm.Store)).scalars().all()
    sku = db.execute(select(bm.Product.id)).scalars().first() or ""
    for s in stores:
        bid = round(rng.uniform(.5, 2.5), 2)
        daily = round(bid * rng.uniform(8, 25), 2)
        monthly = round(daily * 30, 2)
        db.add(bm.AdBudget(store_id=s.id, sku=sku, market=s.market, platform=s.platform,
                           budget_period=period, budget_type="daily", currency=s.currency,
                           bid=bid, daily_budget=daily, monthly_budget=monthly,
                           spent=round(monthly * rng.uniform(.3, 1), 2),
                           target_acos=rng.choice([.2, .25, .3, .35]),
                           status=rng.choices(["active", "paused"], weights=[.8, .2])[0]))
    return len(stores)


def supply_missing_daily(verbose: bool = True, today: dt.date | None = None) -> dict:
    """服务启动时调用：补齐缺失日期，返回 {表: 补齐天数}."""
    axis_cache: dict = {}
    filled: dict[str, int] = {}

    for model, col in _DAILY:
        days = _missing_dates(model, col, today)
        if not days:
            filled[model.__tablename__] = 0
            continue
        with session() as db:
            if "axis" not in axis_cache:
                axis_cache["axis"] = _load_axis(db)
            stores, skus, prices = axis_cache["axis"]
            if not stores or not skus:
                filled[model.__tablename__] = 0
                continue
            gen = {bm.SalesOrder: _fill_sales_orders,
                   bm.Competitor: _fill_competitors,
                   bm.AdPerformance: _fill_ads}[model]
            for day in days:
                gen(db, day, stores, skus, prices, R)
            db.commit()
        filled[model.__tablename__] = len(days)

    with session() as db:
        moved = _refresh_inventory(db, R)
        budgets = _ensure_current_month_budget(db, R)
        db.commit()

    if verbose:
        print(f"[daily-supply] 补齐天数(逐日表): {filled} | "
              f"库存刷新 {moved} 行 | 当月预算新增 {budgets} 行")
    return filled


if __name__ == "__main__":
    supply_missing_daily()