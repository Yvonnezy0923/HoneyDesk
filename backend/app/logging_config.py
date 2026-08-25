"""统一日志配置：按天落盘 + 保留最近 N 天 + 超期自动打包压缩.

目录规划（均在 backend 根目录下）：
  backend/log/agent/{date}.log    Agent 交互日志（对话流 / 工具调用 / 联动）→ agent 文件夹
  backend/log/engine/{date}.log   引擎日志（HTTP 访问与前端交互、配置 llm、审批点击等请求响应）→ engine 文件夹

保留策略：默认保留最近 10 天明文 .log；超过 10 天的文件自动打包成
{date}.log.tar.gz 并存放在各自子目录下，随后删除明文。
```
"""
from __future__ import annotations

import logging
import tarfile
import threading
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]          # backend 根目录（app 的上级）
APP_LOG_DIR = BASE_DIR / "log"                           # 后端日志根目录（内含 agent/engine 两个分类子目录）
AGENT_LOG_DIR = APP_LOG_DIR / "agent"                    # Agent 交互日志 → log/agent/{date}.log
ENGINE_LOG_DIR = APP_LOG_DIR / "engine"                  # 引擎日志 → log/engine/{date}.log

KEEP_DAYS = 10                                           # 明文日志保留天数
_LLM_LOGGER = "honeydesk.llm"                            # 大模型对话流专属 logger → agent 文件夹
_AGENT_LOGGER = "honeydesk.agent"                        # 通用 Agent 交互 logger（工具调用/联动等）→ agent 文件夹

_init_lock = threading.Lock()
_initialized = False


class DailyFileHandler(logging.Handler):
    """按自然日写入 {log_dir}/{date}.log；跨天滚动时对过期文件打包归档.

    线程安全（emit / rotate 全程持锁）。归档仅当跨天滚动时触发一次，
    避免每次写日志都扫描目录。
    """

    def __init__(self, log_dir, name: str = "", keep_days: int = KEEP_DAYS):
        super().__init__()
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.keep_days = keep_days
        self._lock = threading.Lock()
        self._cur_date: str | None = None
        self._fh = None
        self._tag = name or self.log_dir.name

    def _base_date(self) -> str:
        return date.today().isoformat()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            with self._lock:
                today = self._base_date()
                if today != self._cur_date:
                    self._rotate(today)
                if self._fh:
                    self._fh.write(self.format(record) + "\n")
                    self._fh.flush()
        except Exception:  # noqa: BLE001  日志失败不阻断业务
            self.handleError(record)

    def _rotate(self, today: str) -> None:
        if self._fh:
            try:
                self._fh.close()
            except Exception:  # noqa: BLE001
                pass
            self._fh = None
        self._cur_date = today
        try:
            self._fh = open(self.log_dir / f"{today}.log", "a", encoding="utf-8")
        except OSError:
            self._fh = None
        self._maintain()

    def _maintain(self) -> None:
        """把早于 keep_days 的明文 .log 打包成 .tar.gz 并删除明文."""
        cutoff = date.today() - timedelta(days=self.keep_days)
        for f in self.log_dir.glob("*.log"):
            if f.suffix.lower() != ".log":
                continue
            try:
                d = date.fromisoformat(f.stem)   # 仅处理 {date}.log 命名的文件
            except ValueError:
                continue
            if d < cutoff:
                _pack_log(f)

    def close(self) -> None:
        with self._lock:
            if self._fh:
                try:
                    self._fh.close()
                except Exception:  # noqa: BLE001
                    pass
                self._fh = None
        super().close()


def _pack_log(path: Path) -> None:
    """把单日日志打成 {date}.log.tar.gz（压缩后删除明文）."""
    gz = path.with_suffix(".log.tar.gz")
    try:
        with tarfile.open(gz, "w:gz") as tar:
            tar.add(str(path), arcname=path.name)
        path.unlink(missing_ok=True)
    except Exception:  # noqa: BLE001  打包失败保留明文，下次重试
        pass


def _file_fmt() -> logging.Formatter:
    return _Utc8Formatter(
        "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s | %(filename)s:%(lineno)d",
        datefmt="%Y-%m-%d %H:%M:%S")


class _Utc8Formatter(logging.Formatter):
    """强制用东八区本地时间作为日志记录时间（容器默认 UTC，需对齐当下时间）."""

    def formatTime(self, record, datefmt=None) -> str:
        t = datetime.fromtimestamp(record.created, tz=timezone.utc) + timedelta(hours=8)
        return t.strftime(datefmt or "%Y-%m-%d %H:%M:%S")


def setup_logging(keep_days: int = KEEP_DAYS) -> None:
    """初始化后端日志分流：engine 与 agent 两个子目录（幂等，供 lifespan 调用）."""
    global _initialized
    with _init_lock:
        if _initialized:
            return
        console = logging.StreamHandler()
        console.setFormatter(_file_fmt())

        engine_file = DailyFileHandler(ENGINE_LOG_DIR, name="engine", keep_days=keep_days)
        agent_file = DailyFileHandler(AGENT_LOG_DIR, name="agent", keep_days=keep_days)

        # ── engine：根 logger + uvicorn/fastapi → log/engine/{date}.log
        #    承载 HTTP 访问与前端的交互、配置 llm、审批点击等请求/响应日志。
        root = logging.getLogger()
        root.setLevel(logging.INFO)
        root.handlers.clear()
        root.addHandler(engine_file)
        root.addHandler(console)
        for name in ("uvicorn", "uvicorn.access", "uvicorn.error", "uvicorn.asgi",
                     "fastapi"):
            lg = logging.getLogger(name)
            lg.setLevel(logging.INFO)
            lg.handlers.clear()
            lg.addHandler(engine_file)
            lg.addHandler(console)
            lg.propagate = False

        # ── agent：对话流（llm）+ 通用 Agent 交互（工具调用/联动）→ log/agent/{date}.log
        for _name in (_LLM_LOGGER, _AGENT_LOGGER):
            al = logging.getLogger(_name)
            al.setLevel(logging.INFO)
            al.handlers.clear()
            al.addHandler(agent_file)
            al.addHandler(console)
            al.propagate = False

        _initialized = True


def get_llm_logger() -> logging.Logger:
    """返回大模型对话流 logger（未初始化时自动补初始化，避免早于 lifespan 调用空转）."""
    if not _initialized:
        setup_logging()
    return logging.getLogger(_LLM_LOGGER)


def get_agent_logger() -> logging.Logger:
    """返回通用 Agent 交互 logger（工具调用/联动等）."""
    if not _initialized:
        setup_logging()
    return logging.getLogger(_AGENT_LOGGER)