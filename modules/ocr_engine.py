"""
Congressional Alpha System - OCR Engine

PDF to structured data extraction using Tesseract OCR and OpenRouter LLM.
Converts scanned/printed PDFs to text, then uses AI to extract trade details.
"""
from __future__ import annotations

import re
import json
import logging
import tempfile
import hashlib
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, asdict

import httpx
from PIL import Image

# Local imports
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from config.settings import get_config, RAW_PDFS_DIR, logger

# Module logger
ocr_logger = logging.getLogger("congress_alpha.ocr_engine")

# Check for optional dependencies
try:
    import pdfplumber
    PDFPLUMBER_AVAILABLE = True
except ImportError:
    PDFPLUMBER_AVAILABLE = False
    ocr_logger.warning("pdfplumber not available - native PDF text extraction disabled")

try:
    import pytesseract
    TESSERACT_AVAILABLE = True
except ImportError:
    TESSERACT_AVAILABLE = False
    ocr_logger.warning("pytesseract not available - OCR disabled")

try:
    from pdf2image import convert_from_path
    PDF2IMAGE_AVAILABLE = True
except ImportError:
    PDF2IMAGE_AVAILABLE = False
    ocr_logger.warning("pdf2image not available - PDF conversion disabled")


# -----------------------------------------------------------------------------
# Data Models
# -----------------------------------------------------------------------------
@dataclass
class ExtractedTransaction:
    """Represents a transaction extracted from OCR + LLM parsing."""
    ticker: str
    asset_name: Optional[str]
    trade_type: str  # 'purchase' or 'sale'
    trade_date: Optional[str]  # YYYY-MM-DD
    amount_low: Optional[float]
    amount_high: Optional[float]
    amount_midpoint: float
    owner: Optional[str]  # Self, Spouse, Joint, etc.
    confidence: float  # 0.0 to 1.0
    notification_date: Optional[str] = None  # YYYY-MM-DD - when disclosed
    is_options: bool = False
    option_type: Optional[str] = None  # 'call' or 'put'
    strike_price: Optional[float] = None
    expiration_date: Optional[str] = None
    contracts: Optional[int] = None
    shares: Optional[int] = None
    is_partial_sale: bool = False


# -----------------------------------------------------------------------------
# Amount Parsing
# -----------------------------------------------------------------------------
AMOUNT_RANGES = {
    "$1,001 - $15,000": (1001, 15000),
    "$15,001 - $50,000": (15001, 50000),
    "$50,001 - $100,000": (50001, 100000),
    "$100,001 - $250,000": (100001, 250000),
    "$250,001 - $500,000": (250001, 500000),
    "$500,001 - $1,000,000": (500001, 1000000),
    "$1,000,001 - $5,000,000": (1000001, 5000000),
    "$5,000,001 - $25,000,000": (5000001, 25000000),
    "$25,000,001 - $50,000,000": (25000001, 50000000),
}


def parse_amount_range(amount_str: str) -> tuple[float, float, float]:
    """
    Parse amount string to (low, high, midpoint).
    
    Uses "Aggressive Modeling" - returns midpoint for range estimates.
    """
    amount_str = amount_str.strip()
    
    # Check predefined ranges
    if amount_str in AMOUNT_RANGES:
        low, high = AMOUNT_RANGES[amount_str]
        return float(low), float(high), (low + high) / 2
    
    # Try to parse "$X - $Y" format
    match = re.match(r'\$?([\d,]+)\s*[-–]\s*\$?([\d,]+)', amount_str)
    if match:
        low = float(match.group(1).replace(',', ''))
        high = float(match.group(2).replace(',', ''))
        return low, high, (low + high) / 2
    
    # Single value
    match = re.match(r'\$?([\d,]+)', amount_str)
    if match:
        value = float(match.group(1).replace(',', ''))
        return value, value, value
    
    return 0.0, 0.0, 0.0


# -----------------------------------------------------------------------------
# PDF to Image Conversion
# -----------------------------------------------------------------------------
def pdf_to_images(pdf_path: Path, dpi: int = 300) -> list[Image.Image]:
    """
    Convert PDF pages to high-DPI images for OCR.
    
    Args:
        pdf_path: Path to PDF file
        dpi: Resolution for conversion (higher = better OCR, slower)
    
    Returns:
        List of PIL Image objects, one per page
    """
    if not PDF2IMAGE_AVAILABLE:
        ocr_logger.error("pdf2image not available - cannot convert PDF")
        return []
    
    if not pdf_path.exists():
        ocr_logger.error(f"PDF not found: {pdf_path}")
        return []
    
    try:
        images = convert_from_path(
            pdf_path,
            dpi=dpi,
            fmt='png',
            thread_count=2,  # Limit threads on constrained systems
        )
        ocr_logger.info(f"Converted {len(images)} pages from {pdf_path.name}")
        return images
    except Exception as e:
        ocr_logger.error(f"PDF conversion failed: {e}")
        return []


# -----------------------------------------------------------------------------
# Tesseract OCR
# -----------------------------------------------------------------------------
def extract_text_from_image(image: Image.Image) -> str:
    """Extract text from a single image using Tesseract."""
    if not TESSERACT_AVAILABLE:
        ocr_logger.error("pytesseract not available")
        return ""
    
    try:
        # Use page segmentation mode 6 (uniform block of text)
        # and OEM mode 3 (LSTM neural network)
        custom_config = r'--oem 3 --psm 6'
        text = pytesseract.image_to_string(image, config=custom_config)
        return text
    except Exception as e:
        ocr_logger.error(f"OCR extraction failed: {e}")
        return ""


def extract_text_with_pdfplumber(pdf_path: Path) -> str:
    """
    Extract text from a native PDF using pdfplumber.
    Works for digitally-generated PDFs (not scanned images).
    
    Args:
        pdf_path: Path to PDF file
    
    Returns:
        Concatenated text from all pages, or empty string if extraction fails
    """
    if not PDFPLUMBER_AVAILABLE:
        return ""
    
    try:
        all_text = []
        with pdfplumber.open(pdf_path) as pdf:
            for i, page in enumerate(pdf.pages):
                text = page.extract_text()
                if text:
                    all_text.append(text)
                    ocr_logger.debug(f"pdfplumber extracted {len(text)} chars from page {i+1}")
        
        if all_text:
            return "\n\n--- PAGE BREAK ---\n\n".join(all_text)
        return ""
    except Exception as e:
        ocr_logger.warning(f"pdfplumber extraction failed: {e}")
        return ""


def extract_text_with_ocr(pdf_path: Path, dpi: int = 300) -> str:
    """
    Extract text from PDF using Tesseract OCR.
    Used for scanned PDFs where text is in images.
    
    Args:
        pdf_path: Path to PDF file
        dpi: Resolution for image conversion
    
    Returns:
        Concatenated text from all pages
    """
    images = pdf_to_images(pdf_path, dpi)
    if not images:
        return ""
    
    all_text = []
    for i, image in enumerate(images):
        ocr_logger.debug(f"OCR processing page {i + 1}/{len(images)}")
        text = extract_text_from_image(image)
        all_text.append(text)
    
    return "\n\n--- PAGE BREAK ---\n\n".join(all_text)


def extract_text_from_pdf(pdf_path: Path, dpi: int = 300) -> str:
    """
    Extract text from PDF - tries pdfplumber first (for native PDFs),
    then falls back to Tesseract OCR (for scanned PDFs).
    
    Congressional disclosure PDFs are typically digitally generated,
    so pdfplumber usually works and is much faster than OCR.
    
    Args:
        pdf_path: Path to PDF file
        dpi: Resolution for OCR image conversion (if needed)
    
    Returns:
        Concatenated text from all pages
    """
    # First try pdfplumber for native PDF text extraction
    ocr_logger.info(f"Attempting native text extraction with pdfplumber...")
    text = extract_text_with_pdfplumber(pdf_path)
    
    if text and len(text.strip()) > 100:  # Need meaningful content
        ocr_logger.info(f"pdfplumber extracted {len(text)} characters successfully")
        return text
    
    # Fall back to OCR for scanned PDFs
    ocr_logger.info(f"pdfplumber found no/little text, falling back to Tesseract OCR...")
    text = extract_text_with_ocr(pdf_path, dpi)
    
    if text:
        ocr_logger.info(f"OCR extracted {len(text)} characters")
    else:
        ocr_logger.warning(f"Both pdfplumber and OCR failed to extract text")
    
    return text


# -----------------------------------------------------------------------------
# LLM Parsing with OpenRouter
# -----------------------------------------------------------------------------
EXTRACTION_PROMPT = """You are a financial disclosure parser for U.S. Congressional trading disclosures. Extract ALL stock/option transactions from the following OCR text.

The documents typically have a TABLE format with these columns:
- **ID**: (often empty)
- **Owner**: Who owns the asset
  - "SP" = Spouse
  - "JT" = Joint
  - "DC" = Dependent Child
  - "Self" or empty = Self (the member of Congress)
- **Asset**: Company name with ticker in parentheses, e.g., "Alphabet Inc. - Class A Common Stock (GOOGL) [ST]"
  - [ST] = Stock
  - [OP] = Options
  - [AB] = Asset-backed securities
  - The ticker is usually in parentheses like (AAPL), (MSFT), (AMZN)
- **Transaction Type**:
  - "P" = Purchase
  - "S" = Sale (full)
  - "S (partial)" = Sale (partial)
  - "E" = Exchange
- **Date**: Transaction date (MM/DD/YYYY format in source)
- **Notification Date**: Filing date (MM/DD/YYYY format in source)
- **Amount**: Dollar range like "$1,000,001 - $5,000,000"
- **Description**: Additional details like "Purchased 25,000 shares" or option details like "Purchased 20 call options with a strike price of $150 and an expiration date of 1/15/27"

For each transaction, extract:
1. **ticker**: The stock symbol from parentheses (e.g., GOOGL from "Alphabet Inc. (GOOGL)")
2. **asset_name**: Full name of the company/asset
3. **trade_type**: "purchase" (if P) or "sale" (if S or S (partial))
4. **trade_date**: Transaction date in YYYY-MM-DD format
5. **notification_date**: Filing/notification date in YYYY-MM-DD format
6. **amount**: The dollar range exactly as shown (e.g., "$1,000,001 - $5,000,000")
7. **owner**: Expanded form: "Spouse", "Self", "Joint", or "Dependent Child"
8. **is_options**: true if this is an options trade ([OP] or mentions "call options"/"put options"), false otherwise
9. **option_details**: If options, extract: strike_price, expiration_date, option_type (call/put), contracts
10. **shares**: Number of shares if mentioned in description
11. **is_partial_sale**: true if "S (partial)", false otherwise

Common ticker corrections:
- "Facebook" → META
- "Amazon" or "Amazon.com" → AMZN
- "Alphabet" or "Google" → GOOGL (Class A) or GOOG (Class C)
- "Microsoft" → MSFT
- "Apple" → AAPL
- "Nvidia" or "NVIDIA" → NVDA
- "Tesla" → TSLA
- "AllianceBernstein" → AB

Return ONLY valid JSON array. Extract ALL transactions from the document. If no transactions found, return [].

Example output for the data in the OCR:
[
  {{
    "ticker": "AB",
    "asset_name": "AllianceBernstein Holding L.P. Units",
    "trade_type": "purchase",
    "trade_date": "2026-01-16",
    "notification_date": "2026-01-16",
    "amount": "$1,000,001 - $5,000,000",
    "owner": "Spouse",
    "is_options": false,
    "shares": 25000,
    "is_partial_sale": false
  }},
  {{
    "ticker": "GOOGL",
    "asset_name": "Alphabet Inc. - Class A Common Stock",
    "trade_type": "purchase",
    "trade_date": "2025-12-30",
    "notification_date": "2025-12-30",
    "amount": "$250,001 - $500,000",
    "owner": "Spouse",
    "is_options": true,
    "option_details": {{
      "option_type": "call",
      "strike_price": 150,
      "expiration_date": "2027-01-15",
      "contracts": 20
    }},
    "is_partial_sale": false
  }}
]

OCR TEXT:
{ocr_text}

JSON OUTPUT:"""


async def parse_with_llm(ocr_text: str, config=None) -> list[dict]:
    """
    Send OCR text to OpenRouter LLM for structured extraction.
    
    Uses free models on OpenRouter to keep costs at $0.
    """
    if config is None:
        config = get_config()
    
    if not config.openrouter.validate():
        ocr_logger.error("OpenRouter API key not configured")
        return []
    
    # Truncate very long text to fit context window
    max_chars = 12000
    if len(ocr_text) > max_chars:
        ocr_logger.warning(f"Truncating OCR text from {len(ocr_text)} to {max_chars} chars")
        ocr_text = ocr_text[:max_chars] + "\n...[TRUNCATED]..."
    
    prompt = EXTRACTION_PROMPT.format(ocr_text=ocr_text)
    
    payload = {
        "model": config.openrouter.model,
        "messages": [
            {
                "role": "user",
                "content": prompt
            }
        ],
        "max_tokens": 8000,  # Increased for models with reasoning tokens
        "temperature": 0.1,  # Low temperature for consistent extraction
    }
    
    headers = {
        "Authorization": f"Bearer {config.openrouter.api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/congress-alpha",  # Required by OpenRouter
        "X-Title": "Congressional Alpha System",
    }
    
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(
                f"{config.openrouter.base_url}/chat/completions",
                json=payload,
                headers=headers
            )
            response.raise_for_status()
            
            data = response.json()
            
            # DEBUG: Log full response structure
            ocr_logger.debug(f"API response keys: {list(data.keys())}")
            
            # Check for API errors
            if 'error' in data:
                ocr_logger.error(f"OpenRouter API error: {data['error']}")
                return []
                
            if 'choices' not in data or not data['choices']:
                ocr_logger.error(f"Unexpected API response - no choices. Keys: {list(data.keys())}")
                ocr_logger.error(f"Full response: {json.dumps(data, indent=2)[:1000]}")
                return []
            
            # Get the content - handle potential variations
            choice = data['choices'][0]
            if 'message' not in choice:
                ocr_logger.error(f"No 'message' in choice. Choice keys: {list(choice.keys())}")
                ocr_logger.error(f"Choice content: {choice}")
                return []
            
            content = choice['message'].get('content', '')
            
            # Check for finish_reason
            finish_reason = choice.get('finish_reason', 'unknown')
            ocr_logger.debug(f"LLM finish_reason: {finish_reason}")
            
            if not content or not content.strip():
                ocr_logger.warning(f"LLM returned empty content. Finish reason: {finish_reason}")
                ocr_logger.warning(f"Full choice: {json.dumps(choice, indent=2)[:500]}")
                # Check if there's a refusal
                if choice['message'].get('refusal'):
                    ocr_logger.error(f"LLM refused: {choice['message']['refusal']}")
                return []
            
            # DEBUG: Log raw content for diagnosis
            ocr_logger.debug(f"Raw LLM response content (first 500 chars): {repr(content[:500])}")
            
            # Extract JSON from response
            transactions = _parse_json_response(content)
            ocr_logger.info(f"LLM extracted {len(transactions)} transactions")
            return transactions
            
    except httpx.HTTPError as e:
        ocr_logger.error(f"OpenRouter API error: {e}")
        return []
    except (KeyError, IndexError, json.JSONDecodeError) as e:
        ocr_logger.error(f"Error parsing LLM response: {e}")
        import traceback
        ocr_logger.error(traceback.format_exc())
        return []


def parse_with_llm_sync(ocr_text: str, config=None) -> list[dict]:
    """Synchronous wrapper for LLM parsing."""
    import asyncio
    return asyncio.run(parse_with_llm(ocr_text, config))


def _sanitize_json_content(content: str) -> str:
    """
    Sanitize LLM response content to fix common JSON formatting issues.
    
    Fixes:
    - Removes leading/trailing whitespace and newlines
    - Fixes keys with embedded newlines like '\n "ticker"'
    - Normalizes whitespace around colons and commas
    """
    # Strip leading/trailing whitespace
    content = content.strip()
    
    # Fix keys with embedded newlines: "\n \"key\"" -> "\"key\""
    # This handles cases where LLM outputs malformed JSON like:
    # {\n "ticker": "AAPL"}
    content = re.sub(r'\n\s*"', '"', content)
    
    # Fix multiple consecutive newlines/spaces in JSON structure
    content = re.sub(r'\n\s*\n', '\n', content)
    
    return content


def _normalize_transaction_keys(tx: dict) -> dict:
    """
    Normalize transaction dictionary keys to handle malformed LLM output.
    
    Handles cases where keys have extra whitespace, newlines, or quotes.
    """
    normalized = {}
    key_mapping = {
        'ticker': ['ticker', 'symbol', 'stock', 'ticker_symbol'],
        'asset_name': ['asset_name', 'asset', 'name', 'company', 'description'],
        'trade_type': ['trade_type', 'type', 'transaction_type', 'action'],
        'trade_date': ['trade_date', 'date', 'transaction_date'],
        'notification_date': ['notification_date', 'filing_date', 'disclosure_date', 'filed_date'],
        'amount': ['amount', 'value', 'amount_range', 'transaction_amount'],
        'owner': ['owner', 'holder', 'beneficial_owner'],
        'is_options': ['is_options', 'options', 'is_option'],
        'option_details': ['option_details', 'options_details'],
        'option_type': ['option_type'],
        'strike_price': ['strike_price', 'strike'],
        'expiration_date': ['expiration_date', 'expiration', 'expiry'],
        'contracts': ['contracts', 'num_contracts', 'contract_count'],
        'shares': ['shares', 'share_count', 'num_shares', 'quantity'],
        'is_partial_sale': ['is_partial_sale', 'partial_sale', 'partial'],
    }
    
    # Normalize keys: strip whitespace, lowercase, remove extra quotes
    cleaned_tx = {}
    for key, value in tx.items():
        if isinstance(key, str):
            # Clean the key: strip whitespace/newlines, remove surrounding quotes
            cleaned_key = key.strip().lower().strip('"\'')
            cleaned_tx[cleaned_key] = value
        else:
            cleaned_tx[key] = value
    
    # Map to standard keys
    for standard_key, aliases in key_mapping.items():
        for alias in aliases:
            if alias in cleaned_tx:
                normalized[standard_key] = cleaned_tx[alias]
                break
    
    # Include any other keys that weren't mapped
    for key, value in cleaned_tx.items():
        if key not in normalized:
            normalized[key] = value
    
    return normalized


def _recover_truncated_json_array(content: str) -> list[dict]:
    """
    Attempt to recover complete JSON objects from a truncated JSON array.
    
    When LLM output is truncated (finish_reason: length), the JSON array
    may be incomplete. This function extracts all complete objects that 
    can be parsed.
    """
    objects = []
    
    # Find all complete JSON objects using a balanced brace approach
    depth = 0
    start = None
    
    for i, char in enumerate(content):
        if char == '{':
            if depth == 0:
                start = i
            depth += 1
        elif char == '}':
            depth -= 1
            if depth == 0 and start is not None:
                obj_str = content[start:i+1]
                try:
                    obj = json.loads(obj_str)
                    objects.append(obj)
                except json.JSONDecodeError:
                    pass  # Skip malformed objects
                start = None
    
    return objects


def _parse_json_response(content: str) -> list[dict]:
    """Extract JSON array from LLM response."""
    parsed = None
    
    # DEBUG: Log what we're trying to parse
    ocr_logger.debug(f"_parse_json_response input (repr): {repr(content[:200])}")
    
    # Sanitize content first
    content = _sanitize_json_content(content)
    
    # First, strip code blocks if present
    code_block_match = re.search(r'```(?:json)?\s*([\s\S]*?)(?:```|$)', content)
    if code_block_match:
        content = code_block_match.group(1).strip()
        ocr_logger.debug(f"Extracted from code block: {repr(content[:100])}")
    
    ocr_logger.debug(f"Sanitized content (repr): {repr(content[:200])}")
    
    # Try multiple strategies to find JSON
    try:
        # 1. Direct parse
        parsed = json.loads(content)
        ocr_logger.debug("JSON parsed successfully with direct parse")
    except json.JSONDecodeError as e:
        ocr_logger.debug(f"Direct JSON parse failed: {e}")
        try:
            # 2. Find JSON array
            match = re.search(r'\[[\s\S]*\]', content)
            if match:
                ocr_logger.debug(f"Found JSON array match: {repr(match.group()[:100])}")
                # Sanitize the matched content too
                array_content = _sanitize_json_content(match.group())
                parsed = json.loads(array_content)
            else:
                # 3. Find JSON object (single)
                match = re.search(r'\{[\s\S]*\}', content)
                if match:
                    ocr_logger.debug(f"Found JSON object match: {repr(match.group()[:100])}")
                    # Sanitize the matched content too
                    obj_content = _sanitize_json_content(match.group())
                    parsed = json.loads(obj_content)
                else:
                    ocr_logger.debug("No JSON patterns found in content")
        except json.JSONDecodeError as e2:
            ocr_logger.debug(f"Secondary JSON parse failed: {e2}")
            # Try to recover truncated JSON array - find all complete objects
            parsed = _recover_truncated_json_array(content)
            if parsed:
                ocr_logger.debug(f"Recovered {len(parsed)} objects from truncated JSON")

    # Normalize result and transaction keys
    if isinstance(parsed, list):
        return [_normalize_transaction_keys(tx) for tx in parsed if isinstance(tx, dict)]
    if isinstance(parsed, dict):
        return [_normalize_transaction_keys(parsed)]
        
    ocr_logger.warning(f"Could not parse JSON from LLM response. Content preview: {repr(content[:150])}")
    return []


# -----------------------------------------------------------------------------
# Full Pipeline
# -----------------------------------------------------------------------------
def process_pdf(pdf_path: Path) -> list[ExtractedTransaction]:
    """
    Complete pipeline: PDF -> OCR -> LLM -> Structured Transactions.
    
    Args:
        pdf_path: Path to the PDF file
    
    Returns:
        List of extracted transactions
    """
    ocr_logger.info(f"Processing PDF: {pdf_path}")
    
    # Step 1: OCR extraction
    raw_text = extract_text_from_pdf(pdf_path)
    if not raw_text.strip():
        ocr_logger.warning("No text extracted from PDF")
        return []
    
    ocr_logger.debug(f"Extracted {len(raw_text)} characters of text")
    
    # Step 2: LLM parsing
    raw_transactions = parse_with_llm_sync(raw_text)
    
    # Step 3: Convert to structured format
    transactions = []
    for tx in raw_transactions:
        try:
            # Parse amount
            amount_str = tx.get('amount', '')
            low, high, midpoint = parse_amount_range(amount_str)
            
            # Normalize trade type
            trade_type = tx.get('trade_type', '').lower()
            if trade_type in ['buy', 'purchased', 'bought', 'p']:
                trade_type = 'purchase'
            elif trade_type in ['sell', 'sold', 's', 's (partial)']:
                trade_type = 'sale'
            
            # Normalize owner
            owner = tx.get('owner', 'Self')
            owner_map = {
                'sp': 'Spouse',
                'jt': 'Joint',
                'dc': 'Dependent Child',
                'self': 'Self',
                '': 'Self',
            }
            owner = owner_map.get(owner.lower().strip(), owner)
            
            # Extract option details if present
            is_options = tx.get('is_options', False)
            option_details = tx.get('option_details', {}) or {}
            option_type = option_details.get('option_type') if isinstance(option_details, dict) else None
            strike_price = option_details.get('strike_price') if isinstance(option_details, dict) else None
            expiration_date = option_details.get('expiration_date') if isinstance(option_details, dict) else None
            contracts = option_details.get('contracts') if isinstance(option_details, dict) else None
            
            # Parse shares count
            shares = tx.get('shares')
            if isinstance(shares, str):
                # Extract number from string like "25,000"
                shares_match = re.search(r'[\d,]+', shares.replace(',', ''))
                shares = int(shares_match.group().replace(',', '')) if shares_match else None
            elif isinstance(shares, (int, float)):
                shares = int(shares)
            else:
                shares = None
            
            transaction = ExtractedTransaction(
                ticker=tx.get('ticker', '').upper(),
                asset_name=tx.get('asset_name'),
                trade_type=trade_type,
                trade_date=tx.get('trade_date'),
                notification_date=tx.get('notification_date'),
                amount_low=low,
                amount_high=high,
                amount_midpoint=midpoint,
                owner=owner,
                confidence=0.85 if is_options else 0.9,  # Slightly lower confidence for options
                is_options=is_options,
                option_type=option_type,
                strike_price=float(strike_price) if strike_price else None,
                expiration_date=expiration_date,
                contracts=int(contracts) if contracts else None,
                shares=shares,
                is_partial_sale=tx.get('is_partial_sale', False),
            )
            
            # Validate required fields
            if transaction.ticker and transaction.trade_type:
                transactions.append(transaction)
            else:
                ocr_logger.debug(f"Skipping invalid transaction: {tx}")
                
        except Exception as e:
            ocr_logger.warning(f"Error processing transaction: {e}")
            continue
    
    ocr_logger.info(f"Processed {len(transactions)} valid transactions from {pdf_path.name}")
    return transactions


def process_all_pending_pdfs() -> list[tuple[Path, list[ExtractedTransaction]]]:
    """
    Process all PDFs in the raw_pdfs directory.
    
    - Skips PDFs that have already been analyzed (tracked in database)
    - Marks each PDF as analyzed after processing
    - Deletes processed PDFs to prevent accumulation
    
    Returns:
        List of (pdf_path, transactions) tuples
    """
    from modules.db_manager import DatabaseManager
    
    results = []
    db = DatabaseManager()
    
    if not RAW_PDFS_DIR.exists():
        ocr_logger.warning(f"PDF directory not found: {RAW_PDFS_DIR}")
        return results
    
    pdf_files = list(RAW_PDFS_DIR.glob("*.pdf"))
    ocr_logger.info(f"Found {len(pdf_files)} PDFs in directory")
    
    # Track which PDFs we process in this run (for cleanup)
    processed_this_run = []
    skipped_count = 0
    
    for pdf_path in pdf_files:
        filename = pdf_path.name
        
        # Check if this PDF was already analyzed
        if db.is_pdf_analyzed(filename):
            ocr_logger.debug(f"Skipping already analyzed PDF: {filename}")
            skipped_count += 1
            # Delete old PDFs that were already processed in previous runs
            try:
                pdf_path.unlink()
                ocr_logger.debug(f"Deleted previously analyzed PDF: {filename}")
            except Exception as e:
                ocr_logger.warning(f"Failed to delete old PDF {filename}: {e}")
            continue
        
        # Calculate file hash for tracking
        try:
            with open(pdf_path, 'rb') as f:
                file_hash = hashlib.md5(f.read()).hexdigest()
        except Exception:
            file_hash = None
        
        # Process the PDF
        transactions = process_pdf(pdf_path)
        
        if transactions:
            results.append((pdf_path, transactions))
        
        # Mark as analyzed in database (even if no transactions found)
        db.mark_pdf_analyzed(filename, file_hash, len(transactions))
        processed_this_run.append(pdf_path)
        ocr_logger.info(f"Analyzed and recorded: {filename} ({len(transactions)} transactions)")
    
    if skipped_count > 0:
        ocr_logger.info(f"Skipped {skipped_count} already-analyzed PDFs")
    
    # Delete PDFs that were processed in this run (cleanup)
    for pdf_path in processed_this_run:
        try:
            pdf_path.unlink()
            ocr_logger.debug(f"Deleted processed PDF: {pdf_path.name}")
        except Exception as e:
            ocr_logger.warning(f"Failed to delete processed PDF {pdf_path.name}: {e}")
    
    ocr_logger.info(f"Processed {len(results)} PDFs with transactions, deleted {len(processed_this_run)} files")
    
    return results


# -----------------------------------------------------------------------------
# Module test
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    import asyncio
    
    logging.basicConfig(level=logging.DEBUG)
    
    # Test with sample text matching actual Congressional disclosure format
    sample_text = """
    TRANSACTIONS
    
    ID  Owner  Asset                                      Transaction  Date        Notification  Amount            Cap.
                                                          Type                     Date                            Gains >
                                                                                                                   $200?
    
        SP     AllianceBernstein Holding L.P. Units       P            01/16/2026  01/16/2026    $1,000,001 -
               (AB) [AB]                                                                          $5,000,000
               FILING STATUS: New
               DESCRIPTION: Purchased 25,000 shares.
    
        SP     Alphabet Inc. - Class A Common             P            01/16/2026  01/16/2026    $500,001 -
               Stock (GOOGL) [ST]                                                                 $1,000,000
               FILING STATUS: New
               DESCRIPTION: Exercised 50 call options purchased 1/14/25 (5,000 shares) at a strike price of $150 with an expiration date of 1/16/26.
    
        SP     Alphabet Inc. - Class A Common             P            12/30/2025  12/30/2025    $250,001 -
               Stock (GOOGL) [OP]                                                                 $500,000
               FILING STATUS: New
               DESCRIPTION: Purchased 20 call options with a strike price of $150 and an expiration date of 1/15/27.
    
        SP     Alphabet Inc. - Class A Common             S (partial)  12/30/2025  12/30/2025    $1,000,001 -
               Stock (GOOGL) [ST]                                                                 $5,000,000
               FILING STATUS: New
               DESCRIPTION: Contribution of 7,704 shares held personally to Donor-Advised Fund.
    
        SP     Amazon.com, Inc. - Common Stock            P            12/30/2025  12/30/2025    $100,001 -
               (AMZN) [OP]                                                                        $250,000
               FILING STATUS: New
               DESCRIPTION: Purchased 20 call options with a strike price of $120 and an expiration date of 1/15/27.
    
        SP     Amazon.com, Inc. - Common Stock            S (partial)  12/24/2025  12/24/2025    $1,000,001 -
               (AMZN) [ST]                                                                        $5,000,000
    """
    
    print("Testing LLM parsing with Congressional disclosure format...")
    transactions = parse_with_llm_sync(sample_text)
    print(f"\nExtracted {len(transactions)} transactions:")
    for tx in transactions:
        print(f"  - {tx}")
        if tx.get('is_options'):
            print(f"    -> OPTIONS: {tx.get('option_details')}")
