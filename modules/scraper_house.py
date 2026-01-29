"""
Congressional Alpha System - House Scraper with Playwright

Scrapes House of Representatives financial disclosures using Playwright
for reliable browser automation, avoiding rate limiting issues.
"""
from __future__ import annotations

import re
import random
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

# Local imports
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from config.settings import get_config, RAW_PDFS_DIR
from modules.db_manager import get_db, TradeSignal

# Module logger
scraper_logger = logging.getLogger("congress_alpha.scraper_house_playwright")

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
BASE_URL = "https://disclosures-clerk.house.gov"
SEARCH_PAGE_URL = f"{BASE_URL}/FinancialDisclosure"
VIEW_SEARCH_URL = f"{BASE_URL}/FinancialDisclosure/ViewSearch"

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


def normalize_name(name: str) -> str:
    """Normalize politician name for comparison."""
    name = re.sub(r'\bHon\.?\s*\.?\s*', '', name, flags=re.IGNORECASE)
    
    if ',' in name:
        parts = name.split(',', 1)
        name = f"{parts[1].strip()} {parts[0].strip()}"
    
    name = re.sub(r'\s+', ' ', name)
    name = name.replace('..', '.').replace('. ', ' ')
    return name.lower().strip(' .')


# -----------------------------------------------------------------------------
# Playwright-based House Scraper
# -----------------------------------------------------------------------------
class HousePlaywrightScraper:
    """
    House scraper using Playwright for reliable browser automation.
    
    Uses a real browser to avoid rate limiting and bot detection.
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
        self._playwright = None
    
    def _start_browser(self) -> None:
        """Start Playwright browser."""
        if self._browser:
            return
        
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(
            headless=self.headless,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--disable-features=IsolateOrigins,site-per-process',
            ]
        )
        
        # Create context with realistic settings
        context = self._browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent=random.choice(self.config.scraping.user_agents),
        )
        
        self._page = context.new_page()
        
        # Add extra headers
        self._page.set_extra_http_headers({
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        })
        
        scraper_logger.info("Started Playwright browser for House scraping")
    
    def _stop_browser(self) -> None:
        """Stop Playwright browser."""
        if self._browser:
            self._browser.close()
            self._playwright.stop()
            self._browser = None
            self._page = None
            scraper_logger.info("Stopped Playwright browser")
    
    def _random_delay(self, min_sec: float = 1.0, max_sec: float = 3.0) -> None:
        """Add random delay to appear more human."""
        delay = random.uniform(min_sec, max_sec)
        time.sleep(delay)
    
    def _search_filings(self, year: Optional[int] = None) -> list[dict]:
        """
        Search for PTR filings.
        
        Args:
            year: Filing year to search (defaults to current year)
        
        Returns:
            List of filing dictionaries
        """
        results = []
        
        if year is None:
            year = datetime.now().year
        
        try:
            # Navigate to search page
            scraper_logger.info(f"Navigating to House search page...")
            self._page.goto(VIEW_SEARCH_URL, wait_until="networkidle", timeout=60000)
            self._random_delay(1, 2)
            
            # Fill in search form
            # Select filing year
            year_select = self._page.locator('select[name="FilingYear"], #FilingYear')
            if year_select.count() > 0:
                year_select.first.select_option(str(year))
                self._random_delay(0.5, 1)
            
            # Click search button (it's a <button type="submit">, not <input>)
            search_btn = self._page.locator('button[type="submit"]:has-text("Search")').first
            if search_btn.count() > 0:
                search_btn.click()
                self._page.wait_for_load_state("networkidle", timeout=60000)
                self._random_delay(1, 2)
            
            # Parse results table
            results = self._parse_results_table()
            
            scraper_logger.info(f"Found {len(results)} PTR filings")
            return results
            
        except Exception as e:
            scraper_logger.error(f"Error searching filings: {e}")
            return []
    
    def _parse_results_table(self) -> list[dict]:
        """Parse the results table from the current page."""
        results = []
        
        try:
            # Find the results table
            table = self._page.locator('table.library-table, table').first
            if table.count() == 0:
                scraper_logger.warning("Results table not found")
                return results
            
            # Get all rows except header
            rows = self._page.locator('table tbody tr, table tr').all()
            
            for row in rows:
                try:
                    cells = row.locator('td').all()
                    if len(cells) < 4:
                        continue
                    
                    # Extract data
                    name_cell = cells[0]
                    name_link = name_cell.locator('a').first
                    
                    if name_link.count() == 0:
                        continue
                    
                    raw_name = name_link.inner_text()
                    href = name_link.get_attribute('href') or ''
                    
                    # Build full URL
                    # Relative hrefs like "public_disc/ptr-pdfs/2026/20033751.pdf" 
                    # should become "https://disclosures-clerk.house.gov/public_disc/..."
                    if href:
                        if href.startswith('http'):
                            pdf_url = href
                        elif href.startswith('/'):
                            pdf_url = BASE_URL + href
                        else:
                            # Relative path - append to base URL directly
                            pdf_url = f"{BASE_URL}/{href}"
                    else:
                        pdf_url = None
                    
                    office = cells[1].inner_text() if len(cells) > 1 else ""
                    filing_year = cells[2].inner_text() if len(cells) > 2 else ""
                    filing_type = cells[3].inner_text() if len(cells) > 3 else ""
                    
                    # Only include PTR filings
                    if 'PTR' not in filing_type.upper():
                        continue
                    
                    results.append({
                        'politician': raw_name.strip(),
                        'politician_normalized': normalize_name(raw_name),
                        'office': office.strip(),
                        'filing_year': filing_year.strip(),
                        'filing_type': filing_type.strip(),
                        'pdf_url': pdf_url,
                        'chamber': 'house',
                        'scraped_at': datetime.now().isoformat(),
                    })
                    
                except Exception as e:
                    scraper_logger.debug(f"Error parsing row: {e}")
                    continue
            
            return results
            
        except Exception as e:
            scraper_logger.error(f"Error parsing results table: {e}")
            return []
    
    def _download_pdf(self, url: str, politician: str) -> Optional[Path]:
        """Download a PDF file."""
        try:
            self._random_delay(0.5, 1.5)
            
            # Generate filename upfront
            safe_name = re.sub(r'[^\w\-]', '_', politician)[:50]
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"house_{safe_name}_{timestamp}.pdf"
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
    
    def scrape(self, year: Optional[int] = None) -> list[dict]:
        """
        Main scrape method.
        
        Args:
            year: Filing year to search (defaults to current year)
            
        Returns:
            List of filing dictionaries.
        """
        scraper_logger.info("Starting House Playwright scraper...")
        
        try:
            self._start_browser()
            return self._search_filings(year)
            
        except Exception as e:
            scraper_logger.error(f"Scrape error: {e}")
            return []
        finally:
            self._stop_browser()
    
    def scrape_and_process(self, whitelist: list[str], 
                           year: Optional[int] = None) -> tuple[int, int]:
        """
        Scrape filings and download PDFs for whitelisted politicians.
        
        Args:
            whitelist: List of politician names to track
            year: Filing year (defaults to current year)
            
        Returns:
            Tuple of (whitelisted_count, downloaded_pdfs)
        """
        try:
            self._start_browser()
            
            filings = self._search_filings(year)
            downloaded = 0
            
            # Normalize whitelist for comparison
            whitelist_normalized = [normalize_name(p) for p in whitelist]
            scraper_logger.info(f"Filtering {len(filings)} filings against {len(whitelist)} whitelisted politicians...")
            
            whitelisted_filings = []
            
            for filing in filings:
                politician_norm = filing.get('politician_normalized', '')
                
                # Check if politician is in whitelist (fuzzy match)
                is_whitelisted = False
                for wl_name in whitelist_normalized:
                    if wl_name in politician_norm or politician_norm in wl_name:
                        is_whitelisted = True
                        break
                    wl_parts = set(wl_name.split())
                    pol_parts = set(politician_norm.split())
                    if len(wl_parts & pol_parts) >= 2:
                        is_whitelisted = True
                        break
                
                if not is_whitelisted:
                    continue
                
                whitelisted_filings.append(filing)
                scraper_logger.info(f"Whitelisted politician found: {filing.get('politician', 'unknown')}")
                
                # Download PDF
                pdf_url = filing.get('pdf_url')
                if pdf_url:
                    politician = filing.get('politician', 'unknown')
                    scraper_logger.debug(f"Downloading PDF for {politician}...")
                    pdf_path = self._download_pdf(pdf_url, politician)
                    if pdf_path:
                        downloaded += 1
                    
                    # Small delay between downloads
                    self._random_delay(1, 3)
            
            scraper_logger.info(
                f"Processed {len(whitelisted_filings)} whitelisted filings, "
                f"downloaded {downloaded} PDFs"
            )
            
            return len(whitelisted_filings), downloaded
            
        except Exception as e:
            scraper_logger.error(f"Process error: {e}")
            return 0, 0
        finally:
            self._stop_browser()


# -----------------------------------------------------------------------------
# Convenience function
# -----------------------------------------------------------------------------
def run_house_playwright_scraper(whitelist: list[str], headless: bool = True) -> list[dict]:
    """Run the Playwright-based House scraper."""
    scraper = HousePlaywrightScraper(headless=headless)
    return scraper.scrape()


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    
    print("Testing House Playwright scraper...")
    scraper = HousePlaywrightScraper(headless=False)  # Visible for testing
    filings = scraper.scrape()
    
    print(f"Found {len(filings)} filings:")
    for f in filings[:5]:
        print(f"  - {f['politician']}: {f.get('pdf_url', 'No URL')}")
