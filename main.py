#!/usr/bin/env python3
"""
Congressional Alpha System - Main Scheduler

Orchestrates the copy-trading pipeline with adaptive scheduling:
- Market Hours (09:00-18:00 ET): Every 10-15 minutes (randomized)
- Off Hours: Every 4 hours
- Anti-bot protection with randomized delays
"""
from __future__ import annotations

import json
import time
import random
import logging
import signal as sig
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

# Local imports
import sys
sys.path.insert(0, str(Path(__file__).parent))

from config.settings import get_config, CONFIG_DIR, logger
from modules.db_manager import init_db, get_db, TradeSignal
from modules.scraper_house import HouseScraper
from modules.scraper_senate import SenateScraper
from modules.ocr_engine import process_all_pending_pdfs, ExtractedTransaction
from modules.trade_executor import TradeExecutor, TradeResult

# Try to import Playwright scraper as fallback
try:
    from modules.scraper_senate_playwright import SenatePlaywrightScraper
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

# Module logger
main_logger = logging.getLogger("congress_alpha.main")

# Timezone for market hours
ET = ZoneInfo("America/New_York")


# -----------------------------------------------------------------------------
# Whitelist Management
# -----------------------------------------------------------------------------
class WhitelistManager:
    """Manages the list of politicians to track."""
    
    def __init__(self, whitelist_path: Path = CONFIG_DIR / "whitelist.json"):
        self.whitelist_path = whitelist_path
        self._politicians: list[str] = []
        self._load_whitelist()
    
    def _load_whitelist(self) -> None:
        """Load whitelist from JSON."""
        if not self.whitelist_path.exists():
            main_logger.warning(f"Whitelist not found: {self.whitelist_path}")
            return
        
        try:
            with open(self.whitelist_path, 'r') as f:
                data = json.load(f)
            
            self._politicians = [
                p.get('name', '') for p in data.get('politicians', [])
                if p.get('name')
            ]
            
            main_logger.info(f"Loaded {len(self._politicians)} politicians from whitelist")
            
        except (json.JSONDecodeError, KeyError) as e:
            main_logger.error(f"Error loading whitelist: {e}")
    
    @property
    def politicians(self) -> list[str]:
        """Get list of whitelisted politician names."""
        return self._politicians
    
    def is_whitelisted(self, name: str) -> bool:
        """Check if a politician is on the whitelist."""
        name_lower = name.lower()
        return any(p.lower() == name_lower for p in self._politicians)


# -----------------------------------------------------------------------------
# Adaptive Scheduler
# -----------------------------------------------------------------------------
class AdaptiveScheduler:
    """
    Adaptive scheduling based on market hours.
    
    - Market Hours (09:00-18:00 ET): 10-15 minute intervals
    - Off Hours: 4 hour intervals
    - Random jitter to avoid pattern detection
    """
    
    def __init__(self):
        self.config = get_config()
    
    def is_market_hours(self) -> bool:
        """Check if current time is within market hours (ET)."""
        now_et = datetime.now(ET)
        hour = now_et.hour
        weekday = now_et.weekday()  # 0 = Monday, 6 = Sunday
        
        # Weekend check
        if weekday >= 5:
            return False
        
        # Market hours check
        open_hour = self.config.scheduler.market_open_hour
        close_hour = self.config.scheduler.market_close_hour
        
        return open_hour <= hour < close_hour
    
    def get_next_interval(self) -> int:
        """
        Calculate the next sleep interval in seconds.
        
        Returns randomized interval based on market hours.
        """
        if self.is_market_hours():
            # Market hours: 10-15 minutes
            min_mins = self.config.scheduler.market_hours_min_interval
            max_mins = self.config.scheduler.market_hours_max_interval
            interval = random.randint(min_mins, max_mins) * 60
        else:
            # Off hours: 4 hours
            interval = self.config.scheduler.off_hours_interval * 60
        
        # Add jitter
        jitter_min = self.config.scheduler.jitter_min
        jitter_max = self.config.scheduler.jitter_max
        jitter = random.randint(jitter_min, jitter_max)
        
        return interval + jitter
    
    def get_status_string(self) -> str:
        """Get human-readable scheduler status."""
        now_et = datetime.now(ET)
        is_market = self.is_market_hours()
        
        return (
            f"Time: {now_et.strftime('%Y-%m-%d %H:%M:%S %Z')} | "
            f"Market Hours: {'Yes' if is_market else 'No'}"
        )


# -----------------------------------------------------------------------------
# Main Pipeline
# -----------------------------------------------------------------------------
class CongressAlphaPipeline:
    """Main orchestrator for the copy-trading pipeline."""
    
    def __init__(self):
        self.config = get_config()
        self.db = init_db()
        self.whitelist = WhitelistManager()
        self.scheduler = AdaptiveScheduler()
        self.house_scraper = HouseScraper()
        self.senate_scraper = SenateScraper()
        self.trade_executor = TradeExecutor()
        
        self._running = True
        self._setup_signal_handlers()
    
    def _setup_signal_handlers(self) -> None:
        """Setup graceful shutdown handlers."""
        sig.signal(sig.SIGINT, self._handle_shutdown)
        sig.signal(sig.SIGTERM, self._handle_shutdown)
    
    def _handle_shutdown(self, signum, frame) -> None:
        """Handle shutdown signals gracefully."""
        main_logger.info("Shutdown signal received, stopping...")
        self._running = False
    
    def run_scrape_cycle(self) -> dict:
        """
        Run a complete scrape cycle.
        
        Returns dict with scrape statistics.
        """
        stats = {
            'house_filings': 0,
            'senate_filings': 0,
            'pdfs_processed': 0,
            'transactions_extracted': 0,
        }
        
        whitelist_names = self.whitelist.politicians
        if not whitelist_names:
            main_logger.warning("No politicians in whitelist, skipping scrape")
            return stats
        
        # --- House Scraping ---
        main_logger.info("=== House Scraper ===")
        try:
            house_filings = self.house_scraper.scrape()
            stats['house_filings'] = len(house_filings)
            
            # Process with filtering and PDF downloads
            whitelisted_count, pdf_count = self.house_scraper.scrape_and_process(whitelist_names)
            main_logger.info(
                f"House: {len(house_filings)} total, "
                f"{whitelisted_count} whitelisted, {pdf_count} PDFs downloaded"
            )
            
        except Exception as e:
            main_logger.error(f"House scraper error: {e}")
        
        # --- Senate Scraping ---
        main_logger.info("=== Senate Scraper ===")
        try:
            senate_filings = self.senate_scraper.scrape()
            stats['senate_filings'] = len(senate_filings)
            
            # Process with format forking
            html_count, pdf_count = self.senate_scraper.scrape_and_process(whitelist_names)
            main_logger.info(
                f"Senate: {len(senate_filings)} total, "
                f"{html_count} HTML parsed, {pdf_count} PDFs downloaded"
            )
            
        except Exception as e:
            main_logger.error(f"Senate cookie scraper error: {e}")
            
            # Fallback to Playwright-based scraper
            if PLAYWRIGHT_AVAILABLE:
                main_logger.info("Trying Playwright-based Senate scraper...")
                try:
                    pw_scraper = SenatePlaywrightScraper(headless=True)
                    html_count, pdf_count = pw_scraper.scrape_and_process(whitelist_names)
                    main_logger.info(
                        f"Senate (Playwright): {html_count} HTML parsed, {pdf_count} PDFs"
                    )
                except Exception as pw_err:
                    main_logger.error(f"Senate Playwright scraper error: {pw_err}")
            else:
                main_logger.warning(
                    "Playwright not available. Install with: "
                    "pip install playwright && playwright install chromium"
                )
        
        # --- OCR Processing ---
        main_logger.info("=== OCR Processing ===")
        try:
            pdf_results = process_all_pending_pdfs()
            stats['pdfs_processed'] = len(pdf_results)
            
            for pdf_path, transactions in pdf_results:
                stats['transactions_extracted'] += len(transactions)
                main_logger.info(
                    f"PDF {pdf_path.name}: {len(transactions)} transactions"
                )
                
                # Extract politician name from PDF filename
                # Format: house_PoliticianName_timestamp.pdf or senate_PoliticianName_timestamp.pdf
                filename = pdf_path.stem  # Remove .pdf
                parts = filename.split('_')
                
                # Determine chamber and politician from filename
                chamber = 'house' if parts[0] == 'house' else 'senate'
                # Reconstruct politician name from middle parts (skip first and last 2)
                politician_parts = parts[1:-2] if len(parts) > 3 else parts[1:-1]
                politician = ' '.join(politician_parts).replace('_', ' ').title()
                
                # Get today for disclosure date (approximate)
                from datetime import datetime
                today = datetime.now().strftime("%Y-%m-%d")
                
                # Convert each ExtractedTransaction to TradeSignal and store
                for tx in transactions:
                    if not tx.ticker or not tx.trade_type:
                        continue
                    
                    # Calculate lag days
                    lag_days = 0
                    if tx.trade_date:
                        try:
                            trade_dt = datetime.strptime(tx.trade_date, "%Y-%m-%d")
                            lag_days = (datetime.now() - trade_dt).days
                        except ValueError:
                            lag_days = 30  # Default if parsing fails
                    
                    # Determine signal type based on lag
                    signal_type = 'direct' if lag_days <= self.config.trading.stale_signal_threshold else 'sector_etf'
                    
                    signal = TradeSignal(
                        ticker=tx.ticker,
                        politician=politician,
                        trade_type=tx.trade_type,  # 'purchase' or 'sale'
                        amount_midpoint=tx.amount_midpoint or 10000.0,
                        trade_date=tx.trade_date or today,
                        disclosure_date=today,
                        lag_days=lag_days,
                        signal_type=signal_type,
                        chamber=chamber,
                        asset_name=tx.asset_name,
                        pdf_url=str(pdf_path),
                    )
                    
                    # Check if signal already exists (deduplication)
                    if not self.db.signal_exists(
                        signal.ticker, signal.politician, 
                        signal.trade_date, signal.trade_type
                    ):
                        signal_id = self.db.insert_trade_signal(signal)
                        main_logger.info(
                            f"  → Created signal: {signal.trade_type.upper()} "
                            f"{signal.ticker} by {signal.politician} (ID: {signal_id})"
                        )
                    else:
                        main_logger.debug(f"  → Duplicate signal skipped: {tx.ticker}")
                
        except Exception as e:
            main_logger.error(f"OCR processing error: {e}")
        
        return stats
    
    def run_trade_cycle(self) -> list[TradeResult]:
        """
        Process pending trade signals.
        
        Returns list of trade results.
        """
        main_logger.info("=== Trade Execution ===")
        
        try:
            results = self.trade_executor.process_pending_signals()
            
            successful = sum(1 for r in results if r.success)
            rejected = sum(1 for r in results if not r.success)
            
            main_logger.info(
                f"Trade cycle complete: {successful} executed, {rejected} rejected"
            )
            
            return results
            
        except Exception as e:
            main_logger.error(f"Trade execution error: {e}")
            return []
    
    def run_cycle(self) -> None:
        """Run a complete pipeline cycle."""
        cycle_start = datetime.now()
        main_logger.info("=" * 60)
        main_logger.info(f"Starting cycle | {self.scheduler.get_status_string()}")
        main_logger.info("=" * 60)
        
        # Scrape
        scrape_stats = self.run_scrape_cycle()
        
        # Random delay between scrape and trade
        delay = random.randint(5, 30)
        main_logger.debug(f"Waiting {delay}s before trade execution...")
        time.sleep(delay)
        
        # Execute trades
        trade_results = self.run_trade_cycle()
        
        # Log cycle summary
        cycle_duration = (datetime.now() - cycle_start).total_seconds()
        self.db.log_event(
            "INFO",
            "main",
            f"Cycle complete in {cycle_duration:.1f}s: "
            f"H:{scrape_stats['house_filings']} S:{scrape_stats['senate_filings']} "
            f"T:{len(trade_results)}"
        )
        
        main_logger.info(f"Cycle complete in {cycle_duration:.1f}s")
    
    def run_forever(self) -> None:
        """Main loop with adaptive scheduling."""
        main_logger.info("=" * 60)
        main_logger.info("Congressional Alpha System Starting")
        main_logger.info("=" * 60)
        
        # Validate configuration
        validation = self.config.validate_all()
        for service, valid in validation.items():
            status = "✓" if valid else "✗"
            main_logger.info(f"  {status} {service.capitalize()} configured")
        
        main_logger.info(f"Tracking {len(self.whitelist.politicians)} politicians")
        main_logger.info("=" * 60)
        
        while self._running:
            try:
                # Run cycle
                self.run_cycle()
                
                # Calculate next interval
                interval = self.scheduler.get_next_interval()
                next_run = datetime.now() + timedelta(seconds=interval)
                
                main_logger.info(
                    f"Next cycle at {next_run.strftime('%H:%M:%S')} "
                    f"(in {interval // 60}m {interval % 60}s)"
                )
                
                # Sleep with periodic checks for shutdown
                sleep_remaining = interval
                while sleep_remaining > 0 and self._running:
                    sleep_chunk = min(60, sleep_remaining)
                    time.sleep(sleep_chunk)
                    sleep_remaining -= sleep_chunk
                
            except KeyboardInterrupt:
                main_logger.info("Keyboard interrupt received")
                self._running = False
            except Exception as e:
                main_logger.error(f"Cycle error: {e}")
                # Back off on errors
                time.sleep(300)
        
        main_logger.info("Congressional Alpha System stopped")
    
    def run_once(self) -> None:
        """Run a single cycle (for testing/cron)."""
        self.run_cycle()


# -----------------------------------------------------------------------------
# Entry Point
# -----------------------------------------------------------------------------
def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Congressional Alpha Copy-Trading System"
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single cycle and exit (for cron jobs)"
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging"
    )
    args = parser.parse_args()
    
    # Configure logging
    log_level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="[%(asctime)s] %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    
    # Run pipeline
    pipeline = CongressAlphaPipeline()
    
    if args.once:
        pipeline.run_once()
    else:
        pipeline.run_forever()


if __name__ == "__main__":
    main()
