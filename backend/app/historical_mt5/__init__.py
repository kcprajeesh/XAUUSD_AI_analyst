"""Independent, in-memory historical analysis boundary for Alpari MT5 data."""

from app.historical_mt5.engine import build_historical_run
from app.historical_mt5.indicators import (
    AlignmentResult, AlignedValue, CandleReference, IndicatorObservation,
    IndicatorRun, IndicatorSpec, IndicatorStatus, IndicatorTrack,
    TimeframeIndicators, align_indicators, calculate_indicators,
)
from app.historical_mt5.models import CandleEligibility, HistoricalRun
from app.historical_mt5.structure import (
    FairValueGapState, HistoricalStructureRun, StructureDiagnostics,
    StructureEvent, TimeframeMarketStructure, analyze_market_structure,
)
from app.historical_mt5.confluence import (
    ConfluenceSnapshot, FVGView, SessionView, TimeframeSnapshot,
    build_confluence_snapshot,
)

__all__ = [
    "AlignmentResult", "AlignedValue", "CandleEligibility", "CandleReference",
    "HistoricalRun", "IndicatorObservation", "IndicatorRun", "IndicatorSpec",
    "IndicatorStatus", "IndicatorTrack", "TimeframeIndicators",
    "FairValueGapState", "HistoricalStructureRun", "StructureDiagnostics",
    "StructureEvent", "TimeframeMarketStructure", "align_indicators",
    "analyze_market_structure", "build_historical_run", "calculate_indicators",
    "ConfluenceSnapshot", "FVGView", "SessionView", "TimeframeSnapshot",
    "build_confluence_snapshot",
]
