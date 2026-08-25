"""运营·Listing 生成 Agent：读产品资料 →（可选 LLM）生成 Listing → 提交写操作审批."""
from __future__ import annotations

import time

from .. import ids
from ..llm import chat_text
from .toolkit import execute_read

_TEMPLATE_TITLE = "{name} | Skin Care | {k1} & {k2} | {audience} Gift"
_TEMPLATE_BULLETS = [
    "{k1}: 添加玻尿酸/烟酰胺，深层补水提亮",
    "温和配方：无动物实验、无尼泊金，敏感肌友好",
    "易吸收：质地轻盈，快速吸收不粘腻",
    "多场景：日常护肤、上妆前打底、随身携带",
    "品质保障：品牌支持无条件退换",
]


def run(intent, task_id: str, message: str = "", history: str = "") -> dict:
    from ..rag.service import get_rag
    params = intent.params
    sku = params.get("sku")
    op_id = ids.op_id()
    t0 = time.time()
    rr = execute_read("product_materials", sku=sku, agent_code="ops_listing",
                      task_id=task_id, limit=10)
    materials = rr.rows
    if not materials:
        return {
            "answer": "未找到产品资料，无法生成 Listing。请先在知识库/导入中补充 product_materials。",
            "sources": [], "proposed_writes": [], "artifact": None, "cost": 0.0,
        }

    style = ""
    try:
        kb = get_rag().search("listing 标题 五点 描述 关键词 规范", scope=None, top_k=2)
        if kb:
            style = "\n".join(f"- {r.content}" for r in kb[:2])
    except Exception:  # noqa: BLE001
        style = ""

    cfg = None
    try:
        from ..llm import LLMConfig
        cfg = LLMConfig.from_db()
    except Exception:  # noqa: BLE001
        cfg = None

    listings = []
    llm_used = bool(cfg and cfg.configured)
    cost = 0.0
    for m in materials:
        listing = _generate_one(cfg, m, style, llm_used)
        listings.append({"sku": m["sku"], "market": m.get("target_market") or "US",
                         **listing})
        cost += _rough_cost(listing) if llm_used else 0.0

    proposed_writes = []
    for l in listings:
        proposed_writes.append({
            "table": "listings",
            "record_key": f"new:{l['sku']}",
            "record": {
                "store_id": "store_1001", "sku": l["sku"], "market": l["market"],
                "title": l["title"], "bullet_points": l["bullet_points"],
                "description": l["description"], "search_terms": l["search_terms"],
                "status": "draft", "language": l.get("language", "en"),
            },
            "reason": f"为 SKU {l['sku']} 批量生成 Listing 草稿",
            "evidence": f"产品资料:{l['sku']} · 目标市场:{l['market']}"
                        + (" · 知识库风格参考" if style else ""),
        })

    answer = (f"已为 **{len(listings)}** 个 SKU 生成 Listing 草稿"
              f"{'（LLM 生成）' if llm_used else '（模板草稿，尚未接入 LLM）'}：\n\n")
    sample = listings[0]
    answer += (f"- 示例 {sample['sku']}｜标题：{sample['title'][:60]}\n"
               f"  五点: {len(sample['bullet_points'])} 条 | 关键词: {sample['search_terms'][:60]}\n")
    answer += "\n> ⚠️ 写操作已提交，等待你审批后才会写入【Listing 表】。"

    artifact_data = {
        "agent": "ops_listing",
        "task_id": task_id,
        "count": len(listings),
        "llm_used": llm_used,
        "items": listings,
    }
    return {
        "answer": answer,
        "sources": [{"table": "product_materials", "op_id": op_id, "rows": len(materials)}],
        "proposed_writes": proposed_writes,
        "artifact": {
            "title": f"Listing 生成结果（{len(listings)} SKU）",
            "type": "report", "scope": "operations", "agent_code": "ops_listing",
            "task_id": task_id, "content": answer, "data": artifact_data,
            "sources": [{"table": "product_materials", "rows": len(materials)}],
        },
        "cost": cost,
    }


def _generate_one(cfg, material: dict, style: str, llm_used: bool) -> dict:
    if not llm_used:
        return _template(material)
    name = material.get("name") or material.get("sku", "")
    market = material.get("target_market") or "US"
    lang = material.get("target_language") or "en"
    sys = (
        "你是跨境电商资深 Listing 文案专家。基于产品资料生成高质量的 Listing。"
        "只输出 JSON：{title, bullet_points:[5条], description, search_terms, language}。"
        "标题前80字符放核心关键词；五点覆盖材质/功效/适用人群/质保；关键词用逗号分隔。"
        f"知识风格参考：\n{style or '简洁专业'}"
    )
    user = (f"产品名称:{name}\n卖点:{material.get('selling_points') or material.get('features')}\n"
            f"目标市场:{market}\n语言:{lang}\n规格:{material.get('spec')}")
    try:
        from ..llm import chat_json
        d = chat_json(cfg, sys, user, temperature=0.6)
        d.setdefault("bullet_points", _template(material)["bullet_points"])
        d.setdefault("description", "")
        d.setdefault("search_terms", "")
        d["title"] = d.get("title") or _template(material)["title"]
        d["language"] = lang
        return d
    except Exception:  # noqa: BLE001
        return _template(material)


def _template(material: dict) -> dict:
    name = material.get("name") or material.get("sku", "")
    k1, k2 = "Moisturizing", "Gentle"
    return {
        "title": _TEMPLATE_TITLE.format(name=name, k1=k1, k2=k2, audience="Women"),
        "bullet_points": [_b.format(k1=k1) for _b in _TEMPLATE_BULLETS],
        "description": f"{name}：专为日常护肤设计，温和补水，适合各类肤质。",
        "search_terms": "honey,beauty,skincare,moisturizer,gentle,gift",
        "language": material.get("target_language") or "en",
    }


def _rough_cost(listing: dict) -> float:
    words = len(listing.get("title", "")) + sum(
        len(b) for b in listing.get("bullet_points", [])) + len(
        listing.get("description", ""))
    return round(words / 1000 * 0.1, 4)  # 粗估：$0.1 / 千token