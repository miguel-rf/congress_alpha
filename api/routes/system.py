"""
System API Routes

Endpoints for system monitoring, stats, and logs.
"""
from __future__ import annotations

from typing import Optional
from fastapi import APIRouter, Query
from pydantic import BaseModel

from config.settings import get_config
from modules.db_manager import get_db

router = APIRouter()


class SystemStats(BaseModel):
    """System statistics response model."""
    total_signals: int
    pending_signals: int
    processed_signals: int
    total_trades: int
    total_logs: int


class LogEntry(BaseModel):
    """Log entry response model."""
    id: Optional[int]
    level: str
    module: str
    message: str
    created_at: Optional[str]


class ConfigResponse(BaseModel):
    """Sanitized configuration response."""
    trading212_configured: bool
    trading212_environment: str
    openrouter_configured: bool
    market_open_hour: int
    market_close_hour: int
    min_market_cap: float
    wash_sale_days: int
    immediate_signal_max_lag: int
    stale_signal_threshold: int


@router.get("/stats", response_model=SystemStats)
async def get_system_stats():
    """
    Get system statistics.
    
    Returns counts for signals, trades, and logs.
    """
    db = get_db()
    stats = db.get_stats()
    
    return SystemStats(
        total_signals=stats.get("total_signals", 0),
        pending_signals=stats.get("pending_signals", 0),
        processed_signals=stats.get("processed_signals", 0),
        total_trades=stats.get("total_trades", 0),
        total_logs=stats.get("total_logs", 0),
    )


@router.get("/logs", response_model=list[LogEntry])
async def get_logs(
    limit: int = Query(100, ge=1, le=500, description="Number of logs to return"),
    level: Optional[str] = Query(None, description="Filter by log level (INFO, WARNING, ERROR)"),
):
    """
    Get recent system logs.
    
    - **limit**: Maximum number of logs (default: 100, max: 500)
    - **level**: Filter by log level (INFO, WARNING, ERROR)
    """
    db = get_db()
    logs = db.get_recent_logs(limit=limit, level=level.upper() if level else None)
    
    return [
        LogEntry(
            id=log.id,
            level=log.level,
            module=log.module,
            message=log.message,
            created_at=log.created_at,
        )
        for log in logs
    ]


@router.get("/config", response_model=ConfigResponse)
async def get_config_info():
    """
    Get current system configuration.
    
    Returns sanitized config (no secrets).
    """
    config = get_config()
    
    return ConfigResponse(
        trading212_configured=config.trading212.validate(),
        trading212_environment=config.trading212.environment,
        openrouter_configured=config.openrouter.validate(),
        market_open_hour=config.scheduler.market_open_hour,
        market_close_hour=config.scheduler.market_close_hour,
        min_market_cap=config.trading.min_market_cap,
        wash_sale_days=config.trading.wash_sale_days,
        immediate_signal_max_lag=config.trading.immediate_signal_max_lag,
        stale_signal_threshold=config.trading.stale_signal_threshold,
    )


@router.get("/scheduler/status")
async def get_scheduler_status():
    """Get scheduler status information."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    
    config = get_config()
    now_et = datetime.now(ZoneInfo("America/New_York"))
    
    # Check if market hours
    is_weekday = now_et.weekday() < 5
    is_market_hours = (
        is_weekday and
        config.scheduler.market_open_hour <= now_et.hour < config.scheduler.market_close_hour
    )
    
    return {
        "current_time_et": now_et.isoformat(),
        "is_market_hours": is_market_hours,
        "market_open": f"{config.scheduler.market_open_hour}:00 ET",
        "market_close": f"{config.scheduler.market_close_hour}:00 ET",
        "interval_minutes": (
            f"{config.scheduler.market_hours_min_interval}-{config.scheduler.market_hours_max_interval}"
            if is_market_hours
            else str(config.scheduler.off_hours_interval)
        ),
    }
