# Congressional Alpha System - Complete User Guide

A comprehensive guide to using the Congressional Alpha copy-trading platform.

---

## Table of Contents

1. [Overview](#overview)
2. [Installation](#installation)
3. [Configuration](#configuration)
4. [Running the System](#running-the-system)
5. [Web UI Guide](#web-ui-guide)
6. [API Reference](#api-reference)
7. [Troubleshooting](#troubleshooting)

---

## Overview

Congressional Alpha monitors U.S. congressional stock disclosures and automatically copy-trades on Trading212. The system consists of:

| Component | Description |
|-----------|-------------|
| **Scrapers** | Pull disclosures from House & Senate websites |
| **OCR Engine** | Extract trade data from PDF filings |
| **Trade Executor** | Execute trades on Trading212 with risk guards |
| **Web UI** | Real-time dashboard for monitoring (Next.js) |
| **REST API** | FastAPI backend for the UI |

### How It Works

```
1. Scrapers fetch new disclosures → 2. OCR extracts trade data
                                           ↓
4. Trade Executor buys/sells ← 3. Signals stored in SQLite
                                           ↓
                                   5. Web UI displays status
```

---

## Installation

### Prerequisites

- Python 3.11+
- Node.js 18+
- Tesseract OCR
- Poppler (for PDF processing)

### Quick Setup

```bash
# Clone and enter directory
cd /home/miguel/congress_alpha

# Run setup script (installs all dependencies)
chmod +x setup_arm64.sh
./setup_arm64.sh

# Activate virtual environment
source .venv/bin/activate

# Install API dependencies
pip install fastapi uvicorn

# Install UI dependencies
cd ui && npm install && cd ..
```

---

## Configuration

### 1. Environment Variables

Create a `.env` file or add to `~/.bashrc`:

```bash
# Trading212 API (required for trading)
export TRADING212_API_KEY="your_api_key"
export TRADING212_API_SECRET="your_api_secret"
export TRADING212_ENV="demo"  # "demo" or "live"

# OpenRouter API (required for OCR)
export OPENROUTER_API_KEY="your_openrouter_key"
```

### 2. Senate Cookies (Required)

The Senate website requires authentication cookies:

1. Open Chrome/Firefox → `https://efdsearch.senate.gov/search/`
2. Complete the CAPTCHA/checkbox
3. Open DevTools (F12) → Application → Cookies
4. Copy values to `config/cookies.json`:

```json
{
  "cookies": [
    {"name": "csrftoken", "value": "YOUR_CSRF_TOKEN"},
    {"name": "sessionid", "value": "YOUR_SESSION_ID"}
  ]
}
```

### 3. Whitelist Politicians

Edit `config/whitelist.json` to add politicians to track:

```json
{
  "politicians": [
    {
      "name": "Nancy Pelosi",
      "chamber": "house",
      "notes": "Former Speaker, known for tech stock timing"
    }
  ]
}
```

**Finding Politicians:**
- [Capitol Trades](https://www.capitoltrades.com/) - Historical performance
- [Unusual Whales](https://unusualwhales.com/congress) - Recent trades

---

## Running the System

### Option 1: CLI Scheduler (Headless)

```bash
# Activate environment
source .venv/bin/activate

# Run continuously (adaptive scheduling)
python main.py

# Run single cycle (for cron)
python main.py --once

# Debug mode
python main.py --debug
```

### Option 2: Web UI + API

**Terminal 1 - Start API:**
```bash
cd /home/miguel/congress_alpha
source .venv/bin/activate
uvicorn api.main:app --reload --port 8000
```

**Terminal 2 - Start Web UI:**
```bash
cd /home/miguel/congress_alpha/ui
npm run dev
```

**Access:**
- Web UI: `http://localhost:3000`
- API Docs: `http://localhost:8000/docs`

### Option 3: Production (Cron)

```bash
crontab -e

# During market hours (9 AM - 6 PM ET, Mon-Fri)
*/15 9-17 * * 1-5 cd /home/miguel/congress_alpha && .venv/bin/python main.py --once >> /var/log/congress_alpha.log 2>&1

# Off hours (every 4 hours)
0 */4 * * * cd /home/miguel/congress_alpha && .venv/bin/python main.py --once >> /var/log/congress_alpha.log 2>&1
```

---

## Web UI Guide

### Dashboard (`/`)

The main overview page showing:

| Section | Description |
|---------|-------------|
| **Stats Grid** | Total signals, pending signals, win rate, P&L |
| **Pending Signals** | Latest unprocessed trade signals |
| **Politicians** | List of tracked politicians |

**Features:**
- 🟢 **Live Updates** - Auto-refreshes every 30 seconds
- ↻ **Manual Refresh** - Click to update immediately
- ⏱️ **Last Updated** - Shows time since last refresh

---

### Signals (`/signals`)

View all congressional trade signals:

| Column | Description |
|--------|-------------|
| **Ticker** | Stock symbol (e.g., AAPL, NVDA) |
| **Politician** | Name of filer |
| **Chamber** | House (purple) or Senate (cyan) |
| **Type** | Buy (green) or Sell (red) |
| **Amount** | Estimated trade value |
| **Lag** | Days between trade and disclosure |
| **Status** | Pending or Processed |

**Filters:**
- **All** - Show all signals
- **Pending** - Unprocessed signals only
- **Processed** - Already executed signals

**Lag Color Coding:**
- 🟢 Green (≤10 days) - Fresh signal, trade exact ticker
- 🟡 Yellow (11-45 days) - Moderate lag
- 🔴 Red (>45 days) - Stale, use sector ETF instead

---

### Trades (`/trades`)

View executed trade history:

| Metric | Description |
|--------|-------------|
| **Total Trades** | Number of executed trades |
| **Win Rate** | Percentage of profitable trades |
| **Realized P&L** | Total profit/loss from closed positions |
| **Avg Trade Size** | Average dollar amount per trade |
| **Best Trade** | Highest single trade profit |
| **Worst Trade** | Largest single trade loss |

---

### Portfolio (`/portfolio`)

View Trading212 account positions:

| Column | Description |
|--------|-------------|
| **Ticker** | Stock symbol |
| **Quantity** | Number of shares |
| **Avg Price** | Average purchase price |
| **Current Price** | Live market price |
| **Market Value** | Current position value |
| **P&L** | Unrealized profit/loss |
| **P&L %** | Percentage gain/loss |

**Account Summary:**
- Total Value
- Cash Available
- Invested Value
- Unrealized P&L

---

### Politicians (`/politicians`)

Manage the whitelist of tracked politicians:

**View:**
- Name, Chamber, Notes for each politician
- Count by chamber (House vs Senate)

**Add New:**
1. Click "+ Add Politician"
2. Enter name (must match disclosure filings exactly)
3. Select chamber (House or Senate)
4. Add optional notes
5. Click "Add"

---

### Logs (`/logs`)

Monitor system activity:

| Section | Description |
|---------|-------------|
| **Scheduler Status** | Market hours, scrape interval |
| **Configuration** | API status, trading parameters |
| **Log Entries** | Recent system events |

**Log Levels:**
- 🔵 INFO - Normal operations
- 🟡 WARNING - Potential issues
- 🔴 ERROR - Failures requiring attention

---

## API Reference

Base URL: `http://localhost:8000`

### Signals

```bash
# List signals (paginated)
GET /api/signals?page=1&page_size=20&processed=false

# Get pending signals
GET /api/signals/pending

# Get specific signal
GET /api/signals/{id}

# Mark as processed
POST /api/signals/{id}/process
```

### Trades

```bash
# List trades
GET /api/trades?page=1

# Get statistics
GET /api/trades/stats

# Get trades by ticker
GET /api/trades/ticker/{ticker}
```

### Portfolio

```bash
# Get positions
GET /api/portfolio/positions

# Get account summary
GET /api/portfolio/summary

# Get cash balance
GET /api/portfolio/cash
```

### Politicians

```bash
# List all
GET /api/politicians

# Get count
GET /api/politicians/count

# Add new
POST /api/politicians
{"name": "John Doe", "chamber": "house", "notes": "Active trader"}

# Remove
DELETE /api/politicians/{name}
```

### System

```bash
# Get stats
GET /api/stats

# Get logs
GET /api/logs?limit=100&level=ERROR

# Get config
GET /api/config

# Get scheduler status
GET /api/scheduler/status
```

---

## Troubleshooting

### "REFRESH COOKIES" Warning

Senate cookies expired. Re-extract from browser.

### "Trading212 credentials not configured"

Set environment variables:
```bash
export TRADING212_API_KEY="..."
export TRADING212_API_SECRET="..."
```

### API Connection Failed

1. Check API is running: `curl http://localhost:8000/health`
2. Verify CORS settings in `api/main.py`
3. Check firewall rules

### No Signals Appearing

1. Verify whitelist has politicians
2. Check Senate cookies are valid
3. Run `python main.py --debug` for verbose output

### OCR Failures

```bash
# Install Tesseract
sudo apt-get install tesseract-ocr

# Install PDF tools
sudo apt-get install poppler-utils
```

---

## Trading Rules

### Signal Types

| Lag Days | Action |
|----------|--------|
| ≤10 days | Trade exact ticker |
| >45 days | Trade sector ETF |

### Risk Guards

| Guard | Condition | Action |
|-------|-----------|--------|
| Liquidity | Market Cap < $300M | REJECT |
| Wash Sale | Sold at loss < 30 days ago | REJECT |

### Sector ETF Mapping

When signals are stale, the system trades sector ETFs:

| Sector | ETF |
|--------|-----|
| Technology | XLK |
| Healthcare | XLV |
| Financial | XLF |
| Energy | XLE |
| Default | SPY |

---

## Tips for Profitability

1. **Track fast disclosers** - Politicians with <15 day average lag
2. **Focus on high volume traders** - More data points
3. **Use demo mode first** - Test with paper trading
4. **Monitor daily** - Check the dashboard for new signals
5. **Refresh Senate cookies weekly** - Prevents scraping failures

---

## File Structure

```
congress_alpha/
├── main.py              # CLI scheduler
├── api/                 # FastAPI backend
│   ├── main.py
│   └── routes/
├── ui/                  # Next.js frontend
│   ├── app/
│   ├── components/
│   └── lib/
├── modules/             # Core Python modules
├── config/              # Configuration files
└── data/                # SQLite database
```

---

## Support

- GitHub Issues: Report bugs
- Logs: Check `/var/log/congress_alpha.log`
- API Docs: `http://localhost:8000/docs`

⚠️ **Disclaimer**: This is for educational purposes. Trading involves risk.
