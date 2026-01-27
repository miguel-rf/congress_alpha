"""
Congressional Alpha System - Senate Financial Disclosure Scraper

Scrapes financial disclosures from efdsearch.senate.gov using
cookie injection to bypass CAPTCHA barriers.
"""
from __future__ import annotations

import json
import re
import random
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional
from dataclasses import dataclass

import requests
from bs4 import BeautifulSoup

# Local imports
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from config.settings import get_config, CONFIG_DIR, RAW_PDFS_DIR, logger
from modules.db_manager import get_db, TradeSignal

# Module logger
scraper_logger = logging.getLogger("congress_alpha.scraper_senate")

# -----------------------------------------------------------------------------
# Constants
# -----------------------------------------------------------------------------
BASE_URL = "https://efdsearch.senate.gov"
SEARCH_URL = f"{BASE_URL}/search/"
SEARCH_API_URL = f"{BASE_URL}/search/report/data/"
COOKIES_FILE = CONFIG_DIR / "cookies.json"


# -----------------------------------------------------------------------------
# Amount Range Parsing (Same as House)
# -----------------------------------------------------------------------------
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
    
    # Try to parse custom range format
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
    
    formats = [
        "%m/%d/%Y",
        "%Y-%m-%d",
        "%m-%d-%Y",
        "%B %d, %Y",
        "%b %d, %Y",
    ]
    
    for fmt in formats:
        try:
            dt = datetime.strptime(date_str, fmt)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue
    
    return None


# -----------------------------------------------------------------------------
# Cookie Management
# -----------------------------------------------------------------------------
class CookieManager:
    """Manages browser cookies for authentication."""
    
    def __init__(self, cookies_path: Path = COOKIES_FILE):
        self.cookies_path = cookies_path
    
    def load_cookies(self) -> dict[str, str]:
        """Load cookies from JSON file."""
        if not self.cookies_path.exists():
            scraper_logger.warning(f"Cookies file not found: {self.cookies_path}")
            return {}
        
        try:
            with open(self.cookies_path, 'r') as f:
                data = json.load(f)
            
            cookies = {}
            for cookie in data.get('cookies', []):
                if isinstance(cookie, dict):
                    name = cookie.get('name', '')
                    value = cookie.get('value', '')
                    if name and value:
                        cookies[name] = value
                elif isinstance(cookie, str):
                    # Simple "name=value" format
                    if '=' in cookie:
                        name, value = cookie.split('=', 1)
                        cookies[name.strip()] = value.strip()
            
            return cookies
            
        except (json.JSONDecodeError, KeyError) as e:
            scraper_logger.error(f"Error parsing cookies file: {e}")
            return {}
    
    def has_valid_cookies(self) -> bool:
        """Check if we have any cookies configured."""
        cookies = self.load_cookies()
        return len(cookies) > 0


# -----------------------------------------------------------------------------
# Main Scraper Class
# -----------------------------------------------------------------------------
class SenateScraper:
    """
    Scraper for Senate financial disclosures.
    
    Uses cookie injection to bypass CAPTCHA barriers.
    Falls back gracefully if cookies expire.
    """
    
    def __init__(self):
        self.config = get_config()
        self.db = get_db()
        self.cookie_manager = CookieManager()
        self.session = requests.Session()
        self._setup_session()
    
    def _setup_session(self) -> None:
        """Configure session with headers and cookies."""
        user_agent = random.choice(self.config.scraping.user_agents)
        self.session.headers.update({
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Referer": SEARCH_URL,
        })
        
        # Load and inject cookies
        cookies = self.cookie_manager.load_cookies()
        if cookies:
            self.session.cookies.update(cookies)
            scraper_logger.info(f"Loaded {len(cookies)} cookies")
        else:
            scraper_logger.warning("No cookies loaded - scraper may fail")
    
    def _check_auth(self, response: requests.Response) -> bool:
        """
        Check if we're authenticated (not redirected to CAPTCHA).
        
        Returns True if authenticated, False if auth failed.
        """
        # Check for common auth failure indicators
        if response.url and 'agreement' in response.url.lower():
            return False
        
        if response.url and 'captcha' in response.url.lower():
            return False
        
        # Check response content for auth walls
        content_lower = response.text.lower()
        auth_indicators = [
            'i understand the prohibitions',
            'checkbox',
            'agree to the terms',
            'captcha',
        ]
        
        for indicator in auth_indicators:
            if indicator in content_lower:
                return False
        
        return True
    
    def _fetch_search_page(self) -> Optional[str]:
        """Fetch the search page to verify authentication."""
        try:
            response = self.session.get(SEARCH_URL, timeout=30, allow_redirects=True)
            response.raise_for_status()
            
            if not self._check_auth(response):
                scraper_logger.warning(
                    "⚠️ REFRESH COOKIES: Senate authentication failed. "
                    "Please extract new cookies from your browser."
                )
                self.db.log_event(
                    "WARNING",
                    "scraper_senate",
                    "Authentication failed - cookies need refresh"
                )
                return None
            
            return response.text
            
        except requests.RequestException as e:
            scraper_logger.error(f"Failed to fetch search page: {e}")
            return None
    
    def _search_ptr_filings(self, senator_name: str = "") -> Optional[dict]:
        """
        Search for PTR filings using the Senate API.
        
        The Senate site uses a DataTables-style AJAX API.
        """
        # Build search payload
        payload = {
            'draw': 1,
            'columns[0][data]': 0,
            'columns[0][searchable]': 'true',
            'columns[1][data]': 1,
            'columns[1][searchable]': 'true',
            'start': 0,
            'length': 100,  # Number of results
            'search[value]': senator_name,
            'report_types': '[{"id":"11"}]',  # PTR report type
            'submitted_start_date': '',
            'submitted_end_date': '',
            'senator_state': '',
            'order[0][column]': 3,  # Sort by date
            'order[0][dir]': 'desc',
        }
        
        try:
            response = self.session.post(
                SEARCH_API_URL,
                data=payload,
                timeout=30
            )
            response.raise_for_status()
            
            # Check auth on API response too
            if not self._check_auth(response):
                scraper_logger.warning("⚠️ REFRESH COOKIES: API auth failed")
                return None
            
            return response.json()
            
        except requests.RequestException as e:
            scraper_logger.error(f"Search API request failed: {e}")
            return None
        except json.JSONDecodeError as e:
            scraper_logger.error(f"Invalid JSON response: {e}")
            return None
    
    def _parse_api_results(self, data: dict) -> list[dict]:
        """Parse the DataTables API response."""
        results = []
        
        records = data.get('data', [])
        
        for record in records:
            try:
                # Record is typically a list of values
                if isinstance(record, list) and len(record) >= 4:
                    # Parse the HTML in the first cell for name/link
                    name_html = record[0]
                    soup = BeautifulSoup(name_html, 'lxml')
                    
                    name_link = soup.find('a')
                    name = name_link.get_text(strip=True) if name_link else ''
                    
                    # Get report URL
                    report_url = None
                    if name_link and name_link.get('href'):
                        href = name_link['href']
                        report_url = BASE_URL + href if href.startswith('/') else href
                    
                    # Determine format (HTML or PDF)
                    is_pdf = report_url and '.pdf' in report_url.lower() if report_url else False
                    
                    # Other columns
                    office = record[1] if len(record) > 1 else ''
                    report_type = record[2] if len(record) > 2 else ''
                    filing_date = record[3] if len(record) > 3 else ''
                    
                    results.append({
                        'politician': name,
                        'office': office,
                        'report_type': report_type,
                        'disclosure_date': parse_date(filing_date) if filing_date else None,
                        'report_url': report_url,
                        'is_pdf': is_pdf,
                        'chamber': 'senate',
                    })
                
            except Exception as e:
                scraper_logger.warning(f"Error parsing record: {e}")
                continue
        
        return results
    
    def _download_pdf(self, url: str, politician: str) -> Optional[Path]:
        """Download a PDF to the raw_pdfs directory."""
        try:
            response = self.session.get(url, timeout=60)
            response.raise_for_status()
            
            # Generate filename
            safe_name = re.sub(r'[^\w\-]', '_', politician)[:50]
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{safe_name}_{timestamp}.pdf"
            filepath = RAW_PDFS_DIR / filename
            
            with open(filepath, 'wb') as f:
                f.write(response.content)
            
            scraper_logger.info(f"Downloaded PDF: {filepath}")
            return filepath
            
        except requests.RequestException as e:
            scraper_logger.error(f"Failed to download PDF: {e}")
            return None
    
    def _parse_html_report(self, url: str) -> list[dict]:
        """Parse an HTML format report (low latency path)."""
        try:
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            
            if not self._check_auth(response):
                return []
            
            soup = BeautifulSoup(response.text, 'lxml')
            transactions = []
            
            # Find transaction tables
            tables = soup.find_all('table')
            
            for table in tables:
                rows = table.find_all('tr')[1:]  # Skip header
                
                for row in rows:
                    cells = row.find_all('td')
                    if len(cells) < 5:
                        continue
                    
                    try:
                        transaction = {
                            'asset_name': cells[0].get_text(strip=True),
                            'ticker': self._extract_ticker(cells[0].get_text()),
                            'trade_type': cells[1].get_text(strip=True).lower(),
                            'trade_date': parse_date(cells[2].get_text(strip=True)),
                            'amount': parse_amount(cells[3].get_text(strip=True)),
                            'owner': cells[4].get_text(strip=True) if len(cells) > 4 else '',
                        }
                        transactions.append(transaction)
                    except Exception as e:
                        scraper_logger.debug(f"Error parsing transaction row: {e}")
                        continue
            
            return transactions
            
        except requests.RequestException as e:
            scraper_logger.error(f"Failed to fetch HTML report: {e}")
            return []
    
    def _extract_ticker(self, text: str) -> Optional[str]:
        """Try to extract a stock ticker from text."""
        # Look for ticker in parentheses like "Apple Inc (AAPL)"
        match = re.search(r'\(([A-Z]{1,5})\)', text)
        if match:
            return match.group(1)
        
        # Look for standalone uppercase letters that look like tickers
        # At end of string or followed by punctuation
        match = re.search(r'\b([A-Z]{2,5})\b(?:\s*$|[,.\s])', text)
        if match:
            ticker = match.group(1)
            # Filter out common non-ticker words
            if ticker not in ['LLC', 'INC', 'CORP', 'LTD', 'ETF', 'THE', 'AND']:
                return ticker
        
        return None
    
    def scrape(self, senator_name: str = "") -> list[dict]:
        """
        Main scrape method with format forking.
        
        1. Verify authentication
        2. Search for PTR filings
        3. Fork based on format:
           - HTML: Parse directly (low latency)
           - PDF: Download for OCR (high latency)
        """
        scraper_logger.info("Starting Senate scraper...")
        
        # Check cookies
        if not self.cookie_manager.has_valid_cookies():
            scraper_logger.warning(
                "⚠️ REFRESH COOKIES: No cookies configured. "
                "Skipping Senate scrape."
            )
            return []
        
        # Verify authentication
        if not self._fetch_search_page():
            scraper_logger.warning("Skipping Senate scrape due to auth failure")
            return []
        
        # Search for filings
        api_response = self._search_ptr_filings(senator_name)
        if not api_response:
            return []
        
        filings = self._parse_api_results(api_response)
        scraper_logger.info(f"Found {len(filings)} Senate PTR filings")
        
        return filings
    
    def scrape_and_process(self, whitelist: list[str]) -> tuple[int, int]:
        """
        Scrape and process filings with format forking.
        
        Returns tuple of (html_count, pdf_count) for processed filings.
        """
        filings = self.scrape()
        html_count = 0
        pdf_count = 0
        
        # Normalize whitelist for fuzzy matching
        whitelist_normalized = [self._normalize_name(p) for p in whitelist]
        
        for filing in filings:
            politician = filing.get('politician', '')
            politician_normalized = self._normalize_name(politician)
            
            # Fuzzy whitelist check (same logic as House scraper)
            is_whitelisted = False
            for wl_name in whitelist_normalized:
                # Check if either name contains the other
                if wl_name in politician_normalized or politician_normalized in wl_name:
                    is_whitelisted = True
                    break
                # Check individual name components (at least 2 parts match)
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
            
            # Format fork
            if filing.get('is_pdf'):
                # High latency path: Download for OCR
                pdf_path = self._download_pdf(report_url, politician)
                if pdf_path:
                    self.db.log_event(
                        "INFO",
                        "scraper_senate",
                        f"Downloaded PDF for OCR: {politician} -> {pdf_path}"
                    )
                    pdf_count += 1
            else:
                # Low latency path: Parse HTML directly and CREATE SIGNALS
                transactions = self._parse_html_report(report_url)
                
                for tx in transactions:
                    ticker = tx.get('ticker')
                    trade_type = tx.get('trade_type', '').lower()
                    
                    # Normalize trade type
                    if trade_type in ['buy', 'purchased', 'bought', 'purchase']:
                        trade_type = 'purchase'
                    elif trade_type in ['sell', 'sold', 'sale']:
                        trade_type = 'sale'
                    else:
                        continue  # Unknown trade type
                    
                    if not ticker:
                        continue
                    
                    # Calculate lag days
                    trade_date = tx.get('trade_date') or disclosure_date
                    lag_days = 0
                    if trade_date and disclosure_date:
                        try:
                            trade_dt = datetime.strptime(trade_date, "%Y-%m-%d")
                            disc_dt = datetime.strptime(disclosure_date, "%Y-%m-%d")
                            lag_days = (disc_dt - trade_dt).days
                        except ValueError:
                            lag_days = 30
                    
                    # Determine signal type based on lag
                    from config.settings import get_config
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
                    
                    # Check for duplicates
                    if not self.db.signal_exists(
                        signal.ticker, signal.politician,
                        signal.trade_date, signal.trade_type
                    ):
                        signal_id = self.db.insert_trade_signal(signal)
                        scraper_logger.info(
                            f"Created signal: {trade_type.upper()} {ticker} "
                            f"by {politician} (${tx.get('amount', 0):,.0f})"
                        )
                    else:
                        scraper_logger.debug(f"Duplicate signal skipped: {ticker}")
                
                html_count += 1
        
        return html_count, pdf_count
    
    def _normalize_name(self, name: str) -> str:
        """Normalize politician name for comparison."""
        import re
        # Remove honorifics
        name = re.sub(r'\bHon\.?\s*\.?\s*', '', name, flags=re.IGNORECASE)
        name = re.sub(r'\bSenator\s*', '', name, flags=re.IGNORECASE)
        
        # Handle "Last, First" format
        if ',' in name:
            parts = name.split(',', 1)
            name = f"{parts[1].strip()} {parts[0].strip()}"
        
        # Remove extra whitespace
        name = re.sub(r'\s+', ' ', name)
        name = name.strip(' .')
        
        return name.lower()


# -----------------------------------------------------------------------------
# Module-level convenience function
# -----------------------------------------------------------------------------
def run_senate_scraper(whitelist: list[str]) -> list[dict]:
    """Run the Senate scraper and return filings."""
    scraper = SenateScraper()
    return scraper.scrape()


if __name__ == "__main__":
    # Quick test
    logging.basicConfig(level=logging.DEBUG)
    scraper = SenateScraper()
    filings = scraper.scrape()
    print(f"Found {len(filings)} filings")
    for f in filings[:5]:
        print(f"  - {f['politician']}: {f.get('report_url', 'No URL')}")
