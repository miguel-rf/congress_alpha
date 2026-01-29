# Congressional Alpha System - Modules Package
"""
Modules for the Congressional Alpha copy-trading system.

- db_manager: SQLite database management
- scraper_house: House of Representatives disclosure scraper (Playwright-based)
- scraper_senate: Senate financial disclosure scraper (Playwright-based)
- ocr_engine: PDF to text extraction with LLM parsing
- trade_executor: Trading212 trade execution with risk guards

Note: This system uses Playwright-based scrapers for reliable browser automation.
Install Playwright with: pip install playwright && playwright install chromium
"""
