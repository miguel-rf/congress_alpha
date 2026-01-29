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


def extract_text_from_pdf(pdf_path: Path, dpi: int = 300) -> str:
    """
    Full pipeline: PDF -> Images -> OCR Text.
    
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
        ocr_logger.debug(f"Processing page {i + 1}/{len(images)}")
        text = extract_text_from_image(image)
        all_text.append(text)
    
    return "\n\n--- PAGE BREAK ---\n\n".join(all_text)


# -----------------------------------------------------------------------------
# LLM Parsing with OpenRouter
# -----------------------------------------------------------------------------
EXTRACTION_PROMPT = """You are a financial disclosure parser. Extract stock transactions from the following OCR text.

For each transaction, extract:
1. **Ticker**: The stock symbol (e.g., AAPL, MSFT). If the ticker is unclear or handwritten (e.g., "Facebk", "Amzn"), infer the correct ticker from the asset name.
2. **Asset Name**: Full name of the company/asset
3. **Type**: Either "purchase" or "sale"
4. **Date**: Transaction date in YYYY-MM-DD format
5. **Amount**: The dollar range (e.g., "$15,001 - $50,000")
6. **Owner**: Who made the trade (Self, Spouse, Joint, Child)

Common ticker corrections:
- "Facebk" or "Facebook" → META
- "Amzn" or "Amazon" → AMZN
- "Alphabet" or "Google" → GOOGL
- "Microsoft" → MSFT
- "Apple" → AAPL
- "Nvidia" → NVDA
- "Tesla" → TSLA

Return ONLY valid JSON array. If no transactions found, return [].

Example output:
[
  {
    "ticker": "AAPL",
    "asset_name": "Apple Inc.",
    "trade_type": "purchase",
    "trade_date": "2024-01-15",
    "amount": "$15,001 - $50,000",
    "owner": "Self"
  }
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
        "max_tokens": 2000,
        "temperature": 0.1,  # Low temperature for consistent extraction
    }
    
    headers = {
        "Authorization": f"Bearer {config.openrouter.api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/congress-alpha",  # Required by OpenRouter
        "X-Title": "Congressional Alpha System",
    }
    
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                f"{config.openrouter.base_url}/chat/completions",
                json=payload,
                headers=headers
            )
            response.raise_for_status()
            
            data = response.json()
            
            # Check for API errors
            if 'error' in data:
                ocr_logger.error(f"OpenRouter API error: {data['error']}")
                return []
                
            if 'choices' not in data or not data['choices']:
                ocr_logger.error(f"Unexpected API response keys: {list(data.keys())}")
                if 'error' in data:
                     ocr_logger.error(f"Error detail: {data['error']}")
                return []
            
            content = data['choices'][0]['message']['content']
            
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
        'amount': ['amount', 'value', 'amount_range', 'transaction_amount'],
        'owner': ['owner', 'holder', 'beneficial_owner'],
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


def _parse_json_response(content: str) -> list[dict]:
    """Extract JSON array from LLM response."""
    parsed = None
    
    # DEBUG: Log what we're trying to parse
    ocr_logger.debug(f"_parse_json_response input (repr): {repr(content[:200])}")
    
    # Sanitize content first
    content = _sanitize_json_content(content)
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
                    # 4. Try code blocks
                    match = re.search(r'```(?:json)?\s*([\s\S]*?)```', content)
                    if match:
                        ocr_logger.debug(f"Found code block match: {repr(match.group(1)[:100])}")
                        # Sanitize the extracted content
                        code_content = _sanitize_json_content(match.group(1))
                        parsed = json.loads(code_content)
                    else:
                        ocr_logger.debug("No JSON patterns found in content")
        except json.JSONDecodeError as e2:
            ocr_logger.debug(f"Secondary JSON parse failed: {e2}")
            pass

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
            if trade_type in ['buy', 'purchased', 'bought']:
                trade_type = 'purchase'
            elif trade_type in ['sell', 'sold']:
                trade_type = 'sale'
            
            transaction = ExtractedTransaction(
                ticker=tx.get('ticker', '').upper(),
                asset_name=tx.get('asset_name'),
                trade_type=trade_type,
                trade_date=tx.get('trade_date'),
                amount_low=low,
                amount_high=high,
                amount_midpoint=midpoint,
                owner=tx.get('owner'),
                confidence=0.8,  # Default confidence for LLM extraction
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
    
    Returns:
        List of (pdf_path, transactions) tuples
    """
    results = []
    
    if not RAW_PDFS_DIR.exists():
        ocr_logger.warning(f"PDF directory not found: {RAW_PDFS_DIR}")
        return results
    
    pdf_files = list(RAW_PDFS_DIR.glob("*.pdf"))
    ocr_logger.info(f"Found {len(pdf_files)} PDFs to process")
    
    for pdf_path in pdf_files:
        transactions = process_pdf(pdf_path)
        if transactions:
            results.append((pdf_path, transactions))
    
    return results


# -----------------------------------------------------------------------------
# Module test
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    import asyncio
    
    logging.basicConfig(level=logging.DEBUG)
    
    # Test with a sample text
    sample_text = """
    PERIODIC TRANSACTION REPORT
    
    Filer: John Smith
    Filing Date: 01/15/2024
    
    TRANSACTIONS
    
    Asset: Apple Inc (AAPL)
    Type: Purchase
    Date: 01/10/2024
    Amount: $15,001 - $50,000
    Owner: Self
    
    Asset: Microsoft Corporation
    Type: Sale
    Date: 01/12/2024
    Amount: $50,001 - $100,000
    Owner: Spouse
    """
    
    print("Testing LLM parsing...")
    transactions = parse_with_llm_sync(sample_text)
    print(f"Extracted {len(transactions)} transactions:")
    for tx in transactions:
        print(f"  - {tx}")
