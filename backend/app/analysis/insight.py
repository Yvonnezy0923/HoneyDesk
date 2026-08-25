"""结论分析与追问：基于查询结果，由 LLM 生成数据结论、下一步操作建议与可点击追问；失败用模板兜底."""
from __future__ import annotations

from ..llm import LLMConfig, chat_json
from . import schema as sm
from . import chart as chart_mod

_DEFAULT_FOLLOW_UPS = [
    "对比上个月的数据变化，找出主要波动点",
    "为表现最好的 SKU 生成优化建议",
    "按时间趋势下钻，看最近 30 天走势",
    "导出本次查询的完整明细数据",
]


def summarize(results: list[dict]) -> str:
    """把查询结果压缩成给 LLM 的紧凑数据摘要."""
    lines = []
    for res in results:
        t = res["table"]
        head = f"{t}（{sm.table_label(t)}）"
        if res.get("raw") or not res.get("dimension"):
            rows = res.get("rows") or []
            lines.append(f"{head}：原样记录 {len(rows)} 条。")
            continue
        ch = chart_mod.build_chart(res)
        if not ch:
            lines.append(f"{head}：无数据。")
            continue
        top = list(zip(ch["categories"], ch["series"][0]["data"] if ch["series"] else []))
        total = sum(v for _, v in top)
        sample = "\n".join(f"  - {c}：{v:.2f}" for c, v in top[:5])
        lines.append(
            f"{head}｜按 {ch['dimension_label']} 分组（共 {len(top)} 项），"
            f"指标 {ch['series'][0]['name'] if ch['series'] else ''} 合计 {total:.2f}：\n{sample}"
        )
    return "\n".join(lines)


def analyze(message: str, results: list[dict], history: str = "",
            agent_code: str = "ops_query", task_id: str = "") -> dict:
    """返回 {conclusion, suggestions:[...], follow_ups:[...]}."""
    summary = summarize(results)
    try:
        cfg = LLMConfig.from_db()
        if cfg.configured:
            _out = _llm(message, summary, cfg, history)
            if _out:
                return _finalize(_out, results, used_llm=True,
                                 agent_code=agent_code, task_id=task_id,
                                 message=message)
    except Exception:  # noqa: BLE001
        pass
    return _finalize(_fallback(results), results, used_llm=False,
                     agent_code=agent_code, task_id=task_id)


def _has_data(results: list[dict]) -> bool:
    """是否有任一查询表实际返回了记录（作为结论的事实根基）."""
    return any((r.get("rows") or []) for r in results)


def _finalize(out: dict, results: list[dict], *, used_llm: bool,
              agent_code: str, task_id: str, message: str = "") -> dict:
    """落库结论并做幻觉风险监测：仅当 LLM 产出了结论、却无任何源数据支撑时预警."""
    if used_llm and (out.get("conclusion") or "").strip() and not _has_data(results):
        _flag_hallucination(
            title="无源数据产出了结论（疑似幻觉）",
            message=(out["conclusion"] or "")[:500],
            agent_code=agent_code, task_id=task_id, scope=agent_code,
            user_message=message)
    return out


def _flag_hallucination(*, title: str, message: str, agent_code: str,
                        task_id: str, scope: str, user_message: str) -> None:
    """写入一条低危幻觉预警 + 累计计数（供看板「幻觉雷达」统计）."""
    from sqlalchemy import select
    from ..alerts import service as alerts_service
    from ..database import session as _session
    from ..models.business import Setting
    try:  # 尽力而为：预警写入失败不影响回答
        alerts_service.write(
            alert_type="hallucination", scope=scope,
            market="US", severity="low",
            title=title,
            message=message or "LLM 在无业务数据支撑的情况下给出了结论，请核对后使用。",
            evidence={"user_message": user_message, "rows_fetched": 0},
            source_task=task_id)
        with _session() as db:
            row = db.execute(
                select(Setting).where(Setting.key == "hallucination_risk_count")
            ).scalar()
            n = int(row.value or 0) + 1 if row else 1
            if row:
                row.value = str(n)
            else:
                db.add(Setting(key="hallucination_risk_count", value=str(n)))
    except Exception:  # noqa: BLE001
        pass


def _llm(message: str, summary: str, cfg, history: str = "") -> dict | None:
    sys = (
        "你是跨境电商数据分析师。根据用户问题与查询结果，输出结构化洞察。\n"
        "输出 JSON：{"
        "\"conclusion\":\"数据结论要点（1~3 句，基于真实数据，不臆造数字）\","
        "\"suggestions\":[\"下一步操作建议（2~4 条，具体可落地）\"],"
        "\"follow_ups\":[\"用户还可能追问的 3~4 个问题，贴合数据继续深挖\"]}"
        "。只输出 JSON。结论须结合对话背景中已谈及的 SKU/口径保持一致，"
        "但数字一律以本次查询结果为准。"
    )
    user = f"用户问题：{message}\n\n查询结果摘要：\n{summary or '（无有效数据）'}"
    if history:
        user += f"\n\n最近对话背景：{history}\n（仅作上下文参考，结论基于本次查询结果）"
    data = chat_json(cfg, sys, user, temperature=0.5, max_tokens=1500)
    return {
        "conclusion": (data.get("conclusion") or "").strip(),
        "suggestions": [s for s in (data.get("suggestions") or []) if str(s).strip()],
        "follow_ups": [q for q in (data.get("follow_ups") or _DEFAULT_FOLLOW_UPS) if str(q).strip()],
    }


def _fallback(results: list[dict]) -> dict:
    ch = None
    for res in results:
        c = chart_mod.build_chart(res)
        if c:
            ch = c
            break
    conclusion = "已按查询条件完成数据汇总与可视化。"
    if ch and ch["series"]:
        total = sum(ch["series"][0]["data"])
        conclusion = (f"共统计到 {len(ch['categories'])} 项，"
                      f"指标【{ch['series'][0]['name']}】合计为 {total:.2f}。")
    return {
        "conclusion": conclusion,
        "suggestions": [
            "结合上期数据做环比判断，识别显著波动项",
            "对领先/垫底项进一步下钻，定位原因",
            "把关键指标加入定期监控与预警",
        ],
        "follow_ups": _DEFAULT_FOLLOW_UPS,
    }