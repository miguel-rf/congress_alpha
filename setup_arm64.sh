#!/bin/bash
###############################################################################
# Congressional Alpha System - ARM64 Setup Script
# Target: Ubuntu 24.04 Minimal (Oracle Cloud Free Tier ARM64)
# 
# This script installs all system dependencies and Python packages required
# for the copy-trading platform.
###############################################################################
set -Eeuo pipefail

# -----------------------------------------------------------------------------
# Logging Functions
# -----------------------------------------------------------------------------
log_info() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] INFO: $*"
}

log_warn() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] WARN: $*" >&2
}

log_error() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] ERROR: $*" >&2
}

# -----------------------------------------------------------------------------
# Error Handling
# -----------------------------------------------------------------------------
trap 'log_error "Error on line $LINENO. Exit code: $?"' ERR

# -----------------------------------------------------------------------------
# Dependency Checking
# -----------------------------------------------------------------------------
check_architecture() {
    local arch
    arch=$(uname -m)
    
    if [[ "$arch" != "aarch64" && "$arch" != "arm64" ]]; then
        log_warn "Architecture is $arch, not ARM64. Some packages may differ."
    else
        log_info "ARM64 architecture confirmed: $arch"
    fi
}

check_ubuntu_version() {
    if [[ -f /etc/os-release ]]; then
        . /etc/os-release
        log_info "Detected OS: $NAME $VERSION_ID"
    else
        log_warn "Could not detect OS version"
    fi
}

# -----------------------------------------------------------------------------
# System Package Installation
# -----------------------------------------------------------------------------
install_system_deps() {
    log_info "Updating package lists..."
    sudo apt-get update -y
    
    log_info "Installing system dependencies..."
    sudo apt-get install -y \
        tesseract-ocr \
        libtesseract-dev \
        poppler-utils \
        python3-pip \
        python3-venv \
        python3-dev \
        build-essential \
        libffi-dev \
        libssl-dev \
        libjpeg-dev \
        zlib1g-dev \
        libpng-dev \
        curl \
        wget \
        git
    
    log_info "System dependencies installed successfully"
}

# -----------------------------------------------------------------------------
# Python Virtual Environment Setup
# -----------------------------------------------------------------------------
setup_python_venv() {
    local script_dir
    script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
    local venv_dir="$script_dir/.venv"
    
    if [[ -d "$venv_dir" ]]; then
        log_info "Virtual environment already exists at $venv_dir"
    else
        log_info "Creating Python virtual environment..."
        python3 -m venv "$venv_dir"
    fi
    
    log_info "Activating virtual environment..."
    # shellcheck source=/dev/null
    source "$venv_dir/bin/activate"
    
    log_info "Upgrading pip..."
    pip install --upgrade pip wheel setuptools
    
    log_info "Installing Python dependencies..."
    pip install -r "$script_dir/requirements.txt"
    
    log_info "Python dependencies installed successfully"
}

# -----------------------------------------------------------------------------
# Playwright Setup (ARM64 Compatible)
# -----------------------------------------------------------------------------
setup_playwright() {
    log_info "Installing Playwright system dependencies..."
    
    # Install Playwright browser dependencies
    # Note: On ARM64, Playwright uses system Chromium
    sudo apt-get install -y \
        libatk1.0-0 \
        libatk-bridge2.0-0 \
        libcups2 \
        libdrm2 \
        libxkbcommon0 \
        libxcomposite1 \
        libxdamage1 \
        libxfixes3 \
        libxrandr2 \
        libgbm1 \
        libasound2 \
        libpango-1.0-0 \
        libcairo2 \
        libnss3 \
        libnspr4 \
        libx11-xcb1 \
        chromium-browser || log_warn "Some Playwright deps may need manual install"
    
    log_info "Installing Playwright Python package and dependencies..."
    pip install playwright
    playwright install-deps || log_warn "playwright install-deps may need sudo"
    playwright install chromium || log_warn "Using system Chromium on ARM64"
    
    log_info "Playwright setup completed"
}

# -----------------------------------------------------------------------------
# Directory Structure Setup
# -----------------------------------------------------------------------------
setup_directories() {
    local script_dir
    script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
    
    log_info "Creating directory structure..."
    
    mkdir -p "$script_dir/data/raw_pdfs"
    mkdir -p "$script_dir/config"
    mkdir -p "$script_dir/modules"
    
    # Create __init__.py for modules package
    touch "$script_dir/modules/__init__.py"
    
    log_info "Directory structure created"
}

# -----------------------------------------------------------------------------
# Verify Installation
# -----------------------------------------------------------------------------
verify_installation() {
    log_info "Verifying installation..."
    
    local -a missing_deps=()
    local -a required=("tesseract" "pdftoppm" "python3")
    
    for cmd in "${required[@]}"; do
        if ! command -v "$cmd" &>/dev/null; then
            missing_deps+=("$cmd")
        fi
    done
    
    if [[ ${#missing_deps[@]} -gt 0 ]]; then
        log_error "Missing required commands: ${missing_deps[*]}"
        return 1
    fi
    
    # Verify Python packages
    log_info "Verifying Python packages..."
    python3 -c "import requests, bs4, pytesseract, pdf2image, PIL, yfinance" || {
        log_error "Some Python packages failed to import"
        return 1
    }
    
    log_info "All dependencies verified successfully!"
}

# -----------------------------------------------------------------------------
# Main Execution
# -----------------------------------------------------------------------------
main() {
    log_info "=========================================="
    log_info "Congressional Alpha System - ARM64 Setup"
    log_info "=========================================="
    
    check_architecture
    check_ubuntu_version
    
    install_system_deps
    setup_directories
    setup_python_venv
    setup_playwright
    verify_installation
    
    log_info "=========================================="
    log_info "Setup completed successfully!"
    log_info ""
    log_info "Next steps:"
    log_info "  1. Set environment variables:"
    log_info "     export ALPACA_API_KEY='your_key'"
    log_info "     export ALPACA_SECRET_KEY='your_secret'"
    log_info "     export OPENROUTER_API_KEY='your_key'"
    log_info ""
    log_info "  2. Configure whitelist.json with target politicians"
    log_info "  3. Extract Senate cookies to cookies.json"
    log_info "  4. Run: source .venv/bin/activate && python main.py"
    log_info "=========================================="
}

main "$@"
