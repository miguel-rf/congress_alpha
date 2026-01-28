#!/bin/bash
# Congressional Alpha System - One-Click Start Script
# Starts API, Dashboard, and optionally the Scraper

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo -e "${CYAN}"
echo "╔═══════════════════════════════════════════════════════════╗"
echo "║           Congressional Alpha System Launcher             ║"
echo "╚═══════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# Function to check if a port is in use
check_port() {
    if lsof -Pi :$1 -sTCP:LISTEN -t >/dev/null 2>&1; then
        return 0  # Port is in use
    else
        return 1  # Port is free
    fi
}

# Function to cleanup on exit
cleanup() {
    echo -e "\n${YELLOW}Shutting down services...${NC}"
    
    # Kill background processes
    if [ ! -z "$API_PID" ]; then
        kill $API_PID 2>/dev/null || true
        echo -e "${GREEN}✓ API stopped${NC}"
    fi
    
    if [ ! -z "$UI_PID" ]; then
        kill $UI_PID 2>/dev/null || true
        echo -e "${GREEN}✓ Dashboard stopped${NC}"
    fi
    
    if [ ! -z "$SCRAPER_PID" ]; then
        kill $SCRAPER_PID 2>/dev/null || true
        echo -e "${GREEN}✓ Scraper stopped${NC}"
    fi
    
    echo -e "${GREEN}All services stopped. Goodbye!${NC}"
    exit 0
}

# Trap Ctrl+C and call cleanup
trap cleanup SIGINT SIGTERM

# Load .env file if exists
if [ -f "$SCRIPT_DIR/.env" ]; then
    echo -e "${BLUE}Loading environment variables from .env...${NC}"
    set -a
    source "$SCRIPT_DIR/.env"
    set +a
fi

# Check for virtual environment
if [ ! -d "$SCRIPT_DIR/.venv" ]; then
    echo -e "${RED}Error: Virtual environment not found. Run ./setup_arm64.sh first.${NC}"
    exit 1
fi

# Activate virtual environment
echo -e "${BLUE}Activating Python virtual environment...${NC}"
source "$SCRIPT_DIR/.venv/bin/activate"

# Check if node_modules exists for UI
if [ ! -d "$SCRIPT_DIR/ui/node_modules" ]; then
    echo -e "${YELLOW}Installing UI dependencies...${NC}"
    cd "$SCRIPT_DIR/ui"
    npm install
    cd "$SCRIPT_DIR"
fi

# Start API
echo -e "\n${GREEN}▶ Starting Backend API on port 8000...${NC}"
if check_port 8000; then
    echo -e "${YELLOW}  Port 8000 already in use, skipping API start${NC}"
else
    cd "$SCRIPT_DIR"
    uvicorn api.main:app --host 0.0.0.0 --port 8000 &
    API_PID=$!
    sleep 2
    echo -e "${GREEN}  ✓ API running at http://localhost:8000${NC}"
    echo -e "${GREEN}  ✓ API docs at http://localhost:8000/docs${NC}"
fi

# Start Dashboard UI
echo -e "\n${GREEN}▶ Starting Dashboard UI on port 3000...${NC}"
if check_port 3000; then
    echo -e "${YELLOW}  Port 3000 already in use, skipping UI start${NC}"
else
    cd "$SCRIPT_DIR/ui"
    npm run dev &
    UI_PID=$!
    sleep 3
    echo -e "${GREEN}  ✓ Dashboard running at http://localhost:3000${NC}"
fi

cd "$SCRIPT_DIR"

# Ask about scraper
echo -e "\n${CYAN}═══════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}Services Started Successfully!${NC}"
echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"
echo ""
echo -e "  ${BLUE}📊 Dashboard:${NC}  http://localhost:3000"
echo -e "  ${BLUE}🔌 API:${NC}        http://localhost:8000"
echo -e "  ${BLUE}📖 API Docs:${NC}   http://localhost:8000/docs"
echo ""
echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}"
echo ""
echo -e "${YELLOW}Press Ctrl+C to stop all services${NC}"
echo ""

# Keep script running and wait for interrupt
wait
