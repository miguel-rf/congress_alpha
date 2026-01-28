"""
Congressional Alpha System - FastAPI Application

Main FastAPI application with CORS, middleware, and router registration.
Run with: uvicorn api.main:app --reload --port 8000
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import signals, trades, portfolio, politicians, system, actions


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler for startup/shutdown."""
    # Startup
    print("🚀 Congressional Alpha API starting...")
    yield
    # Shutdown
    print("👋 Congressional Alpha API shutting down...")


app = FastAPI(
    title="Congressional Alpha API",
    description="REST API for Congressional stock trading platform",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS middleware for Next.js frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(signals.router, prefix="/api/signals", tags=["Signals"])
app.include_router(trades.router, prefix="/api/trades", tags=["Trades"])
app.include_router(portfolio.router, prefix="/api/portfolio", tags=["Portfolio"])
app.include_router(politicians.router, prefix="/api/politicians", tags=["Politicians"])
app.include_router(system.router, prefix="/api", tags=["System"])
app.include_router(actions.router, prefix="/api/actions", tags=["Actions"])


@app.get("/", tags=["Health"])
async def root():
    """Root endpoint - API health check."""
    return {
        "status": "healthy",
        "service": "Congressional Alpha API",
        "version": "1.0.0",
    }


@app.get("/health", tags=["Health"])
async def health_check():
    """Health check endpoint for monitoring."""
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api.main:app", host="0.0.0.0", port=8000, reload=True)
