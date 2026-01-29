"""
Congressional Alpha System - Configuration Settings

Centralized configuration management with environment variable loading
and validation for API keys, paths, and system constants.
"""
from __future__ import annotations

import os
import logging
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    # Load from project root .env file
    _env_path = Path(__file__).parent.parent / ".env"
    if _env_path.exists():
        load_dotenv(_env_path)
except ImportError:
    pass  # dotenv not installed, rely on system environment variables

# -----------------------------------------------------------------------------
# Path Configuration
# -----------------------------------------------------------------------------
BASE_DIR = Path(__file__).parent.parent
CONFIG_DIR = BASE_DIR / "config"
DATA_DIR = BASE_DIR / "data"
RAW_PDFS_DIR = DATA_DIR / "raw_pdfs"
DATABASE_PATH = DATA_DIR / "congress_alpha.db"

# Ensure directories exist
DATA_DIR.mkdir(exist_ok=True)
RAW_PDFS_DIR.mkdir(exist_ok=True)

# -----------------------------------------------------------------------------
# Logging Configuration
# -----------------------------------------------------------------------------
LOG_FORMAT = "[%(asctime)s] %(levelname)s [%(name)s] %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format=LOG_FORMAT,
    datefmt=LOG_DATE_FORMAT
)

logger = logging.getLogger("congress_alpha")


# -----------------------------------------------------------------------------
# API Configuration
# -----------------------------------------------------------------------------
@dataclass
class Trading212Config:
    """Trading212 API configuration."""
    api_key: str = field(default_factory=lambda: os.getenv("TRADING212_API_KEY", ""))
    api_secret: str = field(default_factory=lambda: os.getenv("TRADING212_API_SECRET", ""))
    environment: str = field(default_factory=lambda: os.getenv("TRADING212_ENV", "demo"))
    
    @property
    def base_url(self) -> str:
        """Get base URL based on environment."""
        if self.environment == "live":
            return "https://live.trading212.com"
        return "https://demo.trading212.com"
    
    def validate(self) -> bool:
        """Check if Trading212 credentials are configured."""
        if not self.api_key or not self.api_secret:
            logger.warning("Trading212 API credentials not configured")
            return False
        return True


@dataclass
class OpenRouterConfig:
    """OpenRouter LLM API configuration."""
    api_key: str = field(default_factory=lambda: os.getenv("OPENROUTER_API_KEY", ""))
    base_url: str = "https://openrouter.ai/api/v1"
    # Free models on OpenRouter
    model: str = "openai/gpt-oss-120b:free"
    
    def validate(self) -> bool:
        """Check if OpenRouter credentials are configured."""
        if not self.api_key:
            logger.warning("OpenRouter API key not configured")
            return False
        return True


# -----------------------------------------------------------------------------
# Scraping Configuration
# -----------------------------------------------------------------------------
@dataclass
class ScrapingConfig:
    """Web scraping configuration and rate limits."""
    # House of Representatives
    house_url: str = "https://disclosures-clerk.house.gov/FinancialDisclosure"
    house_search_url: str = "https://disclosures-clerk.house.gov/FinancialDisclosure/Search"
    
    # Senate
    senate_url: str = "https://efdsearch.senate.gov/search/"
    senate_search_url: str = "https://efdsearch.senate.gov/search/report/data/"
    
    # Rate limiting
    min_delay_seconds: int = 30
    max_delay_seconds: int = 180
    
    # User agents for rotation
    user_agents: list[str] = field(default_factory=lambda: [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    ])


# -----------------------------------------------------------------------------
# Trading Configuration
# -----------------------------------------------------------------------------
@dataclass
class TradingConfig:
    """Trading rules and risk parameters."""
    # Liquidity filter
    min_market_cap: float = 300_000_000  # $300M minimum
    
    # Wash sale lookback
    wash_sale_days: int = 30
    
    # Signal freshness thresholds
    immediate_signal_max_lag: int = 10  # days
    stale_signal_threshold: int = 45  # days - trigger sector rotation


# -----------------------------------------------------------------------------
# Scheduler Configuration
# -----------------------------------------------------------------------------
@dataclass
class SchedulerConfig:
    """Adaptive scheduling configuration."""
    # Market hours (Eastern Time)
    market_open_hour: int = 9
    market_close_hour: int = 18
    
    # Scrape intervals (minutes)
    market_hours_min_interval: int = 10
    market_hours_max_interval: int = 15
    off_hours_interval: int = 240  # 4 hours
    
    # Anti-bot jitter (seconds)
    jitter_min: int = 30
    jitter_max: int = 180


# -----------------------------------------------------------------------------
# Global Config Instance
# -----------------------------------------------------------------------------
@dataclass
class Config:
    """Main configuration container."""
    trading212: Trading212Config = field(default_factory=Trading212Config)
    openrouter: OpenRouterConfig = field(default_factory=OpenRouterConfig)
    scraping: ScrapingConfig = field(default_factory=ScrapingConfig)
    trading: TradingConfig = field(default_factory=TradingConfig)
    scheduler: SchedulerConfig = field(default_factory=SchedulerConfig)
    
    def validate_all(self) -> dict[str, bool]:
        """Validate all API configurations."""
        return {
            "trading212": self.trading212.validate(),
            "openrouter": self.openrouter.validate(),
        }


# Singleton config instance
config = Config()


def get_config() -> Config:
    """Get the global configuration instance."""
    return config
