"""
Congressional Alpha System - Trade Executor

Executes trades on Trading212 with comprehensive risk guards:
- Liquidity Filter (Market Cap > $300M)
- Wash Sale Guard (30-day lookback)
"""
from __future__ import annotations

import base64
import json
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from dataclasses import dataclass

import httpx
import yfinance as yf

# Local imports
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from config.settings import get_config, CONFIG_DIR, logger
from modules.db_manager import get_db, TradeSignal, TradeHistory

# Module logger
trade_logger = logging.getLogger("congress_alpha.trade_executor")


# -----------------------------------------------------------------------------
# Data Models
# -----------------------------------------------------------------------------
@dataclass
class TradeResult:
    """Result of a trade execution attempt."""
    success: bool
    ticker: str
    side: str  # 'buy' or 'sell'
    shares: Optional[float] = None
    price: Optional[float] = None
    order_id: Optional[str] = None
    rejected_reason: Optional[str] = None
    message: str = ""


# -----------------------------------------------------------------------------
# Symbol Mapper for Trading212
# -----------------------------------------------------------------------------
class SymbolMapper:
    """Maps standard tickers to Trading212 format."""
    
    def __init__(self, symbol_map_path: Path = CONFIG_DIR / "symbol_map.json"):
        self.symbol_map_path = symbol_map_path
        self._explicit_mappings: dict = {}
        self._default_suffix: str = "_US_EQ"
        self._load_mapping()
    
    def _load_mapping(self) -> None:
        """Load symbol mapping from JSON."""
        if not self.symbol_map_path.exists():
            trade_logger.warning(f"Symbol map not found: {self.symbol_map_path}")
            return
        
        try:
            with open(self.symbol_map_path, 'r') as f:
                data = json.load(f)
            
            self._explicit_mappings = data.get('explicit_mappings', {})
            self._default_suffix = data.get('default_suffix', '_US_EQ')
            trade_logger.info(f"Loaded symbol map with {len(self._explicit_mappings)} explicit mappings")
            
        except (json.JSONDecodeError, KeyError) as e:
            trade_logger.error(f"Error loading symbol map: {e}")
    
    def to_trading212(self, ticker: str) -> str:
        """Convert standard ticker to Trading212 format.
        
        Examples:
            AAPL -> AAPL_US_EQ
            BRK.B -> BRKb_US_EQ (explicit mapping)
        """
        ticker_upper = ticker.upper()
        
        # Check explicit mappings first
        if ticker_upper in self._explicit_mappings:
            return self._explicit_mappings[ticker_upper]
        
        # Default: append suffix
        return f"{ticker_upper}{self._default_suffix}"
    
    def from_trading212(self, t212_ticker: str) -> str:
        """Convert Trading212 ticker back to standard format.
        
        Examples:
            AAPL_US_EQ -> AAPL
        """
        # Check if it's an explicit mapping (reverse lookup)
        for standard, t212 in self._explicit_mappings.items():
            if t212 == t212_ticker:
                return standard
        
        # Default: strip suffix
        if t212_ticker.endswith(self._default_suffix):
            return t212_ticker[:-len(self._default_suffix)]
        return t212_ticker


# -----------------------------------------------------------------------------
# Sector ETF Mapping
# -----------------------------------------------------------------------------
class SectorMapper:
    """Maps tickers to sector ETFs for stale signal rotation."""
    
    def __init__(self, sector_map_path: Path = CONFIG_DIR / "sector_map.json"):
        self.sector_map_path = sector_map_path
        self._mapping: dict = {}
        self._default_etf: str = "SPY"
        self._load_mapping()
    
    def _load_mapping(self) -> None:
        """Load sector mapping from JSON."""
        if not self.sector_map_path.exists():
            trade_logger.warning(f"Sector map not found: {self.sector_map_path}")
            return
        
        try:
            with open(self.sector_map_path, 'r') as f:
                data = json.load(f)
            
            self._mapping = data.get('ticker_to_sector', {})
            self._default_etf = data.get('default_etf', 'SPY')
            trade_logger.info(f"Loaded {len(self._mapping)} ticker mappings")
            
        except (json.JSONDecodeError, KeyError) as e:
            trade_logger.error(f"Error loading sector map: {e}")
    
    def get_sector_etf(self, ticker: str) -> str:
        """Get the sector ETF for a ticker, or default if not mapped."""
        return self._mapping.get(ticker.upper(), self._default_etf)


# -----------------------------------------------------------------------------
# Trading212 API Client
# -----------------------------------------------------------------------------
class Trading212Client:
    """HTTP client for Trading212 API with rate limiting."""
    
    # Rate limits from API docs
    RATE_LIMITS = {
        'market_order': (50, 60),    # 50 requests per 60 seconds
        'account_summary': (1, 5),    # 1 request per 5 seconds
        'positions': (1, 1),          # 1 request per 1 second
        'default': (1, 1),
    }
    
    def __init__(self, api_key: str, api_secret: str, base_url: str):
        self.base_url = base_url.rstrip('/')
        
        # Build Basic Auth header
        credentials = f"{api_key}:{api_secret}"
        encoded = base64.b64encode(credentials.encode()).decode()
        self.headers = {
            "Authorization": f"Basic {encoded}",
            "Content-Type": "application/json"
        }
        
        self._client = httpx.Client(timeout=30.0, headers=self.headers)
        self._last_request_times: dict[str, float] = {}
    
    def _rate_limit(self, endpoint_type: str = 'default') -> None:
        """Apply rate limiting based on endpoint type."""
        limit, period = self.RATE_LIMITS.get(endpoint_type, self.RATE_LIMITS['default'])
        min_interval = period / limit
        
        last_time = self._last_request_times.get(endpoint_type, 0)
        elapsed = time.time() - last_time
        
        if elapsed < min_interval:
            sleep_time = min_interval - elapsed
            trade_logger.debug(f"Rate limiting: sleeping {sleep_time:.2f}s for {endpoint_type}")
            time.sleep(sleep_time)
        
        self._last_request_times[endpoint_type] = time.time()
    
    def _request(self, method: str, path: str, endpoint_type: str = 'default', 
                 json_data: dict = None) -> Optional[dict]:
        """Make an API request with error handling."""
        self._rate_limit(endpoint_type)
        
        url = f"{self.base_url}{path}"
        
        try:
            if method == 'GET':
                response = self._client.get(url)
            elif method == 'POST':
                response = self._client.post(url, json=json_data)
            elif method == 'DELETE':
                response = self._client.delete(url)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")
            
            if response.status_code == 200:
                return response.json() if response.text else {}
            elif response.status_code == 401:
                trade_logger.error("Trading212 API: Invalid credentials")
            elif response.status_code == 403:
                trade_logger.error(f"Trading212 API: Forbidden - {response.text}")
            elif response.status_code == 429:
                trade_logger.warning("Trading212 API: Rate limited")
            else:
                trade_logger.error(f"Trading212 API error {response.status_code}: {response.text}")
            
            return None
            
        except httpx.RequestError as e:
            trade_logger.error(f"Trading212 request failed: {e}")
            return None
    
    def get_account_summary(self) -> Optional[dict]:
        """Get account summary including cash and investments.
        
        Returns:
            {
                'id': int,
                'currency': str,
                'totalValue': float,
                'cash': {'availableToTrade': float, ...},
                'investments': {'currentValue': float, 'unrealizedProfitLoss': float, ...}
            }
        """
        return self._request('GET', '/api/v0/equity/account/summary', 'account_summary')
    
    def get_positions(self, ticker: str = None) -> Optional[list]:
        """Get all open positions or filter by ticker.
        
        Args:
            ticker: Optional Trading212 ticker (e.g., AAPL_US_EQ)
        
        Returns:
            List of position dicts
        """
        path = '/api/v0/equity/positions'
        if ticker:
            path += f'?ticker={ticker}'
        return self._request('GET', path, 'positions')
    
    def place_market_order(self, ticker: str, quantity: float, 
                          extended_hours: bool = False) -> Optional[dict]:
        """Place a market order.
        
        Args:
            ticker: Trading212 ticker (e.g., AAPL_US_EQ)
            quantity: Number of shares. POSITIVE for buy, NEGATIVE for sell.
            extended_hours: Allow execution outside regular hours
        
        Returns:
            Order dict with id, status, etc.
        """
        data = {
            "ticker": ticker,
            "quantity": quantity,
            "extendedHours": extended_hours
        }
        return self._request('POST', '/api/v0/equity/orders/market', 'market_order', data)
    
    def get_pending_orders(self) -> Optional[list]:
        """Get all pending orders."""
        return self._request('GET', '/api/v0/equity/orders', 'default')
    
    def cancel_order(self, order_id: int) -> bool:
        """Cancel a pending order by ID."""
        result = self._request('DELETE', f'/api/v0/equity/orders/{order_id}', 'default')
        return result is not None
    
    def close(self) -> None:
        """Close the HTTP client."""
        self._client.close()


# -----------------------------------------------------------------------------
# Risk Guards
# -----------------------------------------------------------------------------
class RiskGuards:
    """Implements all trading risk checks."""
    
    def __init__(self):
        self.config = get_config()
        self.db = get_db()
    
    def check_liquidity(self, ticker: str) -> tuple[bool, str]:
        """
        Liquidity Filter: Check if market cap > $300M.
        
        Rejects micro-cap stocks due to slippage and manipulation risk.
        
        Returns:
            (passed, message)
        """
        try:
            stock = yf.Ticker(ticker)
            info = stock.info
            
            market_cap = info.get('marketCap', 0)
            
            if market_cap == 0:
                # Try to estimate from shares * price
                shares = info.get('sharesOutstanding', 0)
                price = info.get('regularMarketPrice', info.get('previousClose', 0))
                market_cap = shares * price
            
            min_cap = self.config.trading.min_market_cap
            
            if market_cap < min_cap:
                return False, f"Market cap ${market_cap:,.0f} < ${min_cap:,.0f} (micro-cap rejected)"
            
            return True, f"Market cap ${market_cap:,.0f} OK"
            
        except Exception as e:
            trade_logger.warning(f"Could not verify market cap for {ticker}: {e}")
            # Conservative: reject if we can't verify
            return False, f"Could not verify market cap: {e}"
    
    def check_wash_sale(self, ticker: str) -> tuple[bool, str]:
        """
        Wash Sale Guard: Check if we sold this ticker at a loss in last 30 days.
        
        The IRS wash sale rule disallows loss deduction if you buy back
        within 30 days of selling at a loss.
        
        Returns:
            (can_trade, message) - False means DO NOT BUY
        """
        lookback = self.config.trading.wash_sale_days
        
        if self.db.check_wash_sale(ticker, lookback):
            return False, f"Wash sale: {ticker} sold at loss within {lookback} days"
        
        return True, "Wash sale check passed"
    
    def run_buy_checks(self, ticker: str) -> tuple[bool, list[str]]:
        """
        Run all pre-buy checks.
        
        Returns:
            (can_buy, list of check messages)
        """
        messages = []
        can_buy = True
        
        # Liquidity check
        passed, msg = self.check_liquidity(ticker)
        messages.append(f"Liquidity: {msg}")
        if not passed:
            can_buy = False
        
        # Wash sale check
        passed, msg = self.check_wash_sale(ticker)
        messages.append(f"Wash Sale: {msg}")
        if not passed:
            can_buy = False
        
        return can_buy, messages


# -----------------------------------------------------------------------------
# Position Sizer
# -----------------------------------------------------------------------------
class PositionSizer:
    """
    Calculates position sizes based on portfolio value and conviction level.
    
    Algorithm:
    1. Base position = base_position_pct * portfolio_value
    2. Scale based on politician's trade size (conviction indicator):
       - Small trades (<$15k): use base position
       - Large trades (>$250k): use max position  
       - In between: linear interpolation
    3. Ensure position doesn't exceed available cash
    4. Ensure position meets minimum trade threshold
    """
    
    def __init__(self):
        self.config = get_config()
    
    def calculate_position(
        self,
        portfolio_value: float,
        available_cash: float,
        politician_amount: float,
        current_price: float,
        existing_position_value: float = 0.0
    ) -> tuple[float, str]:
        """
        Calculate the number of shares to buy.
        
        Args:
            portfolio_value: Total account value
            available_cash: Cash available to trade
            politician_amount: The midpoint dollar amount of politician's trade
            current_price: Current stock price
            existing_position_value: Value of existing position in this ticker
        
        Returns:
            (shares_to_buy, explanation_message)
        """
        tc = self.config.trading
        
        # Handle edge cases
        if portfolio_value <= 0:
            return 0.0, "Portfolio value is zero or negative"
        
        if available_cash < tc.min_trade_amount:
            return 0.0, f"Insufficient cash: ${available_cash:.2f} < ${tc.min_trade_amount:.2f} minimum"
        
        if current_price <= 0:
            return 0.0, "Invalid stock price"
        
        # Step 1: Calculate conviction multiplier based on politician's trade size
        # Linear interpolation between low and high conviction thresholds
        if politician_amount <= tc.low_conviction_threshold:
            conviction_mult = 0.0  # Base position
        elif politician_amount >= tc.high_conviction_threshold:
            conviction_mult = 1.0  # Max position
        else:
            # Linear interpolation
            conviction_mult = (politician_amount - tc.low_conviction_threshold) / \
                            (tc.high_conviction_threshold - tc.low_conviction_threshold)
        
        # Step 2: Calculate target position percentage
        # Interpolate between base_position_pct and max_position_pct
        target_pct = tc.base_position_pct + conviction_mult * (tc.max_position_pct - tc.base_position_pct)
        
        # Step 3: Calculate target position value
        target_value = portfolio_value * target_pct
        
        # Step 4: Account for existing position
        # Don't add more if we already have a significant position
        additional_value = max(0, target_value - existing_position_value)
        
        if additional_value < tc.min_trade_amount:
            return 0.0, f"Already have sufficient position (${existing_position_value:.2f})"
        
        # Step 5: Don't exceed available cash
        buy_value = min(additional_value, available_cash * 0.95)  # Leave 5% buffer
        
        if buy_value < tc.min_trade_amount:
            return 0.0, f"Insufficient cash after buffer: ${buy_value:.2f}"
        
        # Step 6: Calculate shares
        shares = buy_value / current_price
        shares = round(shares, 4)  # Trading212 supports fractional shares
        
        # Build explanation
        explanation = (
            f"Position sizing: {target_pct*100:.1f}% of portfolio "
            f"(conviction: {conviction_mult*100:.0f}%, politician traded ${politician_amount:,.0f}). "
            f"Buying ${buy_value:.2f} worth = {shares} shares"
        )
        
        return shares, explanation


# -----------------------------------------------------------------------------
# Trade Executor
# -----------------------------------------------------------------------------
class TradeExecutor:
    """Executes trades on Trading212 with full risk management."""
    
    def __init__(self):
        self.config = get_config()
        self.db = get_db()
        self.risk_guards = RiskGuards()
        self.sector_mapper = SectorMapper()
        self.symbol_mapper = SymbolMapper()
        self.position_sizer = PositionSizer()
        self._client: Optional[Trading212Client] = None
    
    @property
    def client(self) -> Optional[Trading212Client]:
        """Lazy-load Trading212 client."""
        if self._client is None:
            if not self.config.trading212.validate():
                trade_logger.error("Trading212 credentials not configured")
                return None
            
            self._client = Trading212Client(
                api_key=self.config.trading212.api_key,
                api_secret=self.config.trading212.api_secret,
                base_url=self.config.trading212.base_url
            )
            trade_logger.info(f"Trading212 client initialized ({self.config.trading212.environment} mode)")
        
        return self._client
    
    def get_account_equity(self) -> float:
        """Get current account total value from Trading212."""
        if not self.client:
            return 0.0
        
        try:
            summary = self.client.get_account_summary()
            if summary:
                return float(summary.get('totalValue', 0))
            return 0.0
        except Exception as e:
            trade_logger.error(f"Failed to get account equity: {e}")
            return 0.0
    
    def get_position(self, ticker: str) -> Optional[dict]:
        """Check if we have a position in a ticker."""
        if not self.client:
            return None
        
        try:
            # Convert to Trading212 ticker format
            t212_ticker = self.symbol_mapper.to_trading212(ticker)
            positions = self.client.get_positions(t212_ticker)
            
            if positions and len(positions) > 0:
                pos = positions[0]
                return {
                    'ticker': ticker,
                    't212_ticker': pos.get('instrument', {}).get('ticker', t212_ticker),
                    'qty': float(pos.get('quantity', 0)),
                    'avg_cost': float(pos.get('averagePricePaid', 0)),
                    'current_price': float(pos.get('currentPrice', 0)),
                    'unrealized_pnl': float(pos.get('walletImpact', {}).get('unrealizedProfitLoss', 0)),
                }
            return None
        except Exception as e:
            trade_logger.warning(f"Error getting position for {ticker}: {e}")
            return None
    
    def _get_current_price(self, ticker: str) -> Optional[float]:
        """Get current market price for a ticker."""
        try:
            stock = yf.Ticker(ticker)
            info = stock.info
            return info.get('regularMarketPrice', info.get('previousClose'))
        except Exception as e:
            trade_logger.warning(f"Could not get price for {ticker}: {e}")
            return None
    
    def execute_buy(self, signal: TradeSignal) -> TradeResult:
        """
        Execute a buy order with all risk checks.
        
        Flow:
        1. Run liquidity + wash sale checks
        2. Calculate position size
        3. Submit market order (positive quantity)
        4. Record in history
        """
        ticker = signal.ticker
        trade_logger.info(f"Processing BUY signal for {ticker}")
        
        # Run pre-trade checks
        can_buy, check_messages = self.risk_guards.run_buy_checks(ticker)
        
        for msg in check_messages:
            trade_logger.info(f"  {msg}")
        
        if not can_buy:
            return TradeResult(
                success=False,
                ticker=ticker,
                side='buy',
                rejected_reason="; ".join(check_messages),
                message="Buy rejected by risk guards"
            )
        
        if not self.client:
            return TradeResult(
                success=False,
                ticker=ticker,
                side='buy',
                rejected_reason="Trading212 client not available",
                message="Trading disabled"
            )
        
        # Get current price
        current_price = self._get_current_price(ticker)
        if not current_price:
            return TradeResult(
                success=False,
                ticker=ticker,
                side='buy',
                rejected_reason="Could not get current price",
                message="Price lookup failed"
            )
        
        # Get account info for position sizing
        account_summary = self.client.get_account_summary()
        if not account_summary:
            return TradeResult(
                success=False,
                ticker=ticker,
                side='buy',
                rejected_reason="Could not get account summary",
                message="Account lookup failed"
            )
        
        portfolio_value = float(account_summary.get('totalValue', 0))
        available_cash = float(account_summary.get('cash', {}).get('availableToTrade', 0))
        
        # Check existing position
        existing_position = self.get_position(ticker)
        existing_value = 0.0
        if existing_position:
            existing_value = existing_position['qty'] * existing_position['current_price']
        
        # Calculate position size using the position sizer algorithm
        shares, sizing_msg = self.position_sizer.calculate_position(
            portfolio_value=portfolio_value,
            available_cash=available_cash,
            politician_amount=signal.amount_midpoint,
            current_price=current_price,
            existing_position_value=existing_value
        )
        
        trade_logger.info(f"  {sizing_msg}")
        
        if shares <= 0:
            return TradeResult(
                success=False,
                ticker=ticker,
                side='buy',
                rejected_reason=sizing_msg,
                message="Position sizing rejected trade"
            )
        
        # Convert ticker to Trading212 format
        t212_ticker = self.symbol_mapper.to_trading212(ticker)
        
        trade_logger.info(f"Placing order: BUY {shares} shares of {t212_ticker} @ ~${current_price:.2f}")
        
        try:
            # Trading212 uses positive quantity for buy
            order = self.client.place_market_order(
                ticker=t212_ticker,
                quantity=shares,  # Positive for buy
                extended_hours=False
            )
            
            if not order:
                return TradeResult(
                    success=False,
                    ticker=ticker,
                    side='buy',
                    rejected_reason="Order rejected by Trading212",
                    message="Order submission failed"
                )
            
            order_id = str(order.get('id', ''))
            
            # Record in history
            history = TradeHistory(
                ticker=ticker,
                trade_type='buy',
                shares=shares,
                price=current_price,
                executed_at=datetime.utcnow().isoformat(),
                signal_id=signal.id,
            )
            self.db.insert_trade_history(history)
            
            # If this was a proxy trade (sector ETF), record the mapping
            if hasattr(signal, '_original_ticker') and signal._original_ticker:
                self.db.insert_proxy_trade(
                    original_ticker=signal._original_ticker,
                    proxy_ticker=ticker,
                    politician=signal.politician,
                    shares=shares,
                    signal_id=signal.id
                )
                trade_logger.info(f"Recorded proxy: {signal._original_ticker} -> {ticker}")
            
            trade_logger.info(f"Order submitted: {order_id}")
            
            return TradeResult(
                success=True,
                ticker=ticker,
                side='buy',
                shares=shares,
                price=current_price,
                order_id=order_id,
                message=f"BUY order submitted: {shares} shares @ ${current_price:.2f}"
            )
            
        except Exception as e:
            trade_logger.error(f"Order submission failed: {e}")
            return TradeResult(
                success=False,
                ticker=ticker,
                side='buy',
                rejected_reason=str(e),
                message="Order submission failed"
            )
    
    def execute_sell(self, signal: TradeSignal) -> TradeResult:
        """
        Execute a sell order.
        
        Flow:
        1. Check if we own the position
        2. Submit market order (NEGATIVE quantity for sell)
        3. Record in history with P&L
        """
        ticker = signal.ticker
        trade_logger.info(f"Processing SELL signal for {ticker}")
        
        if not self.client:
            return TradeResult(
                success=False,
                ticker=ticker,
                side='sell',
                rejected_reason="Trading212 client not available",
                message="Trading disabled"
            )
        
        # Check if we own this position
        position = self.get_position(ticker)
        if not position:
            trade_logger.info(f"No position in {ticker}, cancelling sell signal")
            # Mark signal as rejected since we can't sell what we don't own
            if hasattr(signal, 'id') and signal.id:
                self.db.set_signal_status(signal.id, 'rejected')
            return TradeResult(
                success=False,
                ticker=ticker,
                side='sell',
                rejected_reason="No position to sell - signal cancelled",
                message="Sell cancelled - no position owned"
            )
        
        # Determine shares to sell:
        # - If this is a proxy trade, use the proxy shares (but not more than actual position)
        # - Otherwise, sell the entire position
        actual_shares = position['qty']
        
        if hasattr(signal, '_proxy_shares') and signal._proxy_shares:
            # Proxy trade: sell the recorded amount, but not more than we actually own
            shares = min(signal._proxy_shares, actual_shares)
            if shares < signal._proxy_shares:
                trade_logger.warning(
                    f"Proxy says {signal._proxy_shares} shares but only {actual_shares} owned. "
                    f"Selling {shares} shares."
                )
        else:
            # Direct trade: sell entire position
            shares = actual_shares
        
        avg_cost = position['avg_cost']
        
        # Get current price for P&L calculation
        current_price = self._get_current_price(ticker)
        if not current_price:
            current_price = avg_cost  # Fallback
        
        pnl = (current_price - avg_cost) * shares
        
        # Convert ticker to Trading212 format
        t212_ticker = self.symbol_mapper.to_trading212(ticker)
        
        trade_logger.info(f"Placing order: SELL {shares} shares of {t212_ticker} @ ~${current_price:.2f} (P&L: ${pnl:.2f})")
        
        try:
            # Trading212 uses NEGATIVE quantity for sell
            order = self.client.place_market_order(
                ticker=t212_ticker,
                quantity=-shares,  # NEGATIVE for sell
                extended_hours=False
            )
            
            if not order:
                return TradeResult(
                    success=False,
                    ticker=ticker,
                    side='sell',
                    rejected_reason="Order rejected by Trading212",
                    message="Order submission failed"
                )
            
            order_id = str(order.get('id', ''))
            
            # Record in history with P&L
            history = TradeHistory(
                ticker=ticker,
                trade_type='sell',
                shares=shares,
                price=current_price,
                executed_at=datetime.utcnow().isoformat(),
                pnl=pnl,
                signal_id=signal.id,
            )
            self.db.insert_trade_history(history)
            
            trade_logger.info(f"Order submitted: {order_id}")
            
            return TradeResult(
                success=True,
                ticker=ticker,
                side='sell',
                shares=shares,
                price=current_price,
                order_id=order_id,
                message=f"SELL order submitted: {shares} shares @ ${current_price:.2f} (P&L: ${pnl:.2f})"
            )
            
        except Exception as e:
            trade_logger.error(f"Order submission failed: {e}")
            return TradeResult(
                success=False,
                ticker=ticker,
                side='sell',
                rejected_reason=str(e),
                message="Order submission failed"
            )
    
    def process_signal(self, signal: TradeSignal) -> TradeResult:
        """
        Process a trade signal based on type and latency strategy.
        
        Strategies for BUY:
        1. Fresh (lag <= 10 days): Auto-execute immediately
        2. Stale (11-45 days): Require confirmation before executing
        3. Very Stale (46-90 days): Require confirmation + sector rotation
        4. Expired (>90 days): Reject
        
        Strategies for SELL:
        1. Check if we have a proxy trade (ETF bought for this stock)
        2. If proxy exists, sell the proxy ETF
        3. Otherwise, try to sell the actual ticker
        """
        lag = signal.lag_days
        original_ticker = signal.ticker
        
        # For SELL signals, first check if we have a proxy trade to close
        if signal.trade_type == 'sale':
            # ALL signals (including sells) require confirmation
            if signal.status == 'pending':
                self.db.set_signal_status(signal.id, 'pending_confirmation')
                trade_logger.info(
                    f"SELL Signal PENDING CONFIRMATION: {original_ticker} lag {lag} days "
                    f"(all trades require manual approval)"
                )
                return TradeResult(
                    success=False,
                    ticker=original_ticker,
                    side='sell',
                    rejected_reason=f"Waiting for confirmation (lag: {lag} days)",
                    message="Signal pending user confirmation"
                )
            
            # If signal is not confirmed yet, skip it
            if signal.status == 'pending_confirmation':
                return TradeResult(
                    success=False,
                    ticker=original_ticker,
                    side='sell',
                    rejected_reason="Awaiting user confirmation",
                    message="Signal pending user confirmation"
                )
            
            # Now check proxy trades for confirmed sell signals
            proxy = self.db.get_open_proxy_trade(original_ticker, signal.politician)
            if proxy:
                trade_logger.info(
                    f"Proxy Sell: Found proxy trade {original_ticker} -> {proxy['proxy_ticker']} "
                    f"({proxy['shares']} shares)"
                )
                # Override signal to sell the proxy ETF
                signal.ticker = proxy['proxy_ticker']
                signal.signal_type = 'sector_etf'
                signal._proxy_id = proxy['id']  # Store for closing after sell
                signal._proxy_shares = proxy['shares']
            else:
                signal.signal_type = 'direct'
        
        # For BUY signals, apply signal age filtering and confirmation requirements
        elif signal.trade_type == 'purchase':
            stale_lag = self.config.trading.stale_signal_threshold  # 45 days
            max_lag = self.config.trading.max_signal_age  # 90 days
            
            # Reject signals that are too stale (expired)
            if lag > max_lag:
                trade_logger.info(
                    f"Signal EXPIRED: {original_ticker} lag {lag} days > {max_lag} days max"
                )
                return TradeResult(
                    success=False,
                    ticker=original_ticker,
                    side='buy',
                    rejected_reason=f"Signal too stale: {lag} days > {max_lag} max",
                    message="Signal expired - trade date too old"
                )
            
            # ALL signals require confirmation before execution
            if signal.status == 'pending':
                # Mark for confirmation - all trades need manual approval
                self.db.set_signal_status(signal.id, 'pending_confirmation')
                trade_logger.info(
                    f"Signal PENDING CONFIRMATION: {original_ticker} lag {lag} days "
                    f"(all trades require manual approval)"
                )
                return TradeResult(
                    success=False,
                    ticker=original_ticker,
                    side='buy',
                    rejected_reason=f"Waiting for confirmation (lag: {lag} days)",
                    message="Signal pending user confirmation"
                )
            
            # If signal is not confirmed yet, skip it
            if signal.status == 'pending_confirmation':
                return TradeResult(
                    success=False,
                    ticker=original_ticker,
                    side='buy',
                    rejected_reason="Awaiting user confirmation",
                    message="Signal pending user confirmation"
                )
            
            # Apply sector rotation for stale signals (between stale threshold and max)
            if lag > stale_lag:
                # Stale signal - use sector rotation
                etf = self.sector_mapper.get_sector_etf(original_ticker)
                trade_logger.info(
                    f"Sector Rotation: {original_ticker} -> {etf} "
                    f"(lag {lag} days > {stale_lag})"
                )
                signal._original_ticker = original_ticker  # Store for proxy tracking
                signal.ticker = etf
                signal.signal_type = 'sector_etf'
            else:
                signal.signal_type = 'direct'
                signal._original_ticker = None
        
        # Execute based on trade type
        if signal.trade_type == 'purchase':
            result = self.execute_buy(signal)
        elif signal.trade_type == 'sale':
            result = self.execute_sell(signal)
            # If sell was successful and this was a proxy trade, close it
            if result.success and hasattr(signal, '_proxy_id') and signal._proxy_id:
                self.db.close_proxy_trade(signal._proxy_id)
                trade_logger.info(f"Closed proxy trade ID {signal._proxy_id}")
        else:
            result = TradeResult(
                success=False,
                ticker=signal.ticker,
                side='unknown',
                rejected_reason=f"Unknown trade type: {signal.trade_type}",
                message="Invalid signal"
            )
        
        # Mark signal as processed
        if signal.id:
            self.db.mark_signal_processed(signal.id)
        
        return result
    
    def process_pending_signals(self) -> list[TradeResult]:
        """Process all pending trade signals (excluding those awaiting confirmation)."""
        signals = self.db.get_unprocessed_signals()
        trade_logger.info(f"Processing {len(signals)} pending signals")
        
        results = []
        for signal in signals:
            result = self.process_signal(signal)
            results.append(result)
            
            status = "✓" if result.success else "✗"
            trade_logger.info(f"{status} {result.ticker}: {result.message}")
        
        return results


# -----------------------------------------------------------------------------
# Module-level convenience functions
# -----------------------------------------------------------------------------
def check_liquidity(ticker: str) -> tuple[bool, str]:
    """Quick liquidity check for a ticker."""
    guards = RiskGuards()
    return guards.check_liquidity(ticker)


def get_sector_etf(ticker: str) -> str:
    """Get sector ETF for a ticker."""
    mapper = SectorMapper()
    return mapper.get_sector_etf(ticker)


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    
    # Test Trading212 connection
    print("Testing Trading212 connection...")
    
    executor = TradeExecutor()
    
    if executor.client:
        print(f"✓ Connected to Trading212 ({executor.config.trading212.environment})")
        
        equity = executor.get_account_equity()
        print(f"  Account equity: ${equity:,.2f}")
        
        # Test symbol mapping
        print("\nSymbol mapping test:")
        mapper = SymbolMapper()
        for ticker in ["AAPL", "MSFT", "BRK.B"]:
            t212 = mapper.to_trading212(ticker)
            print(f"  {ticker} -> {t212}")
    else:
        print("✗ Trading212 not configured - set TRADING212_API_KEY and TRADING212_API_SECRET")
