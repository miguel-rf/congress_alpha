"""
Trade Signals API Routes

Endpoints for managing congressional trade signals.
"""
from __future__ import annotations

from typing import Optional
from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel

from modules.db_manager import get_db, TradeSignal

router = APIRouter()


class SignalResponse(BaseModel):
    """Trade signal response model."""
    id: Optional[int]
    ticker: str
    politician: str
    trade_type: str
    amount_midpoint: float
    trade_date: str
    disclosure_date: str
    lag_days: int
    signal_type: str
    chamber: str
    asset_name: Optional[str]
    pdf_url: Optional[str]
    processed: bool
    status: str = "pending"
    created_at: Optional[str]

    class Config:
        from_attributes = True


class PaginatedSignals(BaseModel):
    """Paginated signals response."""
    items: list[SignalResponse]
    total: int
    page: int
    page_size: int
    pages: int


@router.get("", response_model=PaginatedSignals)
async def list_signals(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    processed: Optional[bool] = Query(None, description="Filter by processed status"),
    politician: Optional[str] = Query(None, description="Filter by politician name"),
    ticker: Optional[str] = Query(None, description="Filter by ticker symbol"),
):
    """
    List trade signals with pagination and filtering.
    
    - **page**: Page number (default: 1)
    - **page_size**: Items per page (default: 20, max: 100)
    - **processed**: Filter by processed status
    - **politician**: Filter by politician name (partial match)
    - **ticker**: Filter by ticker symbol
    """
    db = get_db()
    
    with db.get_connection() as conn:
        cursor = conn.cursor()
        
        # Build query with filters
        where_clauses = []
        params = []
        
        if processed is not None:
            where_clauses.append("processed = ?")
            params.append(1 if processed else 0)
        
        if politician:
            where_clauses.append("politician LIKE ?")
            params.append(f"%{politician}%")
        
        if ticker:
            where_clauses.append("ticker LIKE ?")
            params.append(f"%{ticker.upper()}%")
        
        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
        
        # Get total count
        cursor.execute(f"SELECT COUNT(*) FROM trades {where_sql}", params)
        total = cursor.fetchone()[0]
        
        # Calculate pagination
        offset = (page - 1) * page_size
        pages = max(1, (total + page_size - 1) // page_size)
        
        # Fetch signals
        cursor.execute(
            f"""
            SELECT id, ticker, politician, trade_type, amount_midpoint,
                   trade_date, disclosure_date, lag_days, signal_type,
                   chamber, asset_name, pdf_url, processed, 
                   COALESCE(status, 'pending') as status, created_at
            FROM trades
            {where_sql}
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
            """,
            params + [page_size, offset]
        )
        
        signals = [
            SignalResponse(
                id=row[0],
                ticker=row[1],
                politician=row[2],
                trade_type=row[3],
                amount_midpoint=row[4],
                trade_date=row[5],
                disclosure_date=row[6],
                lag_days=row[7],
                signal_type=row[8],
                chamber=row[9],
                asset_name=row[10],
                pdf_url=row[11],
                processed=bool(row[12]),
                status=row[13] or "pending",
                created_at=row[14],
            )
            for row in cursor.fetchall()
        ]
    
    return PaginatedSignals(
        items=signals,
        total=total,
        page=page,
        page_size=page_size,
        pages=pages,
    )


@router.get("/pending", response_model=list[SignalResponse])
async def get_pending_signals():
    """Get all unprocessed trade signals."""
    db = get_db()
    signals = db.get_unprocessed_signals()
    
    return [
        SignalResponse(
            id=s.id,
            ticker=s.ticker,
            politician=s.politician,
            trade_type=s.trade_type,
            amount_midpoint=s.amount_midpoint,
            trade_date=s.trade_date,
            disclosure_date=s.disclosure_date,
            lag_days=s.lag_days,
            signal_type=s.signal_type,
            chamber=s.chamber,
            asset_name=s.asset_name,
            pdf_url=s.pdf_url,
            processed=s.processed,
            status=getattr(s, 'status', 'pending'),
            created_at=s.created_at,
        )
        for s in signals
    ]


@router.get("/confirmations", response_model=list[SignalResponse])
async def get_pending_confirmations():
    """Get all signals waiting for user confirmation (lag 11-90 days)."""
    db = get_db()
    signals = db.get_pending_confirmations()
    
    return [
        SignalResponse(
            id=s.id,
            ticker=s.ticker,
            politician=s.politician,
            trade_type=s.trade_type,
            amount_midpoint=s.amount_midpoint,
            trade_date=s.trade_date,
            disclosure_date=s.disclosure_date,
            lag_days=s.lag_days,
            signal_type=s.signal_type,
            chamber=s.chamber,
            asset_name=s.asset_name,
            pdf_url=s.pdf_url,
            processed=s.processed,
            status=getattr(s, 'status', 'pending_confirmation'),
            created_at=s.created_at,
        )
        for s in signals
    ]


@router.get("/{signal_id}", response_model=SignalResponse)
async def get_signal(signal_id: int):
    """Get a specific trade signal by ID."""
    db = get_db()
    
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, ticker, politician, trade_type, amount_midpoint,
                   trade_date, disclosure_date, lag_days, signal_type,
                   chamber, asset_name, pdf_url, processed, 
                   COALESCE(status, 'pending') as status, created_at
            FROM trades
            WHERE id = ?
            """,
            (signal_id,)
        )
        row = cursor.fetchone()
    
    if not row:
        raise HTTPException(status_code=404, detail="Signal not found")
    
    return SignalResponse(
        id=row[0],
        ticker=row[1],
        politician=row[2],
        trade_type=row[3],
        amount_midpoint=row[4],
        trade_date=row[5],
        disclosure_date=row[6],
        lag_days=row[7],
        signal_type=row[8],
        chamber=row[9],
        asset_name=row[10],
        pdf_url=row[11],
        processed=bool(row[12]),
        status=row[13] or "pending",
        created_at=row[14],
    )


@router.post("/{signal_id}/confirm")
async def confirm_signal(signal_id: int):
    """
    Confirm a signal for execution.
    
    Signals with lag 11-90 days require manual confirmation before trading.
    """
    db = get_db()
    
    # Check if signal exists and is pending confirmation
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, status FROM trades WHERE id = ?", (signal_id,))
        row = cursor.fetchone()
        
        if not row:
            raise HTTPException(status_code=404, detail="Signal not found")
        
        if row[1] not in ('pending', 'pending_confirmation'):
            raise HTTPException(
                status_code=400, 
                detail=f"Signal cannot be confirmed (current status: {row[1]})"
            )
    
    success = db.confirm_signal(signal_id)
    if success:
        return {"status": "success", "message": f"Signal {signal_id} confirmed for execution"}
    else:
        raise HTTPException(status_code=400, detail="Failed to confirm signal")


@router.post("/{signal_id}/reject")
async def reject_signal(signal_id: int):
    """
    Reject a signal - it will not be executed.
    
    Signals with lag 11-90 days can be rejected if user doesn't want to trade.
    """
    db = get_db()
    
    # Check if signal exists and is pending confirmation
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, status FROM trades WHERE id = ?", (signal_id,))
        row = cursor.fetchone()
        
        if not row:
            raise HTTPException(status_code=404, detail="Signal not found")
        
        if row[1] not in ('pending', 'pending_confirmation'):
            raise HTTPException(
                status_code=400, 
                detail=f"Signal cannot be rejected (current status: {row[1]})"
            )
    
    success = db.reject_signal(signal_id)
    if success:
        return {"status": "success", "message": f"Signal {signal_id} rejected"}
    else:
        raise HTTPException(status_code=400, detail="Failed to reject signal")


@router.post("/{signal_id}/process")
async def mark_signal_processed(signal_id: int):
    """Mark a signal as processed."""
    db = get_db()
    
    # Check if signal exists
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM trades WHERE id = ?", (signal_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="Signal not found")
    
    db.mark_signal_processed(signal_id)
    return {"status": "success", "message": f"Signal {signal_id} marked as processed"}


@router.delete("/{signal_id}")
async def delete_signal(signal_id: int):
    """
    Delete a signal permanently.
    """
    db = get_db()
    
    success = db.delete_signal(signal_id)
    if success:
        return {"status": "success", "message": f"Signal {signal_id} deleted"}
    else:
        raise HTTPException(status_code=404, detail="Signal not found")


@router.delete("")
async def delete_all_signals(
    processed_only: bool = Query(False, description="Only delete processed signals")
):
    """
    Delete all signals.
    
    - **processed_only**: If true, only delete processed/executed signals
    """
    db = get_db()
    
    count = db.delete_all_signals(processed_only=processed_only)
    return {
        "status": "success", 
        "message": f"Deleted {count} signals",
        "deleted_count": count
    }
