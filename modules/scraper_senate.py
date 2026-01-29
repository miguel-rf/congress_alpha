"""
Congressional Alpha System - Senate Scraper with Playwright

Alternative scraper that uses Playwright to automatically handle
the Senate agreement checkbox, eliminating the need for manual cookies.
"""
from __future__ import annotations

import json
import re
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

# Local imports
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from config.settings import get_config, CONFIG_DIR, RAW_PDFS_DIR
from modules.db_manager import get_db, TradeSignal

# Module logger
scraper_logger = logging.getLogger("congress_alpha.scraper_senate_playwright")

# Check for Playwright
try:
    from playwright.sync_api import sync_playwright, Page, Browser
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    scraper_logger.warning("Playwright not available. Install with: pip install playwright && playwright install chromium")

# -----------------------------------------------------------------------------
# Constants
# -----------------------------------------------------------------------------
BASE_URL = "https://efdsearch.senate.gov"
SEARCH_URL = f"{BASE_URL}/search/"

# Amount parsing
AMOUNT_RANGES = {
    "$1,001 - $15,000": 8000.5,
    "$15,001 - $50,000": 32500.5,
    "$50,001 - $100,000": 75000.5,
    "$100,001 - $250,000": 175000.5,
    "$250,001 - $500,000": 375000.5,
    "$500,001 - $1,000,000": 750000.5,
    "$1,000,001 - $5,000,000": 3000000.5,
    "$5,000,001 - $25,000,000": 15000000.5,
    "$25,000,001 - $50,000,000": 37500000.5,
    "Over $50,000,000": 75000000.0,
}


def parse_amount(amount_str: str) -> float:
    """Convert amount range string to midpoint value."""
    amount_str = amount_str.strip()
    if amount_str in AMOUNT_RANGES:
        return AMOUNT_RANGES[amount_str]
    
    match = re.match(r'\$?([\d,]+)\s*[-–]\s*\$?([\d,]+)', amount_str)
    if match:
        low = float(match.group(1).replace(',', ''))
        high = float(match.group(2).replace(',', ''))
        return (low + high) / 2
    
    match = re.match(r'\$?([\d,]+)', amount_str)
    if match:
        return float(match.group(1).replace(',', ''))
    
    return 0.0


def parse_date(date_str: str) -> Optional[str]:
    """Parse various date formats to YYYY-MM-DD."""
    date_str = date_str.strip()
    formats = ["%m/%d/%Y", "%Y-%m-%d", "%m-%d-%Y", "%B %d, %Y", "%b %d, %Y"]
    
    for fmt in formats:
        try:
            dt = datetime.strptime(date_str, fmt)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


# -----------------------------------------------------------------------------
# Playwright-based Senate Scraper
# -----------------------------------------------------------------------------
class SenatePlaywrightScraper:
    """
    Senate scraper using Playwright for automatic authentication.
    
    Automatically clicks the agreement checkbox, no manual cookies needed.
    """
    
    def __init__(self, headless: bool = True):
        if not PLAYWRIGHT_AVAILABLE:
            raise RuntimeError(
                "Playwright not installed. Run:\n"
                "  pip install playwright\n"
                "  playwright install chromium"
            )
        
        self.config = get_config()
        self.db = get_db()
        self.headless = headless
        self._browser: Optional[Browser] = None
        self._page: Optional[Page] = None
    
    def _start_browser(self) -> None:
        """Start Playwright browser."""
        if self._browser:
            return
        
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=self.headless)
        self._page = self._browser.new_page()
        
        # Set realistic viewport and user agent
        self._page.set_viewport_size({"width": 1280, "height": 800})
        scraper_logger.info("Started Playwright browser")
    
    def _stop_browser(self) -> None:
        """Stop Playwright browser."""
        if self._browser:
            self._browser.close()
            self._playwright.stop()
            self._browser = None
            self._page = None
            scraper_logger.info("Stopped Playwright browser")
    
    def _accept_agreement(self) -> bool:
        """Navigate to search page and accept the agreement checkbox."""
        try:
            self._page.goto(SEARCH_URL, wait_until="networkidle", timeout=30000)
            
            # Check if we need to accept an agreement (look for the checkbox)
            agree_checkbox = self._page.locator('input#agree_statement')
            if agree_checkbox.count() > 0:
                scraper_logger.info("Agreement checkbox detected, clicking...")
                agree_checkbox.click()
                self._page.wait_for_timeout(500)
                
                # Click submit/continue button
                submit_btn = self._page.locator('button[type="submit"], input[type="submit"]').first
                if submit_btn.count() > 0:
                    submit_btn.click()
                    self._page.wait_for_load_state("networkidle")
                
                scraper_logger.info("Agreement accepted")
            
            # Verify we're on the search page
            if "/search" in self._page.url:
                scraper_logger.info("Successfully authenticated to Senate search")
                return True
            
            scraper_logger.warning(f"Unexpected page after agreement: {self._page.url}")
            return False
            
        except Exception as e:
            scraper_logger.error(f"Error accepting agreement: {e}")
            return False
    
    def _search_filings(self, report_type: str = "11") -> list[dict]:
        """
        Search for PTR filings.
        
        Args:
            report_type: "11" for Periodic Transaction Reports
        
        Returns:
            List of filing dictionaries
        """
        results = []
        
        try:
            # Wait for page to be fully loaded
            self._page.wait_for_load_state("networkidle", timeout=30000)
            self._page.wait_for_timeout(2000)  # Extra wait for dynamic content
            
            # The Senate site uses checkboxes for report types
            # Find all report type checkboxes and click the PTR one (value="11")
            scraper_logger.debug("Looking for PTR checkbox...")
            
            # Try to find and click PTR checkbox by value
            ptr_checkbox = self._page.locator(f'input[name="report_type"][value="{report_type}"]')
            if ptr_checkbox.count() > 0:
                if not ptr_checkbox.is_checked():
                    ptr_checkbox.click()
                    scraper_logger.debug("Clicked PTR checkbox by value")
            else:
                # Try by label text
                ptr_label = self._page.locator('label:has-text("Periodic Transaction Report")')
                if ptr_label.count() > 0:
                    ptr_label.click()
                    scraper_logger.debug("Clicked PTR label")
                else:
                    # Try all reportTypes checkboxes and click first one
                    all_checkboxes = self._page.locator('input#reportTypes, input[name="report_type"]').all()
                    for i, cb in enumerate(all_checkboxes):
                        try:
                            val = cb.get_attribute('value')
                            if val == report_type:
                                cb.click()
                                scraper_logger.debug(f"Clicked checkbox with value {val}")
                                break
                        except:
                            pass
            
            self._page.wait_for_timeout(1000)
            
            # Click search button - be specific to avoid hidden buttons
            # The visible search button has class btn-primary and text "Search Reports"
            search_btn = self._page.locator('button.btn-primary:has-text("Search Reports")')
            if search_btn.count() == 0:
                # Try alternative selectors
                search_btn = self._page.locator('button.btn-primary:visible').first
            if search_btn.count() == 0:
                search_btn = self._page.locator('button:has-text("Search Reports")').first
            
            if search_btn.count() > 0:
                search_btn.click()
                scraper_logger.debug("Clicked search button")
                # Wait for results - the site uses AJAX to load data
                self._page.wait_for_timeout(5000)
                self._page.wait_for_load_state("networkidle", timeout=60000)
            
            # The site loads results via DataTables AJAX
            # Wait for the table to appear
            self._page.wait_for_timeout(3000)
            
            # Check if results table appeared
            table = self._page.locator('table#filedReports, table.dataTable, #DataTables_Table_0, table').first
            if table.count() > 0:
                scraper_logger.debug("Found results table")
                
                # Get all rows
                rows = self._page.locator('table tbody tr').all()
                scraper_logger.debug(f"Found {len(rows)} table rows")
                
                for row in rows:
                    try:
                        cells = row.locator('td').all()
                        if len(cells) < 5:
                            continue
                        
                        # Extract data from cells
                        # Column order: First Name, Last Name, Full Name, Report Type (with link), Date
                        first_name = cells[0].inner_text().strip()
                        last_name = cells[1].inner_text().strip()
                        full_name = cells[2].inner_text().strip()  # "Alexander, Lamar (Senator)"
                        
                        # Report type cell has the link
                        report_cell = cells[3]
                        report_link = report_cell.locator('a').first
                        
                        report_type_text = report_cell.inner_text().strip()
                        report_url = report_link.get_attribute('href') if report_link.count() > 0 else None
                        
                        if report_url and report_url.startswith('/'):
                            report_url = BASE_URL + report_url
                        
                        filing_date = cells[4].inner_text().strip() if len(cells) > 4 else ""
                        
                        # Use full name for politician, or combine first + last
                        politician = full_name if full_name else f"{first_name} {last_name}"
                        
                        is_pdf = report_url and '.pdf' in report_url.lower() if report_url else False
                        
                        results.append({
                            'politician': politician,
                            'report_type': report_type_text,
                            'disclosure_date': parse_date(filing_date) if filing_date else None,
                            'report_url': report_url,
                            'is_pdf': is_pdf,
                            'chamber': 'senate',
                        })
                    
                    except Exception as e:
                        scraper_logger.debug(f"Error parsing row: {e}")
                        continue
            
            scraper_logger.info(f"Found {len(results)} filings")
            return results
            
        except Exception as e:
            scraper_logger.error(f"Error searching filings: {e}")
            return []
    
    def _parse_html_report(self, url: str) -> list[dict]:
        """Parse an HTML format report."""
        transactions = []
        
        try:
            self._page.goto(url, wait_until="networkidle", timeout=30000)
            
            # Find transaction tables
            rows = self._page.locator('table tbody tr').all()
            
            for row in rows:
                cells = row.locator('td').all()
                if len(cells) < 5:
                    continue
                
                try:
                    asset_text = cells[0].inner_text()
                    ticker = self._extract_ticker(asset_text)
                    
                    transactions.append({
                        'asset_name': asset_text.strip(),
                        'ticker': ticker,
                        'trade_type': cells[1].inner_text().strip().lower(),
                        'trade_date': parse_date(cells[2].inner_text().strip()),
                        'amount': parse_amount(cells[3].inner_text().strip()),
                        'owner': cells[4].inner_text().strip() if len(cells) > 4 else '',
                    })
                except Exception as e:
                    scraper_logger.debug(f"Error parsing transaction: {e}")
                    continue
            
            return transactions
            
        except Exception as e:
            scraper_logger.error(f"Error parsing HTML report: {e}")
            return []
    
    def _extract_ticker(self, text: str) -> Optional[str]:
        """Extract stock ticker from text."""
        # Look for ticker in parentheses like "Apple Inc (AAPL)"
        match = re.search(r'\(([A-Z]{1,5})\)', text)
        if match:
            return match.group(1)
        
        # Look for standalone uppercase letters
        match = re.search(r'\b([A-Z]{2,5})\b(?:\s*$|[,.\s])', text)
        if match:
            ticker = match.group(1)
            if ticker not in ['LLC', 'INC', 'CORP', 'LTD', 'ETF', 'THE', 'AND']:
                return ticker
        
        return None
    
    def _normalize_name(self, name: str) -> str:
        """Normalize politician name for comparison."""
        name = re.sub(r'\bHon\.?\s*\.?\s*', '', name, flags=re.IGNORECASE)
        name = re.sub(r'\bSenator\s*', '', name, flags=re.IGNORECASE)
        
        if ',' in name:
            parts = name.split(',', 1)
            name = f"{parts[1].strip()} {parts[0].strip()}"
        
        name = re.sub(r'\s+', ' ', name)
        return name.lower().strip(' .')
    
    def _download_pdf(self, url: str, politician: str) -> Optional[Path]:
        """Download a PDF file."""
        try:
            # Generate filename upfront
            safe_name = re.sub(r'[^\w\-]', '_', politician)[:50]
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"senate_{safe_name}_{timestamp}.pdf"
            filepath = RAW_PDFS_DIR / filename
            
            # Ensure directory exists
            RAW_PDFS_DIR.mkdir(parents=True, exist_ok=True)
            
            scraper_logger.info(f"Downloading PDF from: {url}")
            
            # Use expect_download which properly handles the download event
            try:
                with self._page.expect_download(timeout=60000) as download_info:
                    # Navigate to trigger download - use evaluate to avoid the navigation error
                    self._page.evaluate(f"window.location.href = '{url}'")
                
                download = download_info.value
                # Wait for download to complete
                download_path = download.path()
                if download_path:
                    # Copy to our destination
                    import shutil
                    shutil.copy(download_path, filepath)
                    scraper_logger.info(f"Downloaded PDF: {filepath.name}")
                    return filepath
                else:
                    download.save_as(filepath)
                    scraper_logger.info(f"Downloaded PDF (save_as): {filepath.name}")
                    return filepath
                
            except Exception as download_err:
                scraper_logger.warning(f"Download failed: {download_err}")
                return None
                
        except Exception as e:
            scraper_logger.error(f"Failed to download PDF: {e}")
            return None
    
    def scrape(self) -> list[dict]:
        """Main scrape method."""
        scraper_logger.info("Starting Senate Playwright scraper...")
        
        try:
            self._start_browser()
            
            if not self._accept_agreement():
                scraper_logger.error("Failed to accept Senate agreement")
                return []
            
            return self._search_filings()
            
        except Exception as e:
            scraper_logger.error(f"Scrape error: {e}")
            return []
        finally:
            self._stop_browser()
    
    def scrape_and_process(self, whitelist: list[str]) -> tuple[int, int]:
        """
        Scrape and process filings, creating TradeSignals.
        
        Returns tuple of (html_count, pdf_count).
        """
        try:
            self._start_browser()
            
            if not self._accept_agreement():
                return 0, 0
            
            filings = self._search_filings()
            html_count = 0
            pdf_count = 0
            
            whitelist_normalized = [self._normalize_name(p) for p in whitelist]
            
            for filing in filings:
                politician = filing.get('politician', '')
                politician_normalized = self._normalize_name(politician)
                
                # Fuzzy whitelist check
                is_whitelisted = False
                for wl_name in whitelist_normalized:
                    if wl_name in politician_normalized or politician_normalized in wl_name:
                        is_whitelisted = True
                        break
                    wl_parts = set(wl_name.split())
                    pol_parts = set(politician_normalized.split())
                    if len(wl_parts & pol_parts) >= 2:
                        is_whitelisted = True
                        break
                
                if not is_whitelisted:
                    continue
                
                report_url = filing.get('report_url')
                if not report_url:
                    continue
                
                disclosure_date = filing.get('disclosure_date') or datetime.now().strftime("%Y-%m-%d")
                
                if filing.get('is_pdf'):
                    pdf_path = self._download_pdf(report_url, politician)
                    if pdf_path:
                        pdf_count += 1
                else:
                    transactions = self._parse_html_report(report_url)
                    
                    for tx in transactions:
                        ticker = tx.get('ticker')
                        trade_type = tx.get('trade_type', '').lower()
                        
                        if trade_type in ['buy', 'purchased', 'bought', 'purchase']:
                            trade_type = 'purchase'
                        elif trade_type in ['sell', 'sold', 'sale']:
                            trade_type = 'sale'
                        else:
                            continue
                        
                        if not ticker:
                            continue
                        
                        trade_date = tx.get('trade_date') or disclosure_date
                        lag_days = 0
                        if trade_date and disclosure_date:
                            try:
                                trade_dt = datetime.strptime(trade_date, "%Y-%m-%d")
                                disc_dt = datetime.strptime(disclosure_date, "%Y-%m-%d")
                                lag_days = (disc_dt - trade_dt).days
                            except ValueError:
                                lag_days = 30
                        
                        config = get_config()
                        signal_type = 'direct' if lag_days <= config.trading.stale_signal_threshold else 'sector_etf'
                        
                        signal = TradeSignal(
                            ticker=ticker.upper(),
                            politician=politician,
                            trade_type=trade_type,
                            amount_midpoint=tx.get('amount', 10000.0),
                            trade_date=trade_date,
                            disclosure_date=disclosure_date,
                            lag_days=lag_days,
                            signal_type=signal_type,
                            chamber='senate',
                            asset_name=tx.get('asset_name'),
                            pdf_url=report_url,
                        )
                        
                        if not self.db.signal_exists(
                            signal.ticker, signal.politician,
                            signal.trade_date, signal.trade_type
                        ):
                            self.db.insert_trade_signal(signal)
                            scraper_logger.info(
                                f"Created signal: {trade_type.upper()} {ticker} by {politician}"
                            )
                    
                    html_count += 1
            
            return html_count, pdf_count
            
        except Exception as e:
            scraper_logger.error(f"Process error: {e}")
            return 0, 0
        finally:
            self._stop_browser()


# -----------------------------------------------------------------------------
# Convenience function
# -----------------------------------------------------------------------------
def run_senate_playwright_scraper(whitelist: list[str], headless: bool = True) -> list[dict]:
    """Run the Playwright-based Senate scraper."""
    scraper = SenatePlaywrightScraper(headless=headless)
    return scraper.scrape()


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    
    print("Testing Senate Playwright scraper...")
    scraper = SenatePlaywrightScraper(headless=False)  # Visible for testing
    filings = scraper.scrape()
    
    print(f"Found {len(filings)} filings:")
    for f in filings[:5]:
        print(f"  - {f['politician']}: {f.get('report_url', 'No URL')}")
