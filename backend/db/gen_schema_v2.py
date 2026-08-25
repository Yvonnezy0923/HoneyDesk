"""从 ORM 模型生成丰富的跨境电商业务库 V2 建表 SQL + 维度丰富种子数据.

输出 backend/db/schema_v2.sql —— honey_desk 8 张业务表 + honey_system.stores。
DDL 由 SQLAlchemy 模型自动生成，保证与后端字段完全一致（避免字段匹配不上）。
"""
from __future__ import annotations

import datetime as dt
import json
import random
from pathlib import Path


def zh(text: str) -> str:
    """含非 ASCII 的字符串 → CONVERT(X'hex' USING utf8mb4); 否则原样引号."""
    if all(ord(ch) < 128 for ch in text):
        return "'" + text.replace("'", "''") + "'"
    return "CONVERT(X'" + text.encode("utf-8").hex() + "' USING utf8mb4)"


Z = {
    # 常用中文值（避免手写 hex）
    "商品表": "商品表", "产品资料表": "产品资料表", "Listing表": "Listing表",
    "销售订单表": "销售订单表", "竞品快照表": "竞品快照表", "库存表": "库存表",
    "广告数据表": "广告数据表", "广告预算表": "广告预算表",
}


def val(v):
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, dt.datetime):
        return "'" + v.strftime("%Y-%m-%d %H:%M:%S") + "'"
    if isinstance(v, dt.date):
        return "'" + v.strftime("%Y-%m-%d") + "'"
    if isinstance(v, (list, dict)):
        return "'" + json.dumps(v, ensure_ascii=True).replace("'", "''") + "'"
    return zh(str(v))


R = random.Random(20260823)

# ───────────── 维度池（跨表一致键） ─────────────
STORES = [  # id, name, platform, market, group_, currency, tz
    ("store_1001", "HoneyMifang US (Amazon)", "amazon", "US", "NA", "USD", "America/Los_Angeles"),
    ("store_1002", "HoneyMifang CA (Amazon)", "amazon", "CA", "NA", "CAD", "America/Toronto"),
    ("store_1003", "HoneyMifang US (TikTok)", "tiktok", "US", "NA", "USD", "America/New_York"),
    ("store_1004", "HoneyMifang DE (Amazon)", "amazon", "DE", "EU", "EUR", "Europe/Berlin"),
    ("store_1005", "HoneyMifang US (Walmart)", "walmart", "US", "NA", "USD", "America/Chicago"),
]
STORE_MARKET = {s[0]: s[3] for s in STORES}
STORE_CURR = {s[0]: s[5] for s in STORES}

WAREHOUSES = {  # code -> (name, type, region, market)
    "US-LAX": ("US Los Angeles FC", "overseas", "NA", "US"),
    "US-JFK": ("US New York FC", "overseas", "NA", "US"),
    "CA-VAN": ("CA Vancouver FC", "overseas", "NA", "CA"),
    "DE-FRA": ("DE Frankfurt FC", "overseas", "EU", "DE"),
    "UK-LIV": ("UK Liverpool FC", "overseas", "EU", "UK"),
    "CN-SH":  ("CN Shanghai DC", "domestic", "APAC", ""),
}
WH_BY_MARKET = {"US": ["US-LAX", "US-JFK"], "CA": ["CA-VAN"],
                "DE": ["DE-FRA"], "UK": ["UK-LIV"], "": ["CN-SH"]}

PRICE_MARKET = {"US": 1.0, "CA": 1.25, "DE": 0.92, "UK": 0.95, "JP": 140, "": 1.0}
COST_MARKET = {"US": 1.0, "CA": 1.25, "DE": 0.92, "UK": 0.95, "JP": 1.0, "": 1.0}
LANG_BY_MARKET = {"US": "en", "CA": "en", "DE": "de", "UK": "en", "JP": "ja"}

PLATFORM_BY_STORE = {
    "store_1001": "amazon", "store_1002": "amazon", "store_1003": "tiktok",
    "store_1004": "amazon", "store_1005": "walmart",
}

# ────────── 商品目录生成（跨表一致键来源） ──────────
# (cat, subcat, price_min, price_max, cost_min, cost_max, w_min, w_max, v_min, v_max, case_min, case_max, shelf)
SUBCATS = [
    ("美妆", "洗面奶", 8, 16, .12, .26, 90, 150, 140, 220, 48, 72, 900),
    ("美妆", "化妆水", 10, 20, .14, .30, 140, 220, 200, 300, 36, 60, 900),
    ("美妆", "防晒",   9, 20, .15, .30, 120, 200, 180, 270, 48, 72, 700),
    ("美妆", "精华液", 16, 30, .18, .32, 40, 90, 110, 190, 72, 120, 900),
    ("美妆", "眼霜",   14, 26, .17, .30, 35, 70, 100, 170, 80, 120, 900),
    ("美妆", "面膜",   6, 13, .13, .24, 160, 260, 240, 360, 90, 120, 700),
    ("美妆", "面霜",   13, 24, .16, .30, 150, 240, 200, 300, 48, 72, 900),
    ("美妆", "唇膏",   5, 11, .13, .24, 25, 55, 70, 120, 120, 160, 700),
    ("美妆", "妆前乳", 11, 19, .15, .28, 70, 120, 130, 210, 60, 96, 900),
    ("个护", "洗发水", 9, 16, .14, .26, 280, 420, 380, 520, 24, 40, 900),
    ("个护", "卸妆",   8, 14, .14, .25, 130, 200, 180, 260, 60, 84, 900),
    ("个护", "身体乳", 8, 15, .14, .25, 220, 320, 300, 420, 36, 60, 900),
    ("个护", "洁面泡沫", 7, 13, .13, .24, 120, 190, 160, 240, 60, 96, 900),
    ("个护", "磨砂膏", 8, 14, .14, .25, 200, 300, 260, 400, 48, 72, 900),
    ("个护", "润唇膏", 4, 9, .12, .22, 20, 45, 60, 110, 160, 240, 700),
]
SERIES_POOL = {
    "洗面奶": ["Amino Cleanser", "Detox Clay", "Gentle Pure", "Sea Kelp Clean", "Matcha Wash"],
    "化妆水": ["Niacin Bright", "HA Hydra", "Rose Essence", "VitC Pore", "Ceramide Mist"],
    "防晒":   ["SPF50 Shield", "SPF50 Aqua", "UV Mineral", "Tone-Up Sun", "Sport Shield"],
    "精华液": ["VitC Glow", "Retinol Night", "Hyaluronic Boost", "Snail Repair", "AHA Renew"],
    "眼霜":   ["Collagen Firm", "Caffeine Lift", "Eye Bright", "Retinol Eye", "Green Tea Firm"],
    "面膜":   ["HA Hydra", "Tea Tree", "Collagen Sheet", "Charcoal Detox", "Rose Clay"],
    "面霜":   ["Niacin Bright", "Ceramide Rich", "Aqua Gel", "Night Repair", "Barrier Care"],
    "唇膏":   ["Lip Care", "Shea Butter", "Tinted Balm", "Mint Lip", "Peptide Lip"],
    "妆前乳": ["Pore Smooth", "Blur Primer", "Hydra Primer", "Silk Base", "Mattify"],
    "洗发水": ["Repair Hair", "Volume Boost", "Scalp Care", "Color Lock", "Herbal Clean"],
    "卸妆":   ["Cleanse Fresh", "Oil Cleanse", "Micellar Wash", "Balm Cleanse", "Sensitive Clean"],
    "身体乳": ["Shea Body", "Oat Repair", "Aloe Fresh", "Bright Body", "Cocoa Silk"],
    "洁面泡沫": ["Foam Pure", "Low-PH Foam", "Milk Foam", "Carbon Foam", "Acne Care"],
    "磨砂膏": ["Sugar Scrub", "Coffee Body", "Salt Glow", "Sea Salt", "Honey Buff"],
    "润唇膏": ["Overnight Lip", "SPF15 Lip", "Color Care", "Med Repair", "Herbal Lip"],
}
# market -> 在该市场发货/运营的店铺（保证 inventory/ad 的 store_id 有效）
MARKET_STORES = {
    "US": ["store_1001", "store_1003", "store_1005"],
    "CA": ["store_1002"],
    "DE": ["store_1004"],
    "UK": ["store_1001"],
}
# P1 调整：真实业务场景 —— 15 个产品种类（subcat），每个 2 个 SKU，共 30 个 SKU。
# 该量级可保证任意 topN/limit 聚类（如 circle 按 SKU 聚类）在展示上限内全量可见，
# 不会因数据量过大导致尾端 SKU 永远无法被看到。
N_SKU = 30


def build_catalogue(n=N_SKU):
    res, price_map = [], {}
    for i in range(n):
        cat, sub, pmin, pmax, cmin, cmax, wmin, wmax, vmin, vmax, cmin_, cmax_, shelf = SUBCATS[i % len(SUBCATS)]
        price = round(R.uniform(pmin, pmax), 2)
        cost = round(price * R.uniform(cmin, cmax), 2)
        weight = round(R.uniform(wmin, wmax), 1)
        vol = round(R.uniform(vmin, vmax), 1)
        case = R.randint(cmin_, cmax_)
        series = R.choice(SERIES_POOL[sub])
        sku = f"SKU-{10000 + i + 1}"
        res.append((sku, cat, sub, "HoneyMifang", series, price, cost, weight, vol, case, shelf))
        price_map[sku] = price
    return res, price_map


SKUS, SKU_PRICE = build_catalogue()
BASE_BY_SKU = {b[0]: b for b in SKUS}
CATEGORIES = [("美妆", "skincare"), ("个护", "personal-care")]
_ALL_STORES = [s[0] for s in STORES]


def _market_of(sid: str) -> str:
    return STORE_MARKET[sid]


def _platform_of(sid: str) -> str:
    return PLATFORM_BY_STORE[sid]


# ───────────── 各表生成器 ─────────────
def gen_store():
    return [[s[0], s[1], s[2], s[3], s[4], s[5], s[6], 1] for s in STORES]


def gen_products():
    rows = []
    for sku, cat, sub, brand, series, price, cost, w, v, case, shelf in SKUS:
        market = R.choices(["US", "US", "CA", "DE"], weights=[.55, .2, .12, .13])[0]  # 主打市场
        sid = R.choice(MARKET_STORES[market])
        p = round(price * PRICE_MARKET[market], 2)
        c = round(cost * COST_MARKET[market], 2)
        launch = dt.date(2025, 1, 1) + dt.timedelta(days=R.randint(0, 500))
        asin = "B0" + "".join(R.choices("ABCDEFGHJKMNPQRSTUVWXYZ23456789", k=8))
        bc = "0" + "".join(R.choices("1234567890", k=11))
        status = R.choices(["active", "active", "active", "draft", "discontinued"],
                           weights=[.5, .2, .2, .07, .03])[0]
        rows.append([sku, sid, f"{brand} {sub} {sku[-2:]}", cat, sub, brand, series,
                     p, c, w, v, asin, bc, launch, case, status])
    return rows


def gen_materials():
    rows = []
    MAT_MARKETS = ["US", "DE", "JP", "UK"]
    for sku, cat, sub, brand, series, price, cost, w, v, case, shelf in SKUS:
        for market in R.sample(MAT_MARKETS, R.choice([1, 2])):
            lang = LANG_BY_MARKET.get(market, "en")
            feature = zh("天然萃取 · 温和无刺激 · 敏感肌适用 · 无动物实验")
            usage_s = zh("取适量均匀涂抹于肌肤，每日早晚使用")
            mats = zh("玻尿酸 / 烟酰胺 / 维生素C / 神经酰胺 / 角鲨烷")
            sp = zh("深层补水 · 提亮肤色 · 修护屏障 · 长效保湿")
            aud = zh("20-45岁追求健康护肤的年轻女性，注重成分安全")
            kw = zh("保湿 提亮 敏感肌 温和 无添加 纯净美妆")
            specs = f"{round(R.choice([30.0, 50.0, 60.0, 100.0]), 1)}ml/{lang}"
            cert = R.choice(["FDA", "ECOCERT", "EU-COSMOS"])
            net = round(R.choice([30.0, 50.0, 60.0, 100.0]), 1)
            rows.append(["store_1001", sku, f"{brand} {sub} {sku[-2:]} - {lang}", market, lang,
                         cat, sub, brand, series, feature, usage_s, mats, sp, aud, kw, specs,
                         net, shelf, cert])
    return rows


def gen_listings():
    rows = []
    SLOTS = [("store_1001", "US", "en"), ("store_1001", "DE", "de"), ("store_1004", "DE", "de"),
             ("store_1005", "US", "en"), ("store_1003", "US", "en"), ("store_1002", "CA", "en"),
             ("store_1001", "UK", "en")]
    for sku, cat, sub, brand, series, price, cost, w, v, case, shelf in SKUS:
        for sid, mk, lang in R.sample(SLOTS, R.choice([1, 2])):
            title = f"{brand} {sub} {sku[-2:]} | {mk} Version"
            bp = [f"{brand} {sub} {sku[-2:]} for {mk}", "Cruelty-free & Low-irritant",
                  "Hyaluronic Acid / Niacinamide", "Suitable for sensitive skin", "Daily skincare"]
            desc = f"{brand} {sub} for the {mk} market, cruelty-free formula."
            terms = f"{brand},{sub},skincare,{lang}"
            platform = "tiktok" if sid == "store_1003" else ("walmart" if sid == "store_1005" else "amazon")
            status = R.choices(["published", "draft", "pending"], weights=[.75, .15, .10])[0]
            rows.append([sid, sku, mk, platform, lang, title, bp, desc, terms, R.randint(1, 3), status])
    return rows


def gen_sales_orders(target=2600):
    rows = []
    oid = 0
    for _ in range(target):
        oid += 1
        sku = R.choice(SKUS)[0]
        sid = R.choice(_ALL_STORES)
        market = _market_of(sid)
        platform = _platform_of(sid)
        cur = STORE_CURR[sid]
        d = dt.date(2025, 7, 1) + dt.timedelta(days=R.randint(0, 416))
        qty = R.choices([1, 1, 1, 2, 3], weights=[.5, .2, .15, .1, .05])[0]
        unit = round(SKU_PRICE[sku] * PRICE_MARKET[market] * R.uniform(.95, 1.15), 2)
        ship = round(unit * R.uniform(.08, .2), 2)
        fulfillment = R.choices(["fba", "fbm", "tiktok_shipping"], weights=[.7, .2, .1])[0]
        st = R.choices(["completed", "refunded", "returned", "pending"],
                       weights=[.9, .04, .04, .02])[0]
        order_id = f"{platform.upper()}-{d.strftime('%Y%m%d')}-{oid:06d}"
        rows.append([order_id, sid, sku, d, market, platform, platform, cur,
                     qty, unit, round(unit * qty, 2), ship, fulfillment, st])
    return rows


def gen_competitors():
    cmp_names = ["LumineGlow", "BeautyPro", "VelvetSkin", "EcoGlam", "RadiantLab", "PureAura"]
    rows = []
    for sku, cat, sub, brand, series, price, cost, w, v, case, shelf in SKUS:
        for _ in range(R.choice([1, 2])):
            cname = R.choice(cmp_names)
            market = R.choice(["US", "US", "CA", "DE", "UK"])
            platform = "amazon" if market in ("US", "CA", "DE") else "walmart"
            cprice = round(SKU_PRICE[sku] * PRICE_MARKET[market] * R.uniform(.9, 1.2), 2)
            d = dt.date(2025, 8, 1) + dt.timedelta(days=R.randint(0, 380))
            stock = R.choices([0, R.randint(1, 500)], weights=[.2, .8])[0]
            sid = R.choice(_ALL_STORES)
            rows.append([sid, sku, market, platform, cname, f"CMP-{sku[-3:]}-{R.randint(0, 4)}",
                         cprice, d, stock, 1 if stock == 0 else 0,
                         round(R.uniform(3.4, 4.9), 1), R.randint(0, 5000),
                         R.randint(0, 3000), R.randint(30, 1800),
                         R.choices(["up", "down", "stable"], weights=[.3, .2, .5])[0]])
    return rows


def gen_inventory(per=3):
    rows = []
    for sku, cat, sub, brand, series, price, cost, w, v, case, shelf in SKUS:
        for _ in range(per):
            market = R.choices(["US", "US", "US", "CA", "DE"], weights=[.3, .25, .2, .13, .12])[0]
            sid = R.choice(MARKET_STORES[market])
            wh = R.choice(WH_BY_MARKET[market])
            wname, wtype, region, whm = WAREHOUSES[wh]
            wtype = R.choices(["overseas", "overseas", "third_party"], weights=[.6, .3, .1])[0]
            avail = R.randint(0, 900); it = R.randint(0, 600)
            reserved = R.randint(0, 100); damage = R.randint(0, 30)
            safety = R.randint(20, 120); reorder = safety + R.randint(30, 200)
            dos = R.randint(5, 120); ads = round(R.uniform(.5, 15), 1)
            valuation = round((avail + it) * cost, 2)
            lead = R.randint(14, 45)
            lb = dt.date(2025, 9, 1) + dt.timedelta(days=R.randint(0, 350))
            binloc = f"{wh}-{sku[-3:]}-A{R.randint(1, 9)}"
            rows.append([sid, sku, market, wh, wname, wtype, region, avail, it, reserved,
                         damage, safety, reorder, valuation, dos, ads, lb, lead, binloc])
    return rows


def gen_ad_performance(per=2):
    camps = [f"Campaign-{i}" for i in range(1, 41)]
    agroups = ["auto-group", "broad-group", "exact-group", "sponsored-product", "brand-defense"]
    matches = ["auto", "broad", "phrase", "exact"]
    rows = []
    for sku, cat, sub, brand, series, price, cost, w, v, case, shelf in SKUS:
        for _ in range(per):
            sid = R.choice(_ALL_STORES)
            market = _market_of(sid)
            platform = _platform_of(sid)
            cur = STORE_CURR[sid]
            d = dt.date(2025, 7, 1) + dt.timedelta(days=R.randint(0, 416))
            imps = R.randint(500, 20000)
            clicks = int(imps * R.uniform(.005, .04))
            cpc = round(R.uniform(.2, 1.8), 2)
            spend = round(clicks * cpc, 2)
            orders = R.choices([0, 0, R.randint(1, 3), R.randint(1, 8)],
                               weights=[.4, .2, .25, .15])[0]
            base_p = SKU_PRICE[sku] * PRICE_MARKET[market]
            ad_sku = round(base_p * R.uniform(.4, 1.0), 2)
            sales = round(base_p * orders, 2)
            ctr = round(clicks / imps, 4) if imps else 0
            roas = round(sales / spend, 2) if spend else 0
            acos = round(spend / sales, 3) if sales else 0
            tt = R.choice(["auto", "manual", "broad", "phrase", "exact"])
            rows.append([sid, sku, market, platform, R.choice(camps), R.choice(agroups),
                         tt, R.choice(matches), d, cur, spend, sales, ad_sku,
                         clicks, imps, orders, ctr, cpc, acos, roas,
                         R.choices(["enabled", "paused", "archived"], weights=[.85, .1, .05])[0]])
    return rows


def gen_ad_budgets(per=1):
    rows = []
    for sku, cat, sub, brand, series, price, cost, w, v, case, shelf in SKUS:
        for m in R.sample(range(1, 13), per):
            sid = R.choice(_ALL_STORES)
            market = _market_of(sid)
            platform = _platform_of(sid)
            cur = STORE_CURR[sid]
            bid = round(R.uniform(.5, 2.5), 2)
            daily = round(bid * R.uniform(8, 25), 2)
            monthly = round(daily * 30, 2)
            rows.append([sid, sku, market, platform, f"2026-{m:02d}", "daily", cur,
                         bid, daily, monthly, round(monthly * R.uniform(.3, 1), 2),
                         R.choice([.2, .25, .3, .35]),
                         R.choices(["active", "paused"], weights=[.8, .2])[0]])
    return rows


# ───────────── 组装 ─────────────
def _col_sql(model):
    cols = []
    for c in model.__table__.columns:
        ddl = f"`{c.name}` {_typ(c)}"
        if c.name in ("created_at", "updated_at"):
            ddl += " DEFAULT CURRENT_TIMESTAMP"
        if c.primary_key:
            if c.autoincrement and _typ(c).lower().startswith("integer"):
                ddl += " NOT NULL AUTO_INCREMENT"
            else:
                ddl += " NOT NULL"
        elif not c.nullable:
            ddl += " NOT NULL"
        cols.append(ddl)
    pks = [c.name for c in model.__table__.columns if c.primary_key]
    if pks:
        cols.append("PRIMARY KEY (" + ", ".join(f"`{k}`" for k in pks) + ")")
    return ",\n  ".join(cols)


def _typ(c):
    from sqlalchemy import types as T
    t = c.type
    if isinstance(t, T.Integer):
        return "INTEGER"
    if isinstance(t, T.Float):
        return "FLOAT"
    if isinstance(t, T.Text):
        return "TEXT"
    if isinstance(t, T.DateTime):
        return "DATETIME"
    if isinstance(t, T.Date):
        return "DATE"
    if isinstance(t, T.Boolean):
        return "BOOL"
    if isinstance(t, T.JSON):
        return "JSON"
    if isinstance(t, T.String):
        return f"VARCHAR({t.length})"
    return "TEXT"


def make_ddl(schema, model):
    t = model.__table__
    return (f"DROP TABLE IF EXISTS `{schema}`.`{t.name}`;\n"
            f"CREATE TABLE `{schema}`.`{t.name}` (\n"
            f"  {_col_sql(model)}\n);")


def _skip_id(model):
    """应被 INSERT 省略的字段: created_at/updated_at + (仅当自增 Integer) id.

    String 主键 (Store/Product/SalesOrder 的 id) 必须显式插入, 否则列/值错位.
    """
    from sqlalchemy import types as T
    skip = {"created_at", "updated_at"}
    for c in model.__table__.columns:
        if c.name == "id" and isinstance(c.type, T.Integer) and c.autoincrement:
            skip.add("id")
    return skip


def _insert(schema, model, rows):
    cols = [c.name for c in model.__table__.columns if c.name not in _skip_id(model)]
    col_sql = "(" + ", ".join(f"`{c}`" for c in cols) + ")"
    all_lines = ["  (" + ", ".join(val(v) for v in row) + ")" for row in rows]
    return (f"INSERT INTO `{schema}`.`{model.__table__.name}` {col_sql} VALUES\n"
            + ",\n".join(all_lines) + ";")


def build():
    parts = []
    parts.extend([
        "-- ============================================================",
        "-- HoneyDesk (Mifang) 跨境电商数据模型 V2 - 建表 + 丰富种子数据",
        "-- 维度: 多店铺/多市场/多仓库/多渠道/多语言/多币种",
        "-- DDL 由 ORM 模型自动生成, 保证与后端字段一致",
        "-- ============================================================",
        "CREATE DATABASE IF NOT EXISTS honey_desk DEFAULT CHARSET utf8mb4;",
        "CREATE DATABASE IF NOT EXISTS honey_system DEFAULT CHARSET utf8mb4;",
        "USE honey_system;",
        "SET NAMES utf8mb4;",
        "SET FOREIGN_KEY_CHECKS=0;",
        "",
    ])

    tables = [("honey_system", bm.Store)] + \
             [("honey_desk", m) for m in
              [bm.Product, bm.ProductMaterial, bm.Listing, bm.SalesOrder,
               bm.Competitor, bm.Inventory, bm.AdPerformance, bm.AdBudget]]

    for schema, m in tables:
        parts.append(make_ddl(schema, m))
        parts.append("")

    # 索引
    for schema, m in tables:
        for idx in m.__table__.indexes:
            cols = ", ".join("`" + c.name + "`" for c in idx.columns)
            parts.append(f"CREATE INDEX `{idx.name}` ON `{schema}`.`{m.__table__.name}` ({cols});")
    parts.append("")

    def insert(schema, m, rows, cols):
        c_sql = "(" + ", ".join("`" + c + "`" for c in cols) + ")"
        all_lines = []
        for row in rows:
            all_lines.append("  (" + ", ".join(val(v) for v in row) + ")")
        parts.append(f"INSERT INTO `{schema}`.`{m.__table__.name}` {c_sql} VALUES")
        parts.append(",\n".join(all_lines) + ";")
        parts.append("")

    # 各表列（跳过 created_at/updated_at 与自增 Integer id）
    def cols(m):
        return [c.name for c in m.__table__.columns if c.name not in _skip_id(m)]

    insert("honey_system", bm.Store, gen_store(), cols(bm.Store))
    insert("honey_desk", bm.Product, gen_products(), cols(bm.Product))
    insert("honey_desk", bm.ProductMaterial, gen_materials(), cols(bm.ProductMaterial))
    insert("honey_desk", bm.Listing, gen_listings(), cols(bm.Listing))
    insert("honey_desk", bm.SalesOrder, gen_sales_orders(2600), cols(bm.SalesOrder))
    insert("honey_desk", bm.Competitor, gen_competitors(), cols(bm.Competitor))
    insert("honey_desk", bm.Inventory, gen_inventory(3), cols(bm.Inventory))
    insert("honey_desk", bm.AdPerformance, gen_ad_performance(2), cols(bm.AdPerformance))
    insert("honey_desk", bm.AdBudget, gen_ad_budgets(1), cols(bm.AdBudget))

    parts.append("SET FOREIGN_KEY_CHECKS=1;")
    return "\n".join(parts)


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from app.database import Base  # noqa: 触发模型加载
    from app.models import business as bm  # noqa
    out = build()
    dest = Path(__file__).resolve().parents[1] / "db" / "schema_v2.sql"
    dest.write_text(out, encoding="utf-8")
    print("written:", dest, dest.stat().st_size, "bytes")