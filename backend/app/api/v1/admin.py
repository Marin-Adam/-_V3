"""Admin API — system stats, Skill management, and health overview."""

from fastapi import APIRouter, Request
from app.agent.skill_loader import SkillLoader

router = APIRouter()


@router.get("/stats")
async def get_stats(request: Request):
    """Get comprehensive system statistics."""
    gen = request.app.state.data_generator if hasattr(request.app.state, "data_generator") else None
    streams = request.app.state.stream_manager if hasattr(request.app.state, "stream_manager") else None
    store = request.app.state.data_store if hasattr(request.app.state, "data_store") else None
    consumer = request.app.state.data_consumer if hasattr(request.app.state, "data_consumer") else None

    # Data source
    data_source = "generator"
    if consumer:
        data_source = "kafka" if hasattr(consumer, "dedup") else "polling"
    elif gen and gen._running:
        data_source = "generator"
    else:
        data_source = "none"

    stats = {
        "app": "ecom-ai-dashboard",
        "data_source": data_source,
        "generator_running": gen._running if gen else False,

        # Store stats
        "total_orders_in_memory": len(store.orders) if store else 0,
        "tracked_products": len(store.traffic) if store else 0,

        # Stream window stats
        "active_streams": len(streams.get_all_windows()) if streams else 0,

        # Skills
        "skills_loaded": len(SkillLoader().list_skills()),
    }

    # Add DB stats if available
    try:
        from app.data.warehouse import DataWarehouse
        wh = DataWarehouse(request)
        open_alerts = await wh.get_open_alerts()
        stats["open_alerts_db"] = len(open_alerts)
        stats["open_alerts_p0"] = len([a for a in open_alerts if a.get("severity") == "P0"])
        stats["open_alerts_p1"] = len([a for a in open_alerts if a.get("severity") == "P1"])
        stats["open_alerts_p2"] = len([a for a in open_alerts if a.get("severity") == "P2"])
    except Exception:
        stats["open_alerts_db"] = -1  # DB unavailable

    return stats


@router.post("/skills/reload")
async def reload_skills():
    """Hot-reload all Agent Skills from filesystem."""
    loader = SkillLoader()
    loader.reload()
    return {"status": "reloaded", "skill_count": len(loader.list_skills())}
