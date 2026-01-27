# Congressional Alpha System

A high-frequency copy-trading platform that monitors U.S. congressional stock disclosures and executes trades on Trading212.

## Overview

The Congressional Alpha System scrapes financial disclosure filings from:
- **House of Representatives**: `disclosures-clerk.house.gov`
- **Senate**: `efdsearch.senate.gov`

It then parses the disclosures (using OCR for PDFs), filters for whitelisted politicians, and executes copy-trades with comprehensive risk management.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     Congressional Alpha System                  │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐       │
│  │   House      │    │   Senate     │    │    OCR       │       │
│  │   Scraper    │    │   Scraper    │    │   Engine     │       │
│  │              │    │              │    │              │       │
│  │ ViewState    │    │ Cookie       │    │ Tesseract +  │       │
│  │ Handshake    │    │ Injection    │    │ OpenRouter   │       │
│  └──────┬───────┘    └──────┬───────┘    └──────┬───────┘       │
│         │                   │                   │               │
│         └───────────────────┴───────────────────┘               │
│                             │                                   │
│                    ┌────────▼────────┐                          │
│                    │   SQLite DB     │                          │
│                    │   (trades,      │                          │
│                    │    history,     │                          │
│                    │    logs)        │                          │
│                    └────────┬────────┘                          │
│                             │                                   │
│                    ┌────────▼────────┐                          │
│                    │ Trade Executor  │                          │
│                    │                 │                          │
│                    │ • Liquidity     │                          │
│                    │ • Wash Sale     │                          │
│                    └────────┬────────┘                          │
│                             │                                   │
│                    ┌────────▼────────┐                          │
│                    │   Trading212    │                          │
│                    │   (demo/live)   │                          │
│                    └─────────────────┘                          │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

## Target Environment

- **Host**: Oracle Cloud Free Tier Instance
- **OS**: Ubuntu 24.04 Minimal
- **Architecture**: ARM64 (aarch64)
- **Interface**: Headless (CLI only)
- **Budget**: $0.00

## Quick Start

### 1. Clone and Setup

```bash
cd /path/to/congress_alpha
chmod +x setup_arm64.sh
./setup_arm64.sh
```

### 2. Configure Environment Variables

```bash
# Add to ~/.bashrc or create .env file
export TRADING212_API_KEY="your_trading212_api_key"
export TRADING212_API_SECRET="your_trading212_api_secret"
export TRADING212_ENV="demo"  # or "live" for real trading
export OPENROUTER_API_KEY="your_openrouter_api_key"
```

### 3. Configure Whitelist

Edit `config/whitelist.json` to specify which politicians to track:

```json
{
  "politicians": [
    {
      "name": "Nancy Pelosi",
      "chamber": "house",
      "notes": "Former Speaker, known for tech stock timing"
    },
    {
      "name": "Tommy Tuberville",
      "chamber": "senate",
      "notes": "Former coach, active stock trader"
    }
  ]
}
```

**Finding Politicians to Track:**
1. Visit [Capitol Trades](https://www.capitoltrades.com/) for historical performance
2. Check [Unusual Whales](https://unusualwhales.com/congress) for recent trades
3. Look for politicians with:
   - High trading volume
   - Quick disclosure (low lag days)
   - Consistent profitability

### 4. Configure Senate Cookies (Required)

The Senate website uses CAPTCHA/checkbox barriers. You must extract cookies manually:

1. Open Chrome/Firefox and navigate to: `https://efdsearch.senate.gov/search/`
2. Complete the CAPTCHA/checkbox agreement
3. Open Developer Tools (F12) → Application → Cookies
4. Copy the cookie values to `config/cookies.json`:

```json
{
  "cookies": [
    {"name": "csrftoken", "value": "your_csrf_token_value"},
    {"name": "sessionid", "value": "your_session_id_value"}
  ]
}
```

**Note**: Cookies expire after the session ends. If the scraper logs "REFRESH COOKIES", repeat this process.

### 5. Run the System

```bash
# Activate virtual environment
source .venv/bin/activate

# Run continuously (adaptive scheduling)
python main.py

# Or run a single cycle (for cron)
python main.py --once

# With debug logging
python main.py --debug
```

## Cron Job Setup

For production, use cron instead of the built-in scheduler:

```bash
# Edit crontab
crontab -e

# Add these lines:
# Run every 15 minutes during market hours (9 AM - 6 PM ET, Mon-Fri)
*/15 9-17 * * 1-5 cd /path/to/congress_alpha && /path/to/congress_alpha/.venv/bin/python main.py --once >> /var/log/congress_alpha.log 2>&1

# Run every 4 hours outside market hours
0 */4 * * * cd /path/to/congress_alpha && /path/to/congress_alpha/.venv/bin/python main.py --once >> /var/log/congress_alpha.log 2>&1
```

## Configuration Files

| File | Purpose |
|------|---------|
| `config/settings.py` | API keys, trading parameters, scheduler config |
| `config/whitelist.json` | Politicians to track |
| `config/sector_map.json` | Ticker → Sector ETF mapping |
| `config/symbol_map.json` | Standard ticker → Trading212 ticker mapping |
| `config/cookies.json` | Senate website auth cookies |

## Trading Rules

### Signal Generation

1. **Immediate Signal** (Lag < 10 days):
   - Trade the exact ticker the politician traded
   
2. **Sector Rotation** (Lag > 45 days):
   - Signal is stale, specific ticker timing lost
   - Trade the sector ETF instead (e.g., AAPL → XLK)

### Risk Guards

| Guard | Condition | Action |
|-------|-----------|--------|
| Liquidity | Market Cap < $300M | REJECT (micro-cap risk) |
| Wash Sale | Sold at loss < 30 days ago | REJECT (tax rule) |

## Directory Structure

```
congress_alpha/
├── config/
│   ├── settings.py         # Configuration management
│   ├── cookies.json        # Senate auth cookies
│   ├── whitelist.json      # Target politicians
│   └── sector_map.json     # Ticker → ETF mapping
├── data/
│   ├── congress.db         # SQLite database
│   └── raw_pdfs/           # Downloaded PDFs for OCR
├── modules/
│   ├── __init__.py
│   ├── db_manager.py       # Database operations
│   ├── scraper_house.py    # House disclosure scraper
│   ├── scraper_senate.py   # Senate disclosure scraper
│   ├── ocr_engine.py       # PDF → Text → JSON
│   └── trade_executor.py   # Trading212 trade execution
├── setup_arm64.sh          # System setup script
├── main.py                 # Main scheduler
├── requirements.txt        # Python dependencies
└── README.md               # This file
```

## API Keys

### Trading212

1. Go to [Trading212](https://www.trading212.com/)
2. Create an Invest or Stocks ISA account
3. Navigate to Settings → API → Generate API Key
4. Note: API is in beta, only Market Orders work in live environment

> **Important**: Trading212 uses a different ticker format. For example, Apple is `AAPL_US_EQ` not `AAPL`. The system handles this conversion automatically.

### OpenRouter (LLM)

1. Go to [OpenRouter](https://openrouter.ai/)
2. Create account and add a payment method (free tier available)
3. Generate API key
4. Uses `meta-llama/llama-3.2-3b-instruct:free` by default (free model)

## Troubleshooting

### "REFRESH COOKIES" Warning

The Senate cookies have expired. Re-extract them from your browser.

### "Trading212 credentials not configured"

Set the environment variables:
```bash
export TRADING212_API_KEY="..."
export TRADING212_API_SECRET="..."
export TRADING212_ENV="demo"  # or "live"
```

### "pytesseract not available"

Run the setup script or install manually:
```bash
sudo apt-get install tesseract-ocr libtesseract-dev
pip install pytesseract
```

### "pdf2image not available"

```bash
sudo apt-get install poppler-utils
pip install pdf2image
```

## Disclaimer

⚠️ **This is for educational and research purposes only.**

- This system uses paper trading only
- Congressional trading data has significant disclosure lag (up to 45 days)
- Past performance of politicians does not guarantee future results
- Always consult a financial advisor before making investment decisions
- Trading involves risk of loss

## License

MIT License - See LICENSE file for details.
