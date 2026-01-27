# 🚀 Oracle Cloud ARM64 Setup Guide

Complete guide to deploying the **Congressional Alpha System** on Oracle Cloud Free Tier (ARM64).

---

## 📋 Table of Contents

1. [Prerequisites](#-prerequisites)
2. [Create Oracle Cloud Instance](#-create-oracle-cloud-instance)
3. [Connect to Your Instance](#-connect-to-your-instance)
4. [Clone & Install the Application](#-clone--install-the-application)
5. [Configure Environment Variables](#-configure-environment-variables)
6. [Configure Whitelist](#-configure-whitelist)
7. [Running the Application](#-running-the-application)
8. [Setting Up Automated Runs (Cron)](#-setting-up-automated-runs-cron)
9. [Monitoring & Logs](#-monitoring--logs)
10. [Troubleshooting](#-troubleshooting)

---

## 🔧 Prerequisites

Before you begin, ensure you have:

- ✅ An Oracle Cloud account ([Free Tier available](https://www.oracle.com/cloud/free/))
- ✅ SSH key pair generated on your local machine
- ✅ Trading212 API key ([Get it here](https://www.trading212.com/api))
- ✅ OpenRouter API key ([Get it here](https://openrouter.ai/keys))
- ✅ Your GitHub repository URL for this project

---

## ☁️ Create Oracle Cloud Instance

### Step 1: Log into Oracle Cloud Console

1. Go to [Oracle Cloud Console](https://cloud.oracle.com/)
2. Sign in with your account

### Step 2: Create a Compute Instance

1. Navigate to **Compute** → **Instances** → **Create Instance**

2. **Configure the instance:**
   | Setting | Value |
   |---------|-------|
   | **Name** | `congress-alpha` |
   | **Compartment** | Default (or your preferred) |
   | **Image** | Ubuntu 24.04 Minimal (aarch64) |
   | **Shape** | `VM.Standard.A1.Flex` |
   | **OCPUs** | 2-4 (Free tier allows up to 4) |
   | **Memory** | 12-24 GB (Free tier allows up to 24 GB) |

3. **Networking:**
   - Select your VCN or create a new one
   - Enable "Assign a public IPv4 address"

4. **SSH Keys:**
   - Upload your public SSH key (`~/.ssh/id_rsa.pub` or `~/.ssh/id_ed25519.pub`)
   - Or paste the public key contents

5. Click **Create** and wait for the instance to be **RUNNING**

### Step 3: Configure Security List (Firewall)

If you want to access the web dashboard:

1. Go to **Networking** → **Virtual Cloud Networks** → Your VCN
2. Click on your **Subnet** → **Security Lists**
3. Add an **Ingress Rule**:
   | Setting | Value |
   |---------|-------|
   | Source CIDR | `0.0.0.0/0` |
   | IP Protocol | TCP |
   | Destination Port | `8000` |

---

## 🔗 Connect to Your Instance

### Get Your Public IP

1. Go to **Compute** → **Instances**
2. Click on your instance
3. Copy the **Public IP Address**

### SSH Connection

```bash
# From your local machine
ssh -i ~/.ssh/your_private_key ubuntu@YOUR_PUBLIC_IP

# Example:
ssh -i ~/.ssh/id_rsa ubuntu@129.146.123.456
```

> **Note:** The default username for Ubuntu images is `ubuntu`

---

## 📦 Clone & Install the Application

### Step 1: Clone the Repository

```bash
# Navigate to home directory
cd ~

# Clone your repository
git clone https://github.com/YOUR_USERNAME/congress_alpha.git

# Enter the project directory
cd congress_alpha
```

### Step 2: Run the Setup Script

The project includes an automated setup script for ARM64:

```bash
# Make the script executable
chmod +x setup_arm64.sh

# Run the setup script (this may take 5-10 minutes)
./setup_arm64.sh
```

**What this script does:**
- ✅ Updates system packages
- ✅ Installs Tesseract OCR and PDF utilities
- ✅ Creates Python virtual environment
- ✅ Installs all Python dependencies
- ✅ Sets up Playwright with Chromium browser
- ✅ Creates required directory structure

### Step 3: Verify Installation

```bash
# Activate the virtual environment
source .venv/bin/activate

# Verify Python packages
python3 -c "import requests, bs4, pytesseract, playwright; print('✅ All packages installed!')"

# Check Tesseract
tesseract --version
```

---

## 🔐 Configure Environment Variables

### Step 1: Create Your .env File

```bash
# Copy the example file
cp .env.example .env

# Edit with nano (or vim)
nano .env
```

### Step 2: Fill in Your API Keys

```env
# Congressional Alpha System - Environment Variables

# =============================================================================
# TRADING212 API (Required for trading)
# =============================================================================
TRADING212_API_KEY=your_actual_api_key_here
TRADING212_API_SECRET=your_actual_secret_here
TRADING212_ENV=demo  # Use "demo" first to test, then "live" for real trades

# =============================================================================
# OPENROUTER API (Required for OCR/LLM parsing)
# =============================================================================
OPENROUTER_API_KEY=your_openrouter_key_here

# =============================================================================
# OPTIONAL SETTINGS
# =============================================================================
LOG_LEVEL=INFO
```

### Step 3: Secure Your .env File

```bash
# Set proper permissions (only you can read)
chmod 600 .env

# Verify it's not tracked by git
cat .gitignore | grep ".env"
```

---

## 👥 Configure Whitelist

Edit the whitelist to specify which politicians to track:

```bash
nano config/whitelist.json
```

**Example configuration:**

```json
{
  "house": [
    {"name": "Nancy Pelosi", "state": "CA"},
    {"name": "Dan Crenshaw", "state": "TX"}
  ],
  "senate": [
    {"name": "Tommy Tuberville", "state": "AL"},
    {"name": "Markwayne Mullin", "state": "OK"}
  ]
}
```

---

## ▶️ Running the Application

### Activate Virtual Environment First

```bash
cd ~/congress_alpha
source .venv/bin/activate
```

### Run Main Script (Full Pipeline)

```bash
python main.py
```

### Run Specific Components

```bash
# Scrape House disclosures only
python main.py --house-only

# Scrape Senate disclosures only
python main.py --senate-only

# Dry run (no actual trades)
python main.py --dry-run

# Run API server
python -m uvicorn api.main:app --host 0.0.0.0 --port 8000
```

### Access API Dashboard

If you configured the firewall:
```
http://YOUR_PUBLIC_IP:8000
```

---

## ⏰ Setting Up Automated Runs (Cron)

### Edit Crontab

```bash
crontab -e
```

### Add Scheduled Tasks

```cron
# Congressional Alpha - Automated Scraping
# Format: minute hour day month weekday command

# Run every weekday at 6:00 AM, 12:00 PM, and 6:00 PM (market hours)
0 6,12,18 * * 1-5 cd /home/ubuntu/congress_alpha && /home/ubuntu/congress_alpha/.venv/bin/python main.py >> /home/ubuntu/congress_alpha/cron.log 2>&1

# Weekly full rescan on Sunday at midnight
0 0 * * 0 cd /home/ubuntu/congress_alpha && /home/ubuntu/congress_alpha/.venv/bin/python main.py --full-scan >> /home/ubuntu/congress_alpha/cron.log 2>&1
```

### Verify Cron is Running

```bash
# List your scheduled jobs
crontab -l

# Check cron service status
sudo systemctl status cron
```

---

## 📊 Monitoring & Logs

### View Application Logs

```bash
# View main log file
tail -f ~/congress_alpha/cron.log

# View last 100 lines
tail -100 ~/congress_alpha/cron.log

# Search for errors
grep -i "error" ~/congress_alpha/cron.log
```

### Check Database

```bash
cd ~/congress_alpha
source .venv/bin/activate

# View recent trades in SQLite
sqlite3 data/trades.db "SELECT * FROM trades ORDER BY timestamp DESC LIMIT 10;"
```

### System Resources

```bash
# Check disk space
df -h

# Check memory usage
free -h

# Check running processes
htop  # (install with: sudo apt install htop)
```

---

## 🔧 Troubleshooting

### Common Issues & Solutions

#### 1. SSH Connection Refused

```bash
# Check if SSH is running on the instance
sudo systemctl status ssh

# Verify security list allows port 22
# Oracle Cloud Console → Networking → VCN → Security Lists
```

#### 2. Playwright Browser Fails

```bash
# Reinstall Playwright browsers
source .venv/bin/activate
playwright install chromium
playwright install-deps

# Check if Chromium is installed
which chromium-browser
```

#### 3. Out of Memory

ARM64 instances might run out of memory with heavy OCR:

```bash
# Add swap space
sudo fallocate -l 4G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile

# Make permanent
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

#### 4. API Connection Errors

```bash
# Test Trading212 connectivity
curl -H "Authorization: Bearer YOUR_API_KEY" https://demo.trading212.com/api/v0/equity/account/info

# Test OpenRouter connectivity
curl -H "Authorization: Bearer YOUR_API_KEY" https://openrouter.ai/api/v1/models
```

#### 5. Senate Cookies Expired

The Senate website requires authentication. If scraping fails:

```bash
# Extract fresh cookies (see USER_GUIDE.md for instructions)
nano config/cookies.json
```

---

## 🔄 Updating the Application

```bash
cd ~/congress_alpha

# Pull latest changes
git pull origin main

# Reinstall dependencies if requirements changed
source .venv/bin/activate
pip install -r requirements.txt

# Restart any running services
```

---

## 📞 Quick Reference

| Command | Description |
|---------|-------------|
| `source .venv/bin/activate` | Activate virtual environment |
| `python main.py` | Run full pipeline |
| `python main.py --dry-run` | Test without trading |
| `tail -f cron.log` | Monitor logs |
| `crontab -l` | List scheduled jobs |
| `sudo systemctl status cron` | Check cron service |

---

## 🛡️ Security Best Practices

1. **Never commit `.env` file** - It's in `.gitignore`
2. **Use demo mode first** - Test with `TRADING212_ENV=demo`
3. **Set file permissions** - `chmod 600 .env`
4. **Rotate API keys** periodically
5. **Monitor trade logs** for unexpected activity
6. **Enable Oracle Cloud WAF** for additional protection

---

*Last updated: January 2026*
