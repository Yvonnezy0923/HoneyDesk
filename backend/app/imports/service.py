"""数据导入：CSV / JSON → 业务表（幂等，列名与模型字段对齐）."""
from __future__ import annotations

import csv
import io
import json

from .. import ids
from ..database import session
from ..data import access
from ..audit import service as audit_service


def import_rows(table: str, rows: list[dict], store_id: str = "store_1001",
                operator: str = "user") -> dict:
    if table not in access.MODEL_MAP:
        return {"ok": False, "message": f"不支持导入表 {table}"}
    model = access.MODEL_MAP[table]
    columns = set(model.__table__.columns.keys())
    ok = 0
    failed = 0
    with session() as db:
        for r in rows:
            data = {k: v for k, v in r.items() if k in columns and v is not None}
            data.setdefault("store_id", store_id)
            try:
                obj = model(**data)
                db.add(obj)
                ok += 1
            except Exception:  # noqa: BLE001
                failed += 1
    batch = ids.import_batch_id()
    audit_service.record(ids.op_id(), action=f"import_{table}", op_type="write",
                         operator=operator, table_name=table,
                         params={"batch": batch, "ok": ok, "failed": failed},
                         result="success" if failed == 0 else "partial")
    return {"ok": True, "imported": ok, "failed": failed, "batch": batch}


def parse_csv(text: str) -> list[dict]:
    reader = csv.DictReader(io.StringIO(text))
    return [dict(r) for r in reader]


def parse_json(text: str) -> list[dict]:
    data = json.loads(text)
    if isinstance(data, dict) and "rows" in data:
        return data["rows"]
    return data