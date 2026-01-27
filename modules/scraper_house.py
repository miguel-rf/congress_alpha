"""
Congressional Alpha System - House of Representatives Scraper

Scrapes financial disclosures from disclosures-clerk.house.gov
Updated for the new MVC-based site structure (2024+).
"""
from __future__ import annotations

import re
import random
import logging
from datetime import datetime
from typing import Optional
from dataclasses import dataclass
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# Local imports
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from config.settings import get_config, RAW_PDFS_DIR, logger
from modules.db_manager import get_db, TradeSignal

# Module logger
scraper_logger = logging.getLogger("congress_alpha.scraper_house")

# -----------------------------------------------------------------------------
# Constants
# -----------------------------------------------------------------------------
BASE_URL = "https://disclosures-clerk.house.gov"
SEARCH_PAGE_URL = f"{BASE_URL}/FinancialDisclosure/ViewSearch"
MEMBER_SEARCH_URL = f"{BASE_URL}/FinancialDisclosure/ViewMemberSearchResult"


# -----------------------------------------------------------------------------
# Amount Range Parsing
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
    
    # Check predefined ranges
    if amount_str in AMOUNT_RANGES:
        return AMOUNT_RANGES[amount_str]
    
    # Try to parse custom range format: "$X - $Y" or "$X-$Y"
    match = re.match(r'\$?([\d,]+)\s*[-–]\s*\$?([\d,]+)', amount_str)
    if match:
        low = float(match.group(1).replace(',', ''))
        high = float(match.group(2).replace(',', ''))
        return (low + high) / 2
    
    # Single value
    match = re.match(r'\$?([\d,]+)', amount_str)
    if match:
        return float(match.group(1).replace(',', ''))
    
    scraper_logger.warning(f"Could not parse amount: {amount_str}")
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
    
    scraper_logger.warning(f"Could not parse date: {date_str}")
    return None


def normalize_name(name: str) -> str:
    """
    Normalize politician name for comparison.
    
    Handles formats like:
    - "Pelosi, Hon.. Nancy"
    - "Hon. Nancy Pelosi"
    - "Nancy Pelosi"
    """
    # Remove honorifics
    name = re.sub(r'\bHon\.?\s*\.?\s*', '', name, flags=re.IGNORECASE)
    
    # Handle "Last, First" format
    if ',' in name:
        parts = name.split(',', 1)
        name = f"{parts[1].strip()} {parts[0].strip()}"
    
    # Remove extra whitespace and periods
    name = re.sub(r'\s+', ' ', name)
    name = name.replace('..', '.').replace('. ', ' ')
    name = name.strip(' .')
    
    return name.lower()


# -----------------------------------------------------------------------------
# Main Scraper Class
# -----------------------------------------------------------------------------
class HouseScraper:
    """
    Scraper for House of Representatives financial disclosures.
    
    Updated for the new MVC site (2024+) which uses simple POST forms
    instead of ASP.NET ViewState.
    """
    
    def __init__(self):
        self.config = get_config()
        self.db = get_db()
        self.session = requests.Session()
        self._setup_session()
    
    def _setup_session(self) -> None:
        """Configure session with headers."""
        user_agent = random.choice(self.config.scraping.user_agents)
        self.session.headers.update({
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Referer": SEARCH_PAGE_URL,
            "Origin": BASE_URL,
        })
    
    def _search_filings(self, 
                        last_name: str = "",
                        year: Optional[int] = None,
                        state: str = "",
                        district: str = "") -> Optional[str]:
        """
        Search for PTR filings using the new API.
        
        Args:
            last_name: Filter by last name (optional)
            year: Filing year (defaults to current year)
            state: Two-letter state code (optional)
            district: District number (optional)
        
        Returns:
            HTML response containing the results table, or None on error.
        """
        if year is None:
            year = datetime.now().year
        
        # Build POST payload - note the API accepts empty strings
        payload = {
            'LastName': last_name,
            'FilingYear': str(year),
            'State': state,
            'District': district,
        }
        
        try:
            response = self.session.post(
                MEMBER_SEARCH_URL,
                data=payload,
                timeout=30
            )
            response.raise_for_status()
            return response.text
            
        except requests.RequestException as e:
            scraper_logger.error(f"Search request failed: {e}")
            return None
    
    def _parse_results(self, html: str) -> list[dict]:
        """
        Parse the results table from the search response.
        
        New table structure:
        - Name (with PDF link)
        - Office (e.g., "CA12", "Former Member (TX32)")
        - Filing Year
        - Filing (type, e.g., "PTR Original", "Amendment")
        """
        soup = BeautifulSoup(html, 'lxml')
        results = []
        
        # Find the results table
        table = soup.find('table', {'class': 'library-table'})
        if not table:
            # Fallback: find any table with the expected structure
            tables = soup.find_all('table')
            for t in tables:
                if t.find('th', string=lambda x: x and 'Name' in x):
                    table = t
                    break
        
        if not table:
            scraper_logger.warning("Results table not found in response")
            return results
        
        rows = table.find_all('tr')[1:]  # Skip header row
        
        for row in rows:
            cells = row.find_all('td')
            if len(cells) < 4:
                continue
            
            try:
                # Extract name and PDF link
                name_cell = cells[0]
                name_link = name_cell.find('a')
                
                if not name_link:
                    continue
                
                raw_name = name_link.get_text(strip=True)
                
                # Build full PDF URL
                href = name_link.get('href', '')
                if href:
                    if href.startswith('/'):
                        pdf_url = BASE_URL + href
                    elif href.startswith('public_disc'):
                        pdf_url = f"{BASE_URL}/{href}"
                    elif href.startswith('http'):
                        pdf_url = href
                    else:
                        pdf_url = f"{BASE_URL}/FinancialDisclosure/{href}"
                else:
                    pdf_url = None
                
                # Parse other columns
                office = cells[1].get_text(strip=True)
                filing_year = cells[2].get_text(strip=True)
                filing_type = cells[3].get_text(strip=True)
                
                # Only include PTR (Periodic Transaction Report) filings
                if 'PTR' not in filing_type.upper():
                    continue
                
                results.append({
                    'politician': raw_name,
                    'politician_normalized': normalize_name(raw_name),
                    'office': office,
                    'filing_year': filing_year,
                    'filing_type': filing_type,
                    'pdf_url': pdf_url,
                    'chamber': 'house',
                    'scraped_at': datetime.now().isoformat(),
                })
                
            except Exception as e:
                scraper_logger.warning(f"Error parsing row: {e}")
                continue
        
        return results
    
    def _download_pdf(self, url: str, politician: str) -> Optional[Path]:
        """Download a PDF to the raw_pdfs directory."""
        try:
            response = self.session.get(url, timeout=60)
            response.raise_for_status()
            
            # Verify it's actually a PDF
            content_type = response.headers.get('Content-Type', '')
            if 'pdf' not in content_type.lower() and not response.content[:4] == b'%PDF':
                scraper_logger.warning(f"Response is not a PDF: {content_type}")
                return None
            
            # Generate filename
            safe_name = re.sub(r'[^\w\-]', '_', politician)[:50]
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"house_{safe_name}_{timestamp}.pdf"
            filepath = RAW_PDFS_DIR / filename
            
            # Ensure directory exists
            RAW_PDFS_DIR.mkdir(parents=True, exist_ok=True)
            
            with open(filepath, 'wb') as f:
                f.write(response.content)
            
            scraper_logger.info(f"Downloaded PDF: {filepath}")
            return filepath
            
        except requests.RequestException as e:
            scraper_logger.error(f"Failed to download PDF: {e}")
            return None
    
    def scrape(self, year: Optional[int] = None) -> list[dict]:
        """
        Main scrape method.
        
        1. POST search request
        2. Parse results table
        3. Return list of filings
        
        Args:
            year: Filing year to search (defaults to current year)
            
        Returns:
            List of filing dictionaries.
        """
        scraper_logger.info("Starting House scraper...")
        
        # Search for all PTR filings
        results_html = self._search_filings(year=year)
        if not results_html:
            scraper_logger.error("Search request failed")
            return []
        
        # Check for error messages in response
        if 'No results found' in results_html or 'no matching records' in results_html.lower():
            scraper_logger.info("No filings found for search criteria")
            return []
        
        # Parse results
        filings = self._parse_results(results_html)
        scraper_logger.info(f"Found {len(filings)} PTR filings")
        
        return filings
    
    def scrape_and_process(self, whitelist: list[str], 
                           year: Optional[int] = None) -> tuple[int, int]:
        """
        Scrape filings and download PDFs for whitelisted politicians.
        
        Args:
            whitelist: List of politician names to track
            year: Filing year (defaults to current year)
            
        Returns:
            Tuple of (total_filings, downloaded_pdfs)
        """
        filings = self.scrape(year)
        downloaded = 0
        
        # Normalize whitelist for comparison
        whitelist_normalized = [normalize_name(p) for p in whitelist]
        
        whitelisted_filings = []
        
        for filing in filings:
            politician_norm = filing.get('politician_normalized', '')
            
            # Check if politician is in whitelist (fuzzy match)
            is_whitelisted = False
            for wl_name in whitelist_normalized:
                # Check if either name contains the other (handles partial matches)
                if wl_name in politician_norm or politician_norm in wl_name:
                    is_whitelisted = True
                    break
                # Also check individual name components
                wl_parts = set(wl_name.split())
                pol_parts = set(politician_norm.split())
                if len(wl_parts & pol_parts) >= 2:  # At least 2 name parts match
                    is_whitelisted = True
                    break
            
            if not is_whitelisted:
                continue
            
            whitelisted_filings.append(filing)
            
            # Download PDF for OCR processing
            pdf_url = filing.get('pdf_url')
            if pdf_url:
                pdf_path = self._download_pdf(pdf_url, filing['politician'])
                if pdf_path:
                    self.db.log_event(
                        "INFO",
                        "scraper_house",
                        f"Downloaded PDF: {filing['politician']} -> {pdf_path}"
                    )
                    downloaded += 1
        
        scraper_logger.info(
            f"Whitelisted filings: {len(whitelisted_filings)}, "
            f"PDFs downloaded: {downloaded}"
        )
        
        return len(whitelisted_filings), downloaded


# -----------------------------------------------------------------------------
# Module-level convenience function
# -----------------------------------------------------------------------------
def run_house_scraper(whitelist: list[str], year: Optional[int] = None) -> list[dict]:
    """Run the House scraper and return filings."""
    scraper = HouseScraper()
    return scraper.scrape(year)


if __name__ == "__main__":
    # Quick test
    logging.basicConfig(level=logging.DEBUG)
    scraper = HouseScraper()
    filings = scraper.scrape()
    print(f"Found {len(filings)} filings")
    for f in filings[:10]:
        print(f"  - {f['politician']}: {f['pdf_url']}")
