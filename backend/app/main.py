from datetime import UTC, datetime
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from pydantic import AwareDatetime, BaseModel, ConfigDict

from app.analysis.projection import AnalysisProjection, ProjectionError, ProjectionNotFound
from app.config import Settings

settings = Settings.from_environment()
TARGETS = {"1d": 200, "1h": 300, "15m": 300}


class TimeframeDataStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")
    timeframe: Literal["Daily", "1H", "15M"]
    interval: Literal["1d", "1h", "15m"]
    target_candles: int
    actual_candles: int
    retrieval_id: str | None = None
    retrieval_status: str
    first_opened_at: AwareDatetime | None = None
    last_opened_at: AwareDatetime | None = None
    missing_openings: tuple[AwareDatetime, ...] = ()
    error_category: str | None = None


class MarketDataStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: Literal["siftingio"] = "siftingio"
    source_label: Literal["SiftingIO provider data; not broker bid/ask"] = "SiftingIO provider data; not broker bid/ask"
    updated_at: AwareDatetime | None = None
    analysis_available: bool = False
    analysis_status: str = "NO TRADE — INSUFFICIENT EVIDENCE"
    sufficiency_statuses: tuple[str, ...] = ()
    timeframes: tuple[TimeframeDataStatus, ...]


def _initial_market_status() -> MarketDataStatus:
    return MarketDataStatus(timeframes=tuple(TimeframeDataStatus(
        timeframe={"1d": "Daily", "1h": "1H", "15m": "15M"}[interval], interval=interval,
        target_candles=count, actual_candles=0, retrieval_status="not_attempted",
        error_category="startup_ingestion_disabled") for interval, count in TARGETS.items()))


app = FastAPI(title="XAUUSD AI Analyst", version="0.1.0")
app.state.analysis_projection = None
app.state.market_data_status = _initial_market_status()


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["ok"] = "ok"
    service: Literal["XAUUSD AI Analyst"] = "XAUUSD AI Analyst"
    timestamp: AwareDatetime


@app.get("/health", response_model=HealthResponse, tags=["health"])
def health() -> HealthResponse:
    return HealthResponse(timestamp=datetime.now(UTC))


@app.get("/api/v1/analysis/{analysis_id}", response_model=AnalysisProjection, tags=["analysis"])
def read_analysis(analysis_id: str, request: Request) -> AnalysisProjection:
    """Read a single immutable analysis identity; no current-head or write operation exists."""
    projection = request.app.state.analysis_projection
    if projection is None:
        raise HTTPException(status_code=503, detail="analysis_projection_unavailable")
    try:
        return projection(analysis_id)
    except ProjectionNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ProjectionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/v1/market-data/status", response_model=MarketDataStatus, tags=["market data"])
def market_data_status(request: Request) -> MarketDataStatus:
    """Read the unavailable market state without provider or storage access."""
    return request.app.state.market_data_status
