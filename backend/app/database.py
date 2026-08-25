"""单一 MySQL 引擎与会话管理（审计记录并入业务库，见 models/audit.py）."""
from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import get_settings

settings = get_settings()

# 分库：业务库（店家供应链/广告/运营）与系统库（对话/审批/知识库/配置）物理分离
BUSINESS_SCHEMA = "honey_desk"
SYSTEM_SCHEMA = "honey_system"

engine = create_engine(
    settings.business_engine_url,
    pool_pre_ping=True,
    pool_recycle=3600,
    pool_size=10,
    echo=False,
)
SessionFactory = sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    """全部表（业务 + 审计）基类."""


@contextmanager
def session():
    s = SessionFactory()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


# 兼容旧引用
business_session = session