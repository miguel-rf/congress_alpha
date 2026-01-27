"""
Trade History API Routes

Endpoints for viewing executed trades and statistics.
"""
from __future__ import annotations

from typing import Optional
from fastapi import APIRouter, Query
from pydantic import BaseModel

from modules.db_manager import get_db

router = APIRouter()


class TradeResponse(BaseModel):
    """Executed trade response model."""
    id: Optional[int]
    ticker: str
    trade_type: str
    shares: float
    price: float
    executed_at: str
    pnl: Optional[float]
    signal_id: Optional[int]

    class Config:
        from_attributes = True


class PaginatedTrades(BaseModel):
    """Paginated trades response."""
    items: list[TradeResponse]
    total: int
    page: int
    page_size: int
    pages: int


class TradeStats(BaseModel):
    """Aggregate trading statistics."""
    total_trades: int
    total_buys: int
    total_sells: int
    realized_pnl: float
    win_rate: float
    avg_trade_size: float
    best_trade: Optional[float]
    worst_trade: Optional[float]


@router.get("", response_model=PaginatedTrades)
async def list_trades(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    ticker: Optional[str] = Query(None, description="Filter by ticker"),
    trade_type: Optional[str] = Query(None, description="Filter by trade type (buy/sell)"),
):
    """
    List executed trades with pagination.
    
    - **page**: Page number (default: 1)
    - **page_size**: Items per page (default: 20, max: 100)
    - **ticker**: Filter by ticker symbol
    - **trade_type**: Filter by trade type (buy/sell)
    """
    db = get_db()
    
    with db.get_connection() as conn:
        cursor = conn.cursor()
        
        # Build query with filters
        where_clauses = []
        params = []
        
        if ticker:
            where_clauses.append("ticker LIKE ?")
            params.append(f"%{ticker.upper()}%")
        
        if trade_type:
            where_clauses.append("trade_type = ?")
            params.append(trade_type.lower())
        
        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
        
        # Get total count
        cursor.execute(f"SELECT COUNT(*) FROM trade_history {where_sql}", params)
        total = cursor.fetchone()[0]
        
        # Calculate pagination
        offset = (page - 1) * page_size
        pages = max(1, (total + page_size - 1) // page_size)
        
        # Fetch trades
        cursor.execute(
            f"""
            SELECT id, ticker, trade_type, shares, price, executed_at, pnl, signal_id
            FROM trade_history
            {where_sql}
            ORDER BY executed_at DESC
            LIMIT ? OFFSET ?
            """,
            params + [page_size, offset]
        )
        
        trades = [
            TradeResponse(
                id=row[0],
                ticker=row[1],
                trade_type=row[2],
                shares=row[3],
                price=row[4],
                executed_at=row[5],
                pnl=row[6],
                signal_id=row[7],
            )
            for row in cursor.fetchall()
        ]
    
    return PaginatedTrades(
        items=trades,
        total=total,
        page=page,
        page_size=page_size,
        pages=pages,
    )


@router.get("/stats", response_model=TradeStats)
async def get_trade_stats():
    """Get aggregate trading statistics."""
    db = get_db()
    
    with db.get_connection() as conn:
        cursor = conn.cursor()
        
        # Total trades
        cursor.execute("SELECT COUNT(*) FROM trade_history")
        total_trades = cursor.fetchone()[0]
        
        # Buys vs Sells
        cursor.execute("SELECT COUNT(*) FROM trade_history WHERE trade_type = 'buy'")
        total_buys = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM trade_history WHERE trade_type = 'sell'")
        total_sells = cursor.fetchone()[0]
        
        # Realized P&L (only from sells)
        cursor.execute("SELECT COALESCE(SUM(pnl), 0) FROM trade_history WHERE pnl IS NOT NULL")
        realized_pnl = cursor.fetchone()[0] or 0.0
        
        # Win rate (trades with positive P&L)
        cursor.execute("SELECT COUNT(*) FROM trade_history WHERE pnl > 0")
        wins = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM trade_history WHERE pnl IS NOT NULL AND pnl != 0")
        closed_trades = cursor.fetchone()[0]
        
        win_rate = (wins / closed_trades * 100) if closed_trades > 0 else 0.0
        
        # Average trade size
        cursor.execute("SELECT AVG(shares * price) FROM trade_history")
        avg_trade_size = cursor.fetchone()[0] or 0.0
        
        # Best and worst trades
        cursor.execute("SELECT MAX(pnl) FROM trade_history WHERE pnl IS NOT NULL")
        best_trade = cursor.fetchone()[0]
        
        cursor.execute("SELECT MIN(pnl) FROM trade_history WHERE pnl IS NOT NULL")
        worst_trade = cursor.fetchone()[0]
    
    return TradeStats(
        total_trades=total_trades,
        total_buys=total_buys,
        total_sells=total_sells,
        realized_pnl=float(realized_pnl),
        win_rate=round(win_rate, 2),
        avg_trade_size=round(float(avg_trade_size), 2),
        best_trade=float(best_trade) if best_trade else None,
        worst_trade=float(worst_trade) if worst_trade else None,
    )


@router.get("/ticker/{ticker}", response_model=list[TradeResponse])
async def get_trades_by_ticker(ticker: str):
    """Get all trades for a specific ticker."""
    db = get_db()
    history = db.get_position_history(ticker.upper())
    
    return [
        TradeResponse(
            id=h.id,
            ticker=h.ticker,
            trade_type=h.trade_type,
            shares=h.shares,
            price=h.price,
            executed_at=h.executed_at,
            pnl=h.pnl,
            signal_id=h.signal_id,
        )
        for h in history
    ]
