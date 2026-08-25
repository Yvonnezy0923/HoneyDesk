"""共享数据执行：供调度中心/Agent 调用只读工具并计算引用来源."""
from __future__ import annotations

import json
import time
from datetime import date, datetime

from .. import ids
from ..data import access
from ..logging_config import get_agent_logger
from ..tools import registry as tools_reg


def parse_date(val) -> date | None:
    if isinstance(val, date):
        return val
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, str) and val:
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m"):
            try:
                return datetime.strptime(val, fmt).date()
            except ValueError:
                continue
    return None


class ReadResult:
    def __init__(self, table, rows, tool_code, ms, op_id, store_id=None):
        self.table = table
        self.rows = rows
        self.tool_code = tool_code
        self.ms = ms
        self.op_id = op_id
        self.store_id = store_id

    def to_context(self) -> str:
        if not self.rows:
            return f"【{self.table}】无匹配记录。"
        import json
        return f"【{self.table} 共{len(self.rows)}条】\n" + json.dumps(
            self.rows[:30], ensure_ascii=False, default=str)


def execute_read(table: str, *, store_id: str | None = "store_1001",
                 sku: str | None = None, date_from=None, date_to=None,
                 limit: int = 50, agent_code: str = "ops_query",
                 task_id: str = "") -> ReadResult:
    op_id = ids.op_id()
    t0 = time.time()
    rows = access.query_table(
        table, store_id=store_id, sku=sku,
        date_from=parse_date(date_from), date_to=parse_date(date_to), limit=limit)
    ms = int((time.time() - t0) * 1000)
    try:
        get_agent_logger().info(json.dumps({
            "event": "tool_call", "tool": f"query_{table}", "table": table,
            "agent": agent_code, "task_id": task_id, "store_id": store_id,
            "sku": sku, "date_from": str(date_from), "date_to": str(date_to),
            "rows": len(rows or []), "ms": ms,
        }, ensure_ascii=False))
    except Exception:  # noqa: BLE001  工具日志失败不影响调用
        pass
    # 读操作不进操作审计（读无需审批、无需审计留痕），但计入工具调用计数（数据看板）
    _usage(tool_code=f"query_{table}", ok=True, ms=ms)
    return ReadResult(table, rows or [], f"query_{table}", ms, op_id, store_id)


def _usage(tool_code: str, ok: bool, ms: int) -> None:
    try:
        from ..database import session
        from ..models.business import ToolRecord
        with session() as db:
            rec = db.get(ToolRecord, tool_code)
            if not rec:
                # 未命中即新建：保证任意查询工具被调用都有计数
                rec = ToolRecord(id=tool_code, code=tool_code, name=tool_code,
                                 table_name=tool_code, fields=[], permission="read")
                db.add(rec)
            rec.call_count += 1
            rec.success_count += 1 if ok else 0
            rec.total_ms += ms
    except Exception:  # noqa: BLE001
        pass


def gather(params: dict, agent_code: str, task_id: str) -> dict[str, ReadResult]:
    """按参数读取一个/多个表，返回 table -> ReadResult."""
    table = params.get("table")
    out: dict[str, ReadResult] = {}
    if table:
        out[table] = execute_read(table, sku=params.get("sku"),
                                  date_from=params.get("date_from"),
                                  date_to=params.get("date_to"),
                                  agent_code=agent_code, task_id=task_id)
        return out
    # 无指定表：根据意图覆盖读多表
    sku = params.get("sku")
    for t in params.get("tables", []):
        out[t] = execute_read(t, sku=sku,
                              date_from=params.get("date_from"),
                              date_to=params.get("date_to"),
                              agent_code=agent_code, task_id=task_id)
    return out