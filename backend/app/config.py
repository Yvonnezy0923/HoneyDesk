"""应用配置：从环境变量 / .env 读取."""
from __future__ import annotations

from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # 应用
    app_env: str = "dev"
    app_port: int = 8000
    cors_origins: str = "http://localhost:5173,http://localhost:3000"

    # 大模型（用户自填）
    llm_api_base: str = ""
    llm_api_key: str = ""
    llm_model: str = ""
    llm_light_model: str = ""
    llm_timeout: float = 90.0

    # 本地向量模型
    embedding_model_path: str = "models/bge-m3"
    rerank_model_path: str = "models/bge-reranker-v2-m3"
    embedding_backend: str = "auto"  # auto | bge | fallback

    # MySQL（分库：honey_desk 业务库 + honey_system 系统库，表级 schema）
    # 连接默认库为 honey_system（所有表均以 schema 限定，默认库仅需存在）
    mysql_host: str = "localhost"
    mysql_port: int = 3306
    mysql_user: str = "root"
    mysql_root_password: str = "honeydesk_root"
    mysql_database: str = "honey_system"

    # Qdrant
    qdrant_host: str = "localhost"
    qdrant_port: int = 6333
    qdrant_collection: str = "honeydesk_kb"
    embedding_dim: int = 1024

    # 调度 / 检索 / 审批
    approval_timeout_hours: int = 24
    rag_top_k: int = 5
    low_confidence_threshold: float = 0.35

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def business_engine_url(self) -> str:
        return (
            f"mysql+pymysql://{self.mysql_user}:{self.mysql_root_password}"
            f"@{self.mysql_host}:{self.mysql_port}/{self.mysql_database}?charset=utf8mb4"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()