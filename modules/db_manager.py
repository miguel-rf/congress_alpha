"""
Congressional Alpha System - Database Manager

SQLite database management with schema for trades, history, and logging.
Provides CRUD operations for trade signals and execution history.
"""
from __future__ import annotations

import sqlite3
import logging
from datetime import datetime, timedelta
from pathlib import Path
from contextlib import contextmanager
from dataclasses import dataclass, asdict
from typing import Optional, Iterator

# Use relative import from config
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from config.settings import DATABASE_PATH, logger

# Module logger
db_logger = logging.getLogger("congress_alpha.db")


# -----------------------------------------------------------------------------
# Data Models
# -----------------------------------------------------------------------------
@dataclass
class TradeSignal:
    """Represents a parsed trade disclosure signal."""
    ticker: str
    politician: str
    trade_type: str  # 'purchase' or 'sale'
    amount_midpoint: float
    trade_date: str  # YYYY-MM-DD
    disclosure_date: str  # YYYY-MM-DD
    lag_days: int
    signal_type: str  # 'direct' or 'sector_etf'
    chamber: str  # 'house' or 'senate'
    asset_name: Optional[str] = None
    pdf_url: Optional[str] = None
    id: Optional[int] = None
    created_at: Optional[str] = None
    processed: bool = False
    # Additional fields for options trades (not stored in DB, for display only)
    is_options: bool = False
    owner: Optional[str] = None  # Self, Spouse, Joint, etc.


@dataclass
class TradeHistory:
    """Represents an executed trade for wash sale/PDT tracking."""
    ticker: str
    trade_type: str  # 'buy' or 'sell'
    shares: float
    price: float
    executed_at: str  # ISO timestamp
    pnl: Optional[float] = None  # Profit/Loss for sells
    signal_id: Optional[int] = None
    id: Optional[int] = None


@dataclass
class LogEntry:
    """Represents a system log entry."""
    level: str
    module: str
    message: str
    created_at: Optional[str] = None
    id: Optional[int] = None


# -----------------------------------------------------------------------------
# Database Schema
# -----------------------------------------------------------------------------
SCHEMA_SQL = """
-- Trade signals from disclosure parsing
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    politician TEXT NOT NULL,
    trade_type TEXT NOT NULL CHECK(trade_type IN ('purchase', 'sale')),
    amount_midpoint REAL NOT NULL,
    trade_date TEXT NOT NULL,
    disclosure_date TEXT NOT NULL,
    lag_days INTEGER NOT NULL,
    signal_type TEXT NOT NULL CHECK(signal_type IN ('direct', 'sector_etf')),
    chamber TEXT NOT NULL CHECK(chamber IN ('house', 'senate')),
    asset_name TEXT,
    pdf_url TEXT,
    processed INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(ticker, politician, trade_date, trade_type)
);

-- Executed trade history for wash sale and PDT checks
CREATE TABLE IF NOT EXISTS trade_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    trade_type TEXT NOT NULL CHECK(trade_type IN ('buy', 'sell')),
    shares REAL NOT NULL,
    price REAL NOT NULL,
    executed_at TEXT NOT NULL,
    pnl REAL,
    signal_id INTEGER,
    FOREIGN KEY (signal_id) REFERENCES trades(id)
);

-- Proxy trades: tracks when we buy an ETF as a proxy for a stale stock signal
-- Used to correctly sell the ETF when the politician later sells the original stock
CREATE TABLE IF NOT EXISTS proxy_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    original_ticker TEXT NOT NULL,
    proxy_ticker TEXT NOT NULL,
    politician TEXT NOT NULL,
    shares REAL NOT NULL,
    buy_signal_id INTEGER,
    created_at TEXT DEFAULT (datetime('now')),
    closed INTEGER DEFAULT 0,
    closed_at TEXT,
    FOREIGN KEY (buy_signal_id) REFERENCES trades(id)
);

-- System logs
CREATE TABLE IF NOT EXISTS logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    level TEXT NOT NULL,
    module TEXT NOT NULL,
    message TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_trades_ticker ON trades(ticker);
CREATE INDEX IF NOT EXISTS idx_trades_politician ON trades(politician);
CREATE INDEX IF NOT EXISTS idx_trades_processed ON trades(processed);
CREATE INDEX IF NOT EXISTS idx_trades_created ON trades(created_at);

CREATE INDEX IF NOT EXISTS idx_history_ticker ON trade_history(ticker);
CREATE INDEX IF NOT EXISTS idx_history_executed ON trade_history(executed_at);
CREATE INDEX IF NOT EXISTS idx_history_type ON trade_history(trade_type);

CREATE INDEX IF NOT EXISTS idx_logs_level ON logs(level);
CREATE INDEX IF NOT EXISTS idx_logs_created ON logs(created_at);

CREATE INDEX IF NOT EXISTS idx_proxy_original ON proxy_trades(original_ticker, politician);
CREATE INDEX IF NOT EXISTS idx_proxy_closed ON proxy_trades(closed);
"""


# -----------------------------------------------------------------------------
# Database Connection Management
# -----------------------------------------------------------------------------
class DatabaseManager:
    """Thread-safe SQLite database manager."""
    
    def __init__(self, db_path: Path = DATABASE_PATH):
        self.db_path = db_path
        self._ensure_db_exists()
    
    def _ensure_db_exists(self) -> None:
        """Create database and schema if not exists."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self.get_connection() as conn:
            conn.executescript(SCHEMA_SQL)
            db_logger.info(f"Database initialized at {self.db_path}")
    
    @contextmanager
    def get_connection(self) -> Iterator[sqlite3.Connection]:
        """Context manager for database connections."""
        conn = sqlite3.connect(
            self.db_path,
            detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES
        )
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            db_logger.error(f"Database error: {e}")
            raise
        finally:
            conn.close()
    
    # -------------------------------------------------------------------------
    # Trade Signal Operations
    # -------------------------------------------------------------------------
    def insert_trade_signal(self, signal: TradeSignal) -> int:
        """Insert a new trade signal, returns the id."""
        with self.get_connection() as conn:
            cursor = conn.execute("""
                INSERT OR IGNORE INTO trades 
                (ticker, politician, trade_type, amount_midpoint, trade_date,
                 disclosure_date, lag_days, signal_type, chamber, asset_name, pdf_url)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                signal.ticker, signal.politician, signal.trade_type,
                signal.amount_midpoint, signal.trade_date, signal.disclosure_date,
                signal.lag_days, signal.signal_type, signal.chamber,
                signal.asset_name, signal.pdf_url
            ))
            return cursor.lastrowid
    
    def get_unprocessed_signals(self) -> list[TradeSignal]:
        """Get all unprocessed trade signals."""
        with self.get_connection() as conn:
            cursor = conn.execute("""
                SELECT * FROM trades WHERE processed = 0
                ORDER BY created_at ASC
            """)
            rows = cursor.fetchall()
            return [TradeSignal(**dict(row)) for row in rows]
    
    def mark_signal_processed(self, signal_id: int) -> None:
        """Mark a signal as processed."""
        with self.get_connection() as conn:
            conn.execute(
                "UPDATE trades SET processed = 1 WHERE id = ?",
                (signal_id,)
            )
    
    def signal_exists(self, ticker: str, politician: str, 
                      trade_date: str, trade_type: str) -> bool:
        """Check if a signal already exists (deduplication)."""
        with self.get_connection() as conn:
            cursor = conn.execute("""
                SELECT 1 FROM trades 
                WHERE ticker = ? AND politician = ? 
                AND trade_date = ? AND trade_type = ?
            """, (ticker, politician, trade_date, trade_type))
            return cursor.fetchone() is not None
    
    # -------------------------------------------------------------------------
    # Trade History Operations (for Wash Sale / PDT checks)
    # -------------------------------------------------------------------------
    def insert_trade_history(self, history: TradeHistory) -> int:
        """Record an executed trade."""
        with self.get_connection() as conn:
            cursor = conn.execute("""
                INSERT INTO trade_history
                (ticker, trade_type, shares, price, executed_at, pnl, signal_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                history.ticker, history.trade_type, history.shares,
                history.price, history.executed_at, history.pnl, history.signal_id
            ))
            return cursor.lastrowid
    
    def check_wash_sale(self, ticker: str, lookback_days: int = 30) -> bool:
        """
        Check if we sold this ticker at a loss in the lookback period.
        Returns True if wash sale rule applies (should NOT buy).
        """
        cutoff = (datetime.utcnow() - timedelta(days=lookback_days)).isoformat()
        with self.get_connection() as conn:
            cursor = conn.execute("""
                SELECT 1 FROM trade_history
                WHERE ticker = ? 
                AND trade_type = 'sell'
                AND pnl < 0
                AND executed_at >= ?
            """, (ticker, cutoff))
            return cursor.fetchone() is not None
    
    def check_pdt_holding(self, ticker: str, holding_days: int = 5) -> bool:
        """
        Check if we bought this ticker within the holding period.
        Returns True if PDT rule might apply (bought recently).
        """
        cutoff = (datetime.utcnow() - timedelta(days=holding_days)).isoformat()
        with self.get_connection() as conn:
            cursor = conn.execute("""
                SELECT 1 FROM trade_history
                WHERE ticker = ?
                AND trade_type = 'buy'
                AND executed_at >= ?
            """, (ticker, cutoff))
            return cursor.fetchone() is not None
    
    def get_position_history(self, ticker: str) -> list[TradeHistory]:
        """Get all trade history for a ticker."""
        with self.get_connection() as conn:
            cursor = conn.execute("""
                SELECT * FROM trade_history
                WHERE ticker = ?
                ORDER BY executed_at DESC
            """, (ticker,))
            rows = cursor.fetchall()
            return [TradeHistory(**dict(row)) for row in rows]
    
    # -------------------------------------------------------------------------
    # Proxy Trade Operations (for ETF sector rotation tracking)
    # -------------------------------------------------------------------------
    def insert_proxy_trade(self, original_ticker: str, proxy_ticker: str,
                           politician: str, shares: float, 
                           signal_id: Optional[int] = None) -> int:
        """
        Record that we bought a proxy ETF for a stale stock signal.
        
        Args:
            original_ticker: The stock the politician traded (e.g., AAPL)
            proxy_ticker: The ETF we actually bought (e.g., XLK)
            politician: Name of the politician
            shares: Number of ETF shares purchased
            signal_id: The buy signal that triggered this
        
        Returns:
            The proxy trade ID
        """
        with self.get_connection() as conn:
            cursor = conn.execute("""
                INSERT INTO proxy_trades 
                (original_ticker, proxy_ticker, politician, shares, buy_signal_id)
                VALUES (?, ?, ?, ?, ?)
            """, (original_ticker, proxy_ticker, politician, shares, signal_id))
            db_logger.info(f"Recorded proxy trade: {original_ticker} -> {proxy_ticker} ({shares} shares)")
            return cursor.lastrowid
    
    def get_open_proxy_trade(self, original_ticker: str, 
                              politician: str) -> Optional[dict]:
        """
        Find an open proxy trade for a ticker/politician combination.
        
        Used when a sell signal comes in to find what ETF we should sell.
        
        Returns:
            Dict with proxy_ticker, shares, id if found, else None
        """
        with self.get_connection() as conn:
            cursor = conn.execute("""
                SELECT id, proxy_ticker, shares, created_at
                FROM proxy_trades
                WHERE original_ticker = ? 
                AND politician = ?
                AND closed = 0
                ORDER BY created_at DESC
                LIMIT 1
            """, (original_ticker, politician))
            row = cursor.fetchone()
            if row:
                return {
                    'id': row['id'],
                    'proxy_ticker': row['proxy_ticker'],
                    'shares': row['shares'],
                    'created_at': row['created_at']
                }
            return None
    
    def close_proxy_trade(self, proxy_id: int) -> None:
        """Mark a proxy trade as closed (sold)."""
        with self.get_connection() as conn:
            conn.execute("""
                UPDATE proxy_trades 
                SET closed = 1, closed_at = datetime('now')
                WHERE id = ?
            """, (proxy_id,))
            db_logger.info(f"Closed proxy trade ID {proxy_id}")
    
    def get_all_open_proxy_trades(self) -> list[dict]:
        """Get all open proxy trades for portfolio view."""
        with self.get_connection() as conn:
            cursor = conn.execute("""
                SELECT id, original_ticker, proxy_ticker, politician, shares, created_at
                FROM proxy_trades
                WHERE closed = 0
                ORDER BY created_at DESC
            """)
            return [dict(row) for row in cursor.fetchall()]
    
    # -------------------------------------------------------------------------
    # Logging Operations
    # -------------------------------------------------------------------------
    def log_event(self, level: str, module: str, message: str) -> None:
        """Insert a log entry."""
        with self.get_connection() as conn:
            conn.execute("""
                INSERT INTO logs (level, module, message)
                VALUES (?, ?, ?)
            """, (level, module, message))
    
    def get_recent_logs(self, limit: int = 100, 
                        level: Optional[str] = None) -> list[LogEntry]:
        """Get recent log entries."""
        with self.get_connection() as conn:
            if level:
                cursor = conn.execute("""
                    SELECT * FROM logs WHERE level = ?
                    ORDER BY created_at DESC LIMIT ?
                """, (level, limit))
            else:
                cursor = conn.execute("""
                    SELECT * FROM logs
                    ORDER BY created_at DESC LIMIT ?
                """, (limit,))
            rows = cursor.fetchall()
            return [LogEntry(**dict(row)) for row in rows]
    
    # -------------------------------------------------------------------------
    # Utility Methods
    # -------------------------------------------------------------------------
    def get_stats(self) -> dict:
        """Get database statistics."""
        with self.get_connection() as conn:
            stats = {}
            
            cursor = conn.execute("SELECT COUNT(*) FROM trades")
            stats["total_signals"] = cursor.fetchone()[0]
            
            cursor = conn.execute("SELECT COUNT(*) FROM trades WHERE processed = 0")
            stats["pending_signals"] = cursor.fetchone()[0]
            
            cursor = conn.execute("SELECT COUNT(*) FROM trade_history")
            stats["total_trades"] = cursor.fetchone()[0]
            
            cursor = conn.execute("""
                SELECT COUNT(*) FROM trade_history WHERE trade_type = 'buy'
            """)
            stats["total_buys"] = cursor.fetchone()[0]
            
            cursor = conn.execute("""
                SELECT COUNT(*) FROM trade_history WHERE trade_type = 'sell'
            """)
            stats["total_sells"] = cursor.fetchone()[0]
            
            return stats


# -----------------------------------------------------------------------------
# Module-level convenience functions
# -----------------------------------------------------------------------------
_db: Optional[DatabaseManager] = None


def get_db() -> DatabaseManager:
    """Get or create the global database manager instance."""
    global _db
    if _db is None:
        _db = DatabaseManager()
    return _db


def init_db() -> DatabaseManager:
    """Initialize and return the database manager."""
    return get_db()


if __name__ == "__main__":
    # Quick test when run directly
    db = init_db()
    print(f"Database initialized at: {DATABASE_PATH}")
    print(f"Stats: {db.get_stats()}")
