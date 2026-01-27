"""
Portfolio API Routes

Endpoints for Trading212 portfolio data.
"""
from __future__ import annotations

from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from config.settings import get_config
from modules.trade_executor import Trading212Client, SymbolMapper

router = APIRouter()


class PositionResponse(BaseModel):
    """Trading position response model."""
    ticker: str
    quantity: float
    average_price: float
    current_price: Optional[float]
    market_value: Optional[float]
    pnl: Optional[float]
    pnl_percent: Optional[float]


class AccountSummary(BaseModel):
    """Account summary response model."""
    total_value: float
    cash_available: float
    invested_value: float
    unrealized_pnl: float
    currency: str


class CashBalance(BaseModel):
    """Cash balance response model."""
    free: float
    total: float
    currency: str


def _get_client() -> Trading212Client:
    """Get Trading212 client or raise error if not configured."""
    config = get_config()
    if not config.trading212.validate():
        raise HTTPException(
            status_code=503,
            detail="Trading212 API not configured. Set TRADING212_API_KEY and TRADING212_API_SECRET."
        )
    return Trading212Client(
        api_key=config.trading212.api_key,
        api_secret=config.trading212.api_secret,
        base_url=config.trading212.base_url,
    )


@router.get("/positions", response_model=list[PositionResponse])
async def get_positions():
    """
    Get all open positions from Trading212.
    
    Returns current portfolio holdings with P&L calculations.
    """
    try:
        client = _get_client()
        mapper = SymbolMapper()
        
        positions_data = client.get_positions()
        client.close()
        
        positions = []
        for pos in positions_data:
            ticker = mapper.from_trading212(pos.get("ticker", ""))
            quantity = pos.get("quantity", 0)
            avg_price = pos.get("averagePrice", 0)
            current_price = pos.get("currentPrice")
            pnl = pos.get("pnl")
            
            market_value = None
            pnl_percent = None
            
            if current_price and quantity:
                market_value = current_price * quantity
            
            if pnl and avg_price and quantity:
                cost_basis = avg_price * quantity
                if cost_basis > 0:
                    pnl_percent = (pnl / cost_basis) * 100
            
            positions.append(PositionResponse(
                ticker=ticker,
                quantity=quantity,
                average_price=avg_price,
                current_price=current_price,
                market_value=market_value,
                pnl=pnl,
                pnl_percent=round(pnl_percent, 2) if pnl_percent else None,
            ))
        
        return positions
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch positions: {str(e)}")


@router.get("/summary", response_model=AccountSummary)
async def get_account_summary():
    """
    Get account summary from Trading212.
    
    Returns total value, cash, investments, and unrealized P&L.
    """
    try:
        client = _get_client()
        summary = client.get_account_summary()
        client.close()
        
        cash_data = summary.get("cash", {})
        investments = summary.get("investments", {})
        
        return AccountSummary(
            total_value=summary.get("totalValue", 0),
            cash_available=cash_data.get("availableToTrade", 0),
            invested_value=investments.get("currentValue", 0),
            unrealized_pnl=investments.get("unrealizedProfitLoss", 0),
            currency=summary.get("currency", "USD"),
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch summary: {str(e)}")


@router.get("/cash", response_model=CashBalance)
async def get_cash_balance():
    """Get available cash balance."""
    try:
        client = _get_client()
        summary = client.get_account_summary()
        client.close()
        
        cash_data = summary.get("cash", {})
        
        return CashBalance(
            free=cash_data.get("availableToTrade", 0),
            total=cash_data.get("total", 0),
            currency=summary.get("currency", "USD"),
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch cash: {str(e)}")
