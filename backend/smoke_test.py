"""真实 LLM 冒烟测试：验证 DeepSeek 意图识别 + 路由闭环.

直接调用 LlamaChat API（/api/chat/send），以 UTF-8 编码发送中文请求，
覆盖 查询 / 广告分析 / 写操作(Llisting 审批) 三类路由闭环。
"""
import json
import sys

import httpx

BASE = "http://localhost:8000"

CASES = [
    (
        "ops_query 查询",
        "查询 7 月份美妆产品的总销售额",
    ),
    (
        "ads_query 广告分析",
        "分析近 14 天广告投放的 ROI，给出降本增效建议",
    ),
    (
        "ops_listing 写操作+审批",
        "为 SKU-00001 生成一份英文 Listing，突出玻尿酸和烟酰胺卖点",
    ),
]


def colour(s: str, code: str) -> str:
    return f"\033[{code}m{s}\033[0m"


def main() -> int:
    failures = 0
    with httpx.Client(timeout=180, base_url=BASE) as client:
        try:
            conn = test_connection(client)
        except Exception:
            conn = None
        print(colour("\n[连接测试]", "36"), json.dumps(conn, ensure_ascii=False))

        for name, msg in CASES:
            print(colour(f"\n{'='*60}\n▶ 场景：{name}\n  请求：{msg}\n{'='*60}", "1;35"))
            try:
                r = client.post("/api/chat/send", json={"message": msg})
                r.raise_for_status()
                data = r.json()
            except httpx.HTTPStatusError as e:
                body = e.response.text
                print(colour(f"  ❌ HTTP {e.response.status_code}: {body}", "31"))
                failures += 1
                continue
            except Exception as e:
                print(colour(f"  ❌ 请求异常: {e}", "31"))
                failures += 1
                continue

            task = data.get("task", {})
            status = task.get("status")
            intent = task.get("intent") or {}
            ans = (task.get("answer") or "").strip().replace("\n", " ")[:220]

            print(colour(f"  task_id : {task.get('task_id')}", "33"))
            print(colour(f"  status  : {status}", "32" if status != "failed" else "31"))
            print(colour(f"  intent  : scope={intent.get('scope')} mode={intent.get('work_mode')} "
                         f"agent={intent.get('agent_code')} conf={intent.get('confidence')}", "33"))
            if intent.get("params"):
                print(colour(f"  params  : {json.dumps(intent.get('params'), ensure_ascii=False)}", "33"))
            print(colour(f"  answer  : {ans}", "36"))

            if status in ("failed",):
                print(colour("  ✗ 该场景未通过（failed）", "31"))
                failures += 1
            else:
                print(colour("  ✓ 该场景通过", "32"))

    print(colour(f"\n{'='*60}\n冒烟测试结束：{'全部通过 ✅' if failures == 0 else f'{failures} 个失败 ❌'}"
                 f"\n{'='*60}", "1;32" if failures == 0 else "1;31"))
    return 1 if failures else 0


def test_connection(client: httpx.Client) -> dict:
    r = client.get("/api/settings/llm/status")
    r.raise_for_status()
    return r.json()


if __name__ == "__main__":
    sys.exit(main())