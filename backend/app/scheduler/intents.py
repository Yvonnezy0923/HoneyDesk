"""意图识别与路由：LLM 增强（配置时）+ 规则兜底（未配置或失败）."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..llm import LLMConfig, chat_json

SKU_RE = re.compile(r"(?i)\b(SKU[-–]?\d{4,6}|[A-Z]{2,4}[-–]?\d{3,6})\b")
DATE_RE = re.compile(r"(\d{4}[-/年.]\d{1,2}[-/月.]\d{1,2}日?)")
YEAR_RE = re.compile(r"(?<!\d)(20\d{2})(?!\d)")

# LLM 自由输出表名 → 工具注册表真实表名（fuzzy 别名收敛）
TABLE_ALIASES = {
    "product": "products", "products": "products", "商品": "products",
    "sales": "sales_orders", "sale": "sales_orders", "orders": "sales_orders",
    "order": "sales_orders", "sale_orders": "sales_orders", "salesorders": "sales_orders",
    "订单": "sales_orders",
    "listing": "listings", "listings": "listings",
    "material": "product_materials", "materials": "product_materials",
    "product_material": "product_materials", "资料": "product_materials",
    "competitor": "competitors", "competitors": "competitors", "竞品": "competitors",
    "inventory": "inventory", "库存": "inventory", "stock": "inventory",
    "ad_performance": "ad_performance", "adperf": "ad_performance", "ads": "ad_performance",
    "ad": "ad_performance", "广告": "ad_performance",
    "ad_budgets": "ad_budgets", "adbudgets": "ad_budgets", "ad_budget": "ad_budgets",
    "预算": "ad_budgets",
    "store": "stores", "stores": "stores", "店铺": "stores",
}
KNOWN_TABLES = set(TABLE_ALIASES.values())


def normalize_tables(tables: list) -> list[str]:
    """将 LLM 识别的表名归一化为注册表真实表名，过滤未知表."""
    out: list[str] = []
    for t in tables or []:
        real = TABLE_ALIASES.get((t or "").lower(), (t or ""))
        if real in KNOWN_TABLES and real not in out:
            out.append(real)
    return out


def normalize_dates(message: str, date_from=None, date_to=None):
    """消息无显式年份时，用确定性规则重写日期年份（LLM 易臆断错年份）."""
    from datetime import date
    year_now = date.today().year
    has_year = bool(YEAR_RE.search(message))
    # 显式说去年/上年 → 用上一年；否则当年
    target_year = year_now - 1 if ("去年" in message or "上年" in message) else year_now
    df = str(date_from) if date_from else ""
    dt = str(date_to) if date_to else ""
    if not has_year:
        df = _rewrite_year(df, target_year)
        dt = _rewrite_year(dt, target_year)
    elif not df or not dt:
        pass
    return df or date_from, dt or date_to


_CN_NUM = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
           "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


def extract_top_n(message: str) -> int | None:
    """识别用户指定的取数数量，如\"哪三款\"→3、\"销量前三\"→3、\"前20名\"→20."""
    def _conv(s: str):
        if s in _CN_NUM:
            return _CN_NUM[s]
        return int(s) if s.isdigit() else None
    # 显式量词：前3名 / 三款 / 前20个 ...
    for pat in (r"前\s*([一二两三四五六七八九十0-9]{1,3})\s*(?:名|款|位|个|只)",
                r"([一二两三四五六七八九十0-9]{1,3})\s*(?:名|款|位|个|只)"):
        m = re.search(pat, message)
        if m:
            v = _conv(m.group(1))
            if v and 1 <= v <= 500:
                return v
    # 无后缀的\"前三/前五\"（常接\"销量\"），排除日期数字（前30天）
    m = re.search(r"前\s*([一二两三四五六七八九十0-9]{1,2})(?![0-9天月周日])", message)
    if m:
        v = _conv(m.group(1))
        if v and 1 <= v <= 500:
            return v
    return None


def _cn_to_int(s: str) -> int | None:
    """中文数字转整数：三→3、十二→12、三十→30."""
    if not s:
        return None
    n = 0
    reg = 1
    for ch in reversed(s):
        if ch == "十":
            reg = 10
        elif ch in _CN_NUM:
            n += _CN_NUM[ch] * reg
        else:
            return None
    return n or None


def parse_relative_dates(message: str):
    """把\"最近7天/近3周/最近两个月/近一年\"等相对时间解析为 (date_from, date_to) ISO，
    未命中返回 (None, None)。"""
    from datetime import date, timedelta
    today = date.today()
    m = re.search(r"(?:最近|近)?\s*((?:[一二两三四五六七八九十]+|\d{1,3}))\s*(天|日|星期|周|个?月|年)", message)
    if not m:
        return None, None
    raw = m.group(1)
    n = int(raw) if raw.isdigit() else _cn_to_int(raw)
    if not n or n <= 0:
        return None, None
    unit = m.group(2)
    if unit in ("天", "日"):
        start = today - timedelta(days=n)
    elif unit in ("星期", "周"):
        start = today - timedelta(weeks=n)
    elif "月" in unit:
        start = today - timedelta(days=30 * n)
    else:
        start = today - timedelta(days=365 * n)
    return start.isoformat(), today.isoformat()


def _rewrite_year(d: str, year: int) -> str:
    if not d:
        return ""
    try:
        y, m, day = int(d[:4]), d[5:7] if len(d) >= 7 else "01", d[8:10] if len(d) >= 10 else "01"
        from datetime import date
        return date(year, int(m), int(day)).isoformat()
    except Exception:  # noqa: BLE001
        return d

SCOPE_RULES = {
    "supply": ["补货", "库存", "在途", "缺货", "断货", "仓库", "采购", "物流", "供应链"],
    "ads": ["广告", "出价", "预算", "ACOS", "ROAS", "花费", "投放", "转化", "广告组", "关键词", "素材", "CTR"],
    "operations": ["listing", "选品", "竞品", "销售", "订单", "退货", "评论", "运营", "商品", "排名", "差评"],
}
MODE_RULES = {
    "write": ["生成", "创建", "写", "起草", "新建", "优化listing", "生成标题", "翻译"],
    "analysis": ["分析", "对比", "趋势", "汇总", "环比", "同比", "复盘", "统计"],
    "alert": ["预警", "监控", "告急", "异常", "提醒"],
    "query": [],
}


@dataclass
class Intent:
    scope: str = "operations"
    work_mode: str = "query"          # query|analysis|write|alert
    agent_code: str = "ops_query"
    params: dict = field(default_factory=dict)
    confidence: float = 0.6
    table: str = ""


def _rule_recognize(message: str) -> Intent:
    text = message.lower()
    scope = "operations"
    for s, keys in SCOPE_RULES.items():
        if any(k.lower() in text for k in keys):
            scope = s
            break
    mode = "query"
    for m, keys in MODE_RULES.items():
        if any(k in text for k in keys):
            mode = m
            break
    # 路由 agent：按场景与模式（含 P1 预警/写模式，路由到各自板块 Agent）
    agent_map = {
        ("operations", "write"): "ops_listing",
        ("operations", "query"): "ops_query",
        ("operations", "analysis"): "ops_query",
        ("operations", "alert"): "ops_query",
        ("supply", "query"): "supply_query",
        ("supply", "analysis"): "supply_query",
        ("supply", "alert"): "supply_query",
        ("supply", "write"): "supply_query",
        ("ads", "query"): "ads_query",
        ("ads", "analysis"): "ads_query",
        ("ads", "alert"): "ads_query",
        ("ads", "write"): "ads_query",
    }
    agent = agent_map.get((scope, mode), "ops_query")
    params: dict = {}
    m = SKU_RE.search(message)
    if m:
        params["sku"] = re.sub(r"[-–]", "", m.group(1))
    dates = DATE_RE.findall(message)
    if dates:
        params["date_from"] = dates[0]
    tn = extract_top_n(message)
    if tn:
        params["top_n"] = tn
    if not params.get("date_from"):
        rdf, rdt = parse_relative_dates(message)
        if rdf:
            params["date_from"] = rdf
            params["date_to"] = rdt
    return Intent(scope=scope, work_mode=mode, agent_code=agent, params=params,
                  confidence=0.7)


def recognize(message: str, history: str = "") -> Intent:
    """若已配置 LLM 则用结构化意图识别（可携带最近对话历史做多轮指代理解），否则/失败用规则."""
    try:
        cfg = LLMConfig.from_db()
        if not cfg.configured:
            return _rule_recognize(message)
        sys = (
            "你是跨境电商工作台意图识别器。从用户提问中提取结构化 JSON，字段："
            '{"scope":"operations|supply|ads","work_mode":"query|analysis|write|alert",'
            '"sku":"可选SKU或空","date_from":"可选YYYY-MM-DD或空","date_to":"可选或空",'
            '"tables":["可选涉及业务表"],"top_n":"可选整数，用户指定取前几名/几款/几个时如3，未指定则null",'
            '"summary":"一句话意图"}。只输出JSON。'
            "日期规则：用户说月份但没给年份时，默认推断为最近一年的当年（当前年在先，"
            "若用户说'去年/上年'才用上一年），不要把无年份的月份臆断成很久以前的年份。"
            "多轮规则：当问题出现'它/该/这个'等指代或省略了主体时，结合【最近对话上下文】"
            "补全 SKU、表、日期与口径；上下文仅作背景，以当前问题为最终指令。"
        )
        user = message
        if history:
            user += (f"\n\n—— 最近对话上下文（仅作背景参考，勿改动既定量纲口径）——\n{history}")
        data = chat_json(cfg, sys, user, temperature=0)
    except Exception:  # noqa: BLE001
        return _rule_recognize(message)
    scope = data.get("scope", "operations")
    mode = data.get("work_mode", "query")
    table_codes = {
        "ops_listing": "ops_listing", "listing": "ops_listing",
    }
    agent = "ops_listing" if mode == "write" and scope == "operations" else table_codes.get(
        (scope, mode), f"{scope}_query")
    if scope == "operations" and mode == "write":
        agent = "ops_listing"
    elif scope == "operations":
        agent = "ops_query"
    else:
        agent = f"{scope}_query"
    df, dt = normalize_dates(message, data.get("date_from"), data.get("date_to"))
    if not df and not dt:  # LLM 未给出具体日期时，回退到相对时间规则
        rdf, rdt = parse_relative_dates(message)
        if rdf:
            df, dt = rdf, rdt
    top_n = data.get("top_n") or extract_top_n(message)
    return Intent(
        scope=scope, work_mode=mode, agent_code=agent,
        params={"sku": data.get("sku") or None,
                "date_from": df or None,
                "date_to": dt or None,
                "top_n": int(top_n) if top_n else None,
                "tables": normalize_tables(data.get("tables") or [])},
        confidence=float(data.get("confidence", 0.8)))