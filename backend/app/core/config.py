"""Application configuration via pydantic-settings."""

from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=False
    )

    # Application
    APP_NAME: str = "ECom AI Dashboard"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = True
    SECRET_KEY: str = "change-me-in-production"

    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://ecom:ecom2024@localhost:5432/ecom_dashboard"
    DB_ECHO: bool = False

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # Milvus
    MILVUS_HOST: str = "localhost"
    MILVUS_PORT: int = 19530
    MILVUS_COLLECTION: str = "agent_memory"

    # ── LLM ──
    # Three-tier architecture:
    #   Tier 1 (LIGHT) → intent routing + simple queries
    #   Tier 2 (HEAVY) → ReAct deep reasoning
    #   Tier 3 (FAST)  → keyword rule engine (zero-API fallback)
    LLM_PROVIDER: str = "qwen"  # qwen | openai | deepseek
    QWEN_API_KEY: Optional[str] = None
    QWEN_MODEL: str = "qwen-plus"
    QWEN_BASE_URL: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    OPENAI_API_KEY: Optional[str] = None
    OPENAI_MODEL: str = "gpt-4o"
    OPENAI_BASE_URL: Optional[str] = None
    DEEPSEEK_API_KEY: Optional[str] = None
    DEEPSEEK_MODEL: str = "deepseek-chat"

    # ── Lightweight LLM (Tier 1: intent routing + simple answers) ──
    LIGHT_LLM_API_KEY: Optional[str] = None      # defaults to QWEN_API_KEY if unset
    LIGHT_LLM_MODEL: str = "qwen-turbo"           # cheap & fast (~0.001¥/call)
    LIGHT_LLM_BASE_URL: Optional[str] = None      # defaults to QWEN_BASE_URL
    LIGHT_LLM_MAX_TOKENS: int = 256               # short responses for routing
    LIGHT_LLM_TEMPERATURE: float = 0.0            # deterministic for classification

    # Agent
    AGENT_MAX_STEPS: int = 10
    AGENT_TEMPERATURE: float = 0.1
    AGENT_MAX_TOKENS: int = 4096

    # MCP Server
    MCP_SERVER_ENABLED: bool = True
    MCP_HTTP_PORT: int = 9000

    # ── 数据源模式 ──
    # kafka: 从 Kafka 消费实时数据
    # polling: 从数据库轮询（PostgreSQL/MySQL）
    # generator: 随机生成模拟数据（演示/降级）
    # auto: 自动检测（Kafka → 降级到 generator）
    DATA_SOURCE: str = "auto"

    # Data Generator (降级方案)
    DATA_GEN_ENABLED: bool = True
    DATA_GEN_ORDER_INTERVAL: float = 2.0  # seconds
    DATA_GEN_TRAFFIC_INTERVAL: float = 10.0
    DATA_GEN_INVENTORY_INTERVAL: float = 30.0
    DATA_GEN_COMPETITOR_INTERVAL: float = 300.0

    # ── Kafka ──
    KAFKA_BOOTSTRAP_SERVERS: str = "localhost:9092"
    KAFKA_TOPIC_ORDERS: str = "ecom.orders"
    KAFKA_TOPIC_TRAFFIC: str = "ecom.traffic"
    KAFKA_TOPIC_INVENTORY: str = "ecom.inventory"
    KAFKA_TOPIC_COMPETITOR: str = "ecom.competitor"
    KAFKA_CONSUMER_GROUP: str = "ecom-dashboard"

    # ── 通知通道 ──
    FEISHU_WEBHOOK_ENABLED: bool = False
    FEISHU_WEBHOOK_URL: str = ""
    DINGTALK_WEBHOOK_ENABLED: bool = False
    DINGTALK_WEBHOOK_URL: str = ""

    # ── pgvector ──
    VECTOR_DIM: int = 384

    # CORS
    CORS_ORIGINS: list[str] = ["http://localhost:5173", "http://localhost:3000"]

    # ── V3.0: A2A Multi-Agent ──────────────────────────────────────
    A2A_ENABLED: bool = True
    A2A_TIMEOUT: float = 2.0          # seconds, per-agent call timeout
    A2A_RETRY: int = 1                # retries before circuit-break
    A2A_CIRCUIT_BREAK_THRESHOLD: int = 3  # consecutive failures

    # A2A Agent service URLs (when deployed as microservices)
    DATA_AGENT_URL: str = "http://localhost:8010"
    ANALYZE_AGENT_URL: str = "http://localhost:8011"
    SENTIMENT_AGENT_URL: str = "http://localhost:8012"
    REPORT_AGENT_URL: str = "http://localhost:8013"

    # ── V3.0: Cache Manager ───────────────────────────────────────
    CACHE_L1_MAX_SIZE: int = 500
    CACHE_DEFAULT_TTL: int = 60

    # ── V3.0: Guardrails (后链路安全护栏) ──────────────────────────
    GUARDRAILS_ENABLED: bool = True
    MAX_AUTO_BUDGET_ADJUST_PCT: float = 20.0  # 自动执行阈值: 20%
    BUDGET_ROLLBACK_WINDOW_MIN: int = 30       # 回滚检查窗口(分钟)

    # ── V3.0: MySQL (for order persistence, compatible with PG) ───
    MYSQL_URL: str = ""  # optional, uses DATABASE_URL when empty

    # ── V3.0: Pre-aggregation ──────────────────────────────────────
    PREAGG_INTERVAL_SEC: int = 300  # 5-minute aggregation cycle


@lru_cache()
def get_settings() -> Settings:
    return Settings()
