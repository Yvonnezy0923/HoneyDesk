"""监控预警定时调度：自动评估按设置频率运行."""
from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta

from . import service as monitor_service

from .service import FREQ_HOURS

_running = False
_thread: threading.Thread | None = None


def start() -> None:
    global _running, _thread
    if _running:
        return
    _running = True
    freq = monitor_service.get_frequency()
    _thread = threading.Thread(target=_loop, daemon=True)
    _thread.start()
    print(f"[monitor] 调度器已启动（{FREQ_HOURS.get(freq, 1)}小时）")


def stop() -> None:
    global _running
    _running = False


def _get_interval() -> int:
    freq = monitor_service.get_frequency()
    hours = FREQ_HOURS.get(freq, 1)
    return hours * 3600


def _next_run_delay() -> float:
    """计算到下一个执行点的延迟。对于 1h → 整点；2h → 0/2/4/…；1d → 午夜"""
    now = datetime.now()
    freq = monitor_service.get_frequency()
    if freq == "24h":
        # 午夜（0:00）
        next_run = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    elif freq == "12h":
        # 0:00, 12:00
        next_hour = (now.hour // 12 + 1) * 12
        next_run = now.replace(hour=next_hour, minute=0, second=0, microsecond=0)
        if next_run <= now:
            next_run += timedelta(hours=12)
    elif freq == "72h":
        # 3天，从现在起每三天
        next_run = now + timedelta(hours=72)
    else:
        # 1h/2h/6h → 按整点对齐
        hours = FREQ_HOURS.get(freq, 1)
        next_hour = ((now.hour // hours) + 1) * hours
        next_run = now.replace(hour=next_hour, minute=0, second=0, microsecond=0)
        if next_run <= now:
            next_run += timedelta(hours=hours)
    return (next_run - now).total_seconds()


def _loop() -> None:
    # 首次延迟到下一个对齐点
    delay = _next_run_delay()
    if delay > 0:
        time.sleep(delay)
    while _running:
        try:
            _evaluate_once()
        except Exception as e:
            print(f"[monitor] 调度评估异常: {e}")
        interval = _get_interval()
        time.sleep(interval)


def _evaluate_once() -> None:
    results = monitor_service.evaluate_all_rules()
    triggered = [r for r in results if "alert_id" in r]
    freq = monitor_service.get_frequency()
    hours = FREQ_HOURS.get(freq, 1)
    print(f"[monitor] {datetime.utcnow().isoformat()} 评估完成[{hours}h]，"
          f"触发 {len(triggered)} 条预警"
          f"{'（' + str(len(results) - len(triggered)) + ' 条跳过）' if len(results) > len(triggered) else ''}")
    for r in triggered[:5]:
        print(f"  → {r.get('alert_id', '')}: {r.get('message', '')[:60]} [{r.get('dim', '')}]")