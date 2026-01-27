"""
Politicians API Routes

Endpoints for managing the politician whitelist.
"""
from __future__ import annotations

import json
from pathlib import Path
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from config.settings import CONFIG_DIR

router = APIRouter()

WHITELIST_PATH = CONFIG_DIR / "whitelist.json"


class PoliticianResponse(BaseModel):
    """Politician response model."""
    name: str
    chamber: str
    notes: str


class PoliticianCreate(BaseModel):
    """Politician creation model."""
    name: str
    chamber: str  # "house" or "senate"
    notes: str = ""


def _load_whitelist() -> dict:
    """Load whitelist from JSON file."""
    if not WHITELIST_PATH.exists():
        return {"politicians": []}
    
    with open(WHITELIST_PATH, "r") as f:
        return json.load(f)


def _save_whitelist(data: dict) -> None:
    """Save whitelist to JSON file."""
    with open(WHITELIST_PATH, "w") as f:
        json.dump(data, f, indent=4)


@router.get("", response_model=list[PoliticianResponse])
async def list_politicians():
    """
    List all politicians on the whitelist.
    
    Returns list of tracked politicians with their chamber and notes.
    """
    data = _load_whitelist()
    return [
        PoliticianResponse(
            name=p["name"],
            chamber=p.get("chamber", "unknown"),
            notes=p.get("notes", ""),
        )
        for p in data.get("politicians", [])
    ]


@router.get("/count")
async def get_politician_count():
    """Get count of politicians on whitelist."""
    data = _load_whitelist()
    politicians = data.get("politicians", [])
    
    house_count = sum(1 for p in politicians if p.get("chamber") == "house")
    senate_count = sum(1 for p in politicians if p.get("chamber") == "senate")
    
    return {
        "total": len(politicians),
        "house": house_count,
        "senate": senate_count,
    }


@router.post("", response_model=PoliticianResponse)
async def add_politician(politician: PoliticianCreate):
    """
    Add a politician to the whitelist.
    
    - **name**: Politician's full name (must match disclosure filings)
    - **chamber**: Either "house" or "senate"
    - **notes**: Optional notes about the politician
    """
    if politician.chamber not in ("house", "senate"):
        raise HTTPException(
            status_code=400,
            detail="Chamber must be 'house' or 'senate'"
        )
    
    data = _load_whitelist()
    politicians = data.get("politicians", [])
    
    # Check for duplicates
    for p in politicians:
        if p["name"].lower() == politician.name.lower():
            raise HTTPException(
                status_code=409,
                detail=f"Politician '{politician.name}' already exists"
            )
    
    # Add new politician
    new_politician = {
        "name": politician.name,
        "chamber": politician.chamber,
        "notes": politician.notes,
    }
    politicians.append(new_politician)
    data["politicians"] = politicians
    
    _save_whitelist(data)
    
    return PoliticianResponse(
        name=politician.name,
        chamber=politician.chamber,
        notes=politician.notes,
    )


@router.delete("/{name}")
async def remove_politician(name: str):
    """
    Remove a politician from the whitelist.
    
    - **name**: Politician's full name to remove
    """
    data = _load_whitelist()
    politicians = data.get("politicians", [])
    
    # Find and remove politician
    original_count = len(politicians)
    politicians = [p for p in politicians if p["name"].lower() != name.lower()]
    
    if len(politicians) == original_count:
        raise HTTPException(
            status_code=404,
            detail=f"Politician '{name}' not found"
        )
    
    data["politicians"] = politicians
    _save_whitelist(data)
    
    return {"status": "success", "message": f"Removed '{name}' from whitelist"}


@router.get("/{name}", response_model=PoliticianResponse)
async def get_politician(name: str):
    """Get a specific politician by name."""
    data = _load_whitelist()
    
    for p in data.get("politicians", []):
        if p["name"].lower() == name.lower():
            return PoliticianResponse(
                name=p["name"],
                chamber=p.get("chamber", "unknown"),
                notes=p.get("notes", ""),
            )
    
    raise HTTPException(status_code=404, detail=f"Politician '{name}' not found")
