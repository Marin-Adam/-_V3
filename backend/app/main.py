"""FastAPI application entry point — V3.0 Multi-Agent Architecture.

Startup sequence:
  1. Shared data store + stream manager
  2. Data source selection (Kafka → Generator fallback)
  3. CacheManager (L1/L2 + Redis Pub/Sub)
  4. MCP Registry (auto-registered tools from mcp/tools/)
  5. A2A Orchestrator (multi-agent collaboration engine)
  6. SkillScheduler (periodic anomaly detection)
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from app.core.config import get_settings

settings = get_settings()


@asynccontextmanager
async def lifespan(application: FastAPI):
    logger.info(f"Starting {settings.APP_NAME} v{settings.APP_VERSION} (V3.0 Multi-Agent)")

    # ── Shared data store (single source of truth) ─────────────────
    from app.data.store import EcomDataStore
    data_store = EcomDataStore()
    application.state.data_store = data_store

    # ── Shared stream manager ─────────────────────────────────────
    from app.data.streams import StreamManager
    stream_mgr = StreamManager()
    application.state.stream_manager = stream_mgr

    # ── Data source selection ────────────────────────────────────
    data_source_used = "none"

    # Tier 1: Kafka
    kafka_chosen = (settings.DATA_SOURCE == "kafka") or (
        settings.DATA_SOURCE == "auto" and _kafka_reachable()
    )
    if kafka_chosen:
        from app.data.consumers import KafkaConsumerManager
        try:
            kafka_mgr = KafkaConsumerManager(stream_mgr, store=data_store)
            await kafka_mgr.start()
            application.state.data_consumer = kafka_mgr
            data_source_used = "kafka"
            logger.info("Data source: Kafka consumer group")
        except Exception as e:
            logger.warning(f"Kafka start failed ({e}), falling back")
            kafka_chosen = False

    # Tier 3: Random simulation (always available fallback)
    if not kafka_chosen and data_source_used == "none":
        from app.data.generator import DataGenerator
        gen = DataGenerator(stream_mgr, store=data_store)
        application.state.data_generator = gen
        await gen.start()
        data_source_used = "generator"
        logger.info("Data source: random simulation (generator)")

    # ── V3.0: CacheManager ───────────────────────────────────────
    try:
        from app.services.cache_manager import start_cache, get_cache
        await start_cache()
        application.state.cache = get_cache()
        logger.info("CacheManager: L1/L2 cache ready")
    except Exception as e:
        logger.warning(f"CacheManager unavailable: {e}")

    # ── V3.0: MCP Registry (tools auto-register at import) ───────
    try:
        import app.mcp.tools  # triggers all tool registrations
        from app.mcp.registry import MCPRegistry
        tool_count = len(MCPRegistry.list_all())
        enabled_count = len(MCPRegistry.list_enabled())
        logger.info(f"MCP Registry: {enabled_count}/{tool_count} tools enabled")
    except Exception as e:
        logger.warning(f"MCP Registry init failed: {e}")

    # ── V3.0: A2A Orchestrator ───────────────────────────────────
    gen_ref = getattr(application.state, "data_generator", None)
    try:
        from app.agent.orchestrator import Orchestrator
        orchestrator = Orchestrator(
            data_generator=gen_ref,
            stream_manager=stream_mgr,
            store=data_store,
        )
        application.state.orchestrator = orchestrator
        logger.info("Orchestrator: V3.0 multi-agent engine ready (inprocess mode)")
    except Exception as e:
        logger.warning(f"Orchestrator init failed: {e}")

    # ── SkillScheduler ───────────────────────────────────────────
    from app.workers.scheduler import SkillScheduler
    scheduler = SkillScheduler(
        data_generator=gen_ref, stream_manager=stream_mgr, store=data_store,
    )
    application.state.skill_scheduler = scheduler
    await scheduler.start()

    logger.info(f"{settings.APP_NAME} v{settings.APP_VERSION} ready (data={data_source_used})")

    yield  # ── app runs here ──

    # ── Shutdown ─────────────────────────────────────────────────
    if hasattr(application.state, "skill_scheduler"):
        await application.state.skill_scheduler.stop()
    if hasattr(application.state, "data_consumer"):
        await application.state.data_consumer.stop()
    if hasattr(application.state, "data_generator"):
        await application.state.data_generator.stop()
    logger.info(f"Shutting down {settings.APP_NAME}")


def _kafka_reachable() -> bool:
    """Quick TCP probe to Kafka bootstrap server."""
    import socket
    host, _, port = settings.KAFKA_BOOTSTRAP_SERVERS.partition(",")
    host = host.strip()
    port = int(port.strip()) if port.strip() else 9092
    try:
        sock = socket.create_connection((host, port), timeout=3)
        sock.close()
        return True
    except Exception:
        return False


# ═══════════════════════════════════════════════════════════════════
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="AI-Native 电商实时监控智能决策平台 — V3.0 多智能体 A2A + MCP 可插拔工具链",
    lifespan=lifespan,
    docs_url="/docs" if settings.DEBUG else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
from app.api.v1 import dashboard, agent, alerts, admin, insights

app.include_router(dashboard.router, prefix="/api/v1/dashboard", tags=["Dashboard"])
app.include_router(agent.router, prefix="/api/v1/agent", tags=["Agent"])
app.include_router(alerts.router, prefix="/api/v1/alerts", tags=["Alerts"])
app.include_router(admin.router, prefix="/api/v1/admin", tags=["Admin"])
app.include_router(insights.router, prefix="/api/v1/insights", tags=["Insights"])

# MCP Server (HTTP transport)
if settings.MCP_SERVER_ENABLED:
    from app.mcp.server import mcp_router
    app.include_router(mcp_router, prefix="/mcp", tags=["MCP"])


@app.get("/health")
async def health():
    return {"status": "ok", "version": settings.APP_VERSION, "architecture": "V3.0 Multi-Agent A2A"}


@app.get("/")
async def root():
    return {
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "architecture": "V3.0 Multi-Agent A2A",
        "docs": "/docs",
    }
