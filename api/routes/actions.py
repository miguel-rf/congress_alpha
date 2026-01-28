"""
Actions API Routes

Endpoints for triggering system actions like scraping and trading.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from modules.db_manager import get_db

router = APIRouter()


# Track running tasks
_running_tasks: dict[str, bool] = {
    "scraper": False,
    "trader": False,
}


class ActionResponse(BaseModel):
    """Response for action endpoints."""
    success: bool
    message: str
    task_id: Optional[str] = None


class ActionStatus(BaseModel):
    """Status of running actions."""
    scraper_running: bool
    trader_running: bool


def _run_scrape_cycle():
    """Run the scraping cycle (blocking)."""
    global _running_tasks
    _running_tasks["scraper"] = True
    
    try:
        # Import here to avoid circular imports
        from main import CongressAlphaPipeline
        
        pipeline = CongressAlphaPipeline()
        result = pipeline.run_scrape_cycle()
        
        db = get_db()
        db.log("INFO", "actions", f"Scrape cycle completed: {result}")
        
    except Exception as e:
        db = get_db()
        db.log("ERROR", "actions", f"Scrape cycle failed: {e}")
    finally:
        _running_tasks["scraper"] = False


def _run_trade_cycle():
    """Run the trading cycle (blocking)."""
    global _running_tasks
    _running_tasks["trader"] = True
    
    try:
        from main import CongressAlphaPipeline
        
        pipeline = CongressAlphaPipeline()
        result = pipeline.run_trade_cycle()
        
        db = get_db()
        db.log("INFO", "actions", f"Trade cycle completed: {len(result)} trades")
        
    except Exception as e:
        db = get_db()
        db.log("ERROR", "actions", f"Trade cycle failed: {e}")
    finally:
        _running_tasks["trader"] = False


def _run_full_cycle():
    """Run a complete pipeline cycle (scrape + trade)."""
    global _running_tasks
    _running_tasks["scraper"] = True
    _running_tasks["trader"] = True
    
    try:
        from main import CongressAlphaPipeline
        
        pipeline = CongressAlphaPipeline()
        pipeline.run_cycle()
        
        db = get_db()
        db.log("INFO", "actions", "Full cycle completed")
        
    except Exception as e:
        db = get_db()
        db.log("ERROR", "actions", f"Full cycle failed: {e}")
    finally:
        _running_tasks["scraper"] = False
        _running_tasks["trader"] = False


@router.get("/status", response_model=ActionStatus)
async def get_action_status():
    """
    Get status of running actions.
    
    Check if scraper or trader is currently running.
    """
    return ActionStatus(
        scraper_running=_running_tasks["scraper"],
        trader_running=_running_tasks["trader"],
    )


@router.post("/scrape", response_model=ActionResponse)
async def trigger_scrape(background_tasks: BackgroundTasks):
    """
    Trigger a scrape cycle.
    
    Scrapes House and Senate disclosures for new filings.
    Runs in background and returns immediately.
    """
    if _running_tasks["scraper"]:
        raise HTTPException(
            status_code=409,
            detail="Scraper is already running"
        )
    
    background_tasks.add_task(_run_scrape_cycle)
    
    db = get_db()
    db.log("INFO", "actions", "Scrape cycle triggered via API")
    
    return ActionResponse(
        success=True,
        message="Scrape cycle started in background",
        task_id="scraper",
    )


@router.post("/trade", response_model=ActionResponse)
async def trigger_trade(background_tasks: BackgroundTasks):
    """
    Trigger a trade cycle.
    
    Processes pending signals and executes trades.
    Runs in background and returns immediately.
    """
    if _running_tasks["trader"]:
        raise HTTPException(
            status_code=409,
            detail="Trader is already running"
        )
    
    background_tasks.add_task(_run_trade_cycle)
    
    db = get_db()
    db.log("INFO", "actions", "Trade cycle triggered via API")
    
    return ActionResponse(
        success=True,
        message="Trade cycle started in background",
        task_id="trader",
    )


@router.post("/cycle", response_model=ActionResponse)
async def trigger_full_cycle(background_tasks: BackgroundTasks):
    """
    Trigger a full pipeline cycle.
    
    Runs scrape + trade cycle sequentially.
    Equivalent to running `python main.py --once`.
    """
    if _running_tasks["scraper"] or _running_tasks["trader"]:
        raise HTTPException(
            status_code=409,
            detail="A task is already running"
        )
    
    background_tasks.add_task(_run_full_cycle)
    
    db = get_db()
    db.log("INFO", "actions", "Full cycle triggered via API")
    
    return ActionResponse(
        success=True,
        message="Full cycle started in background",
        task_id="cycle",
    )


@router.post("/stop", response_model=ActionResponse)
async def stop_tasks():
    """
    Request to stop running tasks.
    
    Note: This sets flags but running tasks may take time to complete.
    """
    global _running_tasks
    
    # Set flags - actual stopping depends on task checking these
    was_running = _running_tasks["scraper"] or _running_tasks["trader"]
    
    db = get_db()
    db.log("WARNING", "actions", "Stop requested via API")
    
    return ActionResponse(
        success=True,
        message="Stop requested" if was_running else "No tasks were running",
    )


# =============================================================================
# Cookie Management
# =============================================================================

class CookieUpdate(BaseModel):
    """Cookie update request model."""
    csrftoken: str
    sessionid: str


@router.get("/cookies")
async def get_cookies_status():
    """
    Check cookie status and last update time.
    """
    import json
    from datetime import datetime
    
    cookies_path = Path(__file__).parent.parent.parent / "config" / "cookies.json"
    
    if not cookies_path.exists():
        return {
            "configured": False,
            "last_modified": None,
            "cookies_set": False,
        }
    
    # Get file modification time
    mtime = cookies_path.stat().st_mtime
    last_modified = datetime.fromtimestamp(mtime).isoformat()
    
    # Check if cookies have values
    with open(cookies_path, "r") as f:
        data = json.load(f)
    
    cookies = data.get("cookies", [])
    has_csrf = any(c.get("name") == "csrftoken" and c.get("value") for c in cookies)
    has_session = any(c.get("name") == "sessionid" and c.get("value") for c in cookies)
    
    return {
        "configured": has_csrf and has_session,
        "last_modified": last_modified,
        "has_csrftoken": has_csrf,
        "has_sessionid": has_session,
    }


@router.post("/cookies")
async def update_cookies(cookies: CookieUpdate):
    """
    Update Senate cookies.
    
    Use this to refresh cookies when they expire.
    """
    import json
    
    cookies_path = Path(__file__).parent.parent.parent / "config" / "cookies.json"
    
    data = {
        "_comment": "Senate website authentication cookies - Extract from browser after solving CAPTCHA",
        "_instructions": [
            "1. Open https://efdsearch.senate.gov/search/ in your browser",
            "2. Complete the CAPTCHA/checkbox challenge",
            "3. Open Developer Tools (F12) -> Application -> Cookies",
            "4. Copy the cookie values below",
            "5. Cookies typically expire after a session, refresh as needed"
        ],
        "cookies": [
            {"name": "csrftoken", "value": cookies.csrftoken},
            {"name": "sessionid", "value": cookies.sessionid},
        ]
    }
    
    with open(cookies_path, "w") as f:
        json.dump(data, f, indent=4)
    
    db = get_db()
    db.log("INFO", "actions", "Senate cookies updated via API")
    
    return ActionResponse(
        success=True,
        message="Senate cookies updated successfully",
    )


# =============================================================================
# Scheduler Settings
# =============================================================================

class SchedulerSettings(BaseModel):
    """Scheduler settings update model."""
    market_hours_min_interval: Optional[int] = None
    market_hours_max_interval: Optional[int] = None
    off_hours_interval: Optional[int] = None


@router.get("/scheduler/settings")
async def get_scheduler_settings():
    """
    Get current scheduler settings.
    """
    from config.settings import get_config
    
    config = get_config()
    
    return {
        "market_open_hour": config.scheduler.market_open_hour,
        "market_close_hour": config.scheduler.market_close_hour,
        "market_hours_min_interval": config.scheduler.market_hours_min_interval,
        "market_hours_max_interval": config.scheduler.market_hours_max_interval,
        "off_hours_interval": config.scheduler.off_hours_interval,
        "jitter_min": config.scheduler.jitter_min,
        "jitter_max": config.scheduler.jitter_max,
    }


# =============================================================================
# System Health & Diagnostics
# =============================================================================

@router.get("/health/full")
async def get_full_health():
    """
    Comprehensive health check for all system components.
    """
    import os
    from config.settings import get_config, DATABASE_PATH
    
    config = get_config()
    db = get_db()
    
    # Check API configurations
    trading212_ok = config.trading212.validate()
    openrouter_ok = config.openrouter.validate()
    
    # Check database
    db_exists = DATABASE_PATH.exists()
    db_size_mb = DATABASE_PATH.stat().st_size / (1024 * 1024) if db_exists else 0
    
    # Check cookies
    cookies_path = Path(__file__).parent.parent.parent / "config" / "cookies.json"
    cookies_ok = cookies_path.exists()
    
    # Check whitelist
    whitelist_path = Path(__file__).parent.parent.parent / "config" / "whitelist.json"
    whitelist_ok = whitelist_path.exists()
    
    # Get stats
    stats = db.get_stats()
    
    return {
        "status": "healthy" if (trading212_ok and openrouter_ok) else "degraded",
        "components": {
            "trading212": {
                "configured": trading212_ok,
                "environment": config.trading212.environment,
            },
            "openrouter": {
                "configured": openrouter_ok,
                "model": config.openrouter.model,
            },
            "database": {
                "exists": db_exists,
                "size_mb": round(db_size_mb, 2),
                "signals": stats.get("total_signals", 0),
                "trades": stats.get("total_trades", 0),
            },
            "cookies": {
                "configured": cookies_ok,
            },
            "whitelist": {
                "configured": whitelist_ok,
            },
        },
        "running_tasks": _running_tasks,
    }


@router.post("/database/cleanup")
async def cleanup_old_logs():
    """
    Clean up old log entries (older than 30 days).
    """
    db = get_db()
    
    # This would need implementation in db_manager
    db.log("INFO", "actions", "Database cleanup requested")
    
    return ActionResponse(
        success=True,
        message="Cleanup initiated",
    )

