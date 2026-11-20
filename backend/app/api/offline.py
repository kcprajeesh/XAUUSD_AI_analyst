"""Dormant offline API factory. Opt in with XAU_OFFLINE_ARCHIVE=/path/to/*.synthetic.sqlite3.

Run: python -m uvicorn app.api.offline:create_app --factory --host 127.0.0.1 --port 8000
No route generates fixtures, ingests candles, invokes AI, or creates a database.
"""
from contextlib import closing
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import sqlite3
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import AwareDatetime, BaseModel, ConfigDict

from app.analysis.offline import require_resolved_cleanup
from app.analysis.projection import AnalysisProjection, ProjectionError, ProjectionNotFound, project_analysis
from app.canonical import CanonicalLimits
from app.data.archive_prototype import APPLICATION_ID, SCHEMA_VERSION
from app.data.evidence_contracts import MVP_TIMEFRAMES
from app.data.siftingio import SiftingError
from app.main import HealthResponse, health


class OfflineMarketStatus(BaseModel):
    model_config = ConfigDict(extra='forbid')
    environment: Literal['synthetic_archive'] = 'synthetic_archive'
    source_label: Literal['SYNTHETIC FIXTURE — NOT LIVE MARKET DATA'] = 'SYNTHETIC FIXTURE — NOT LIVE MARKET DATA'
    analysis_available: bool = False
    analysis_id: str | None = None
    updated_at: AwareDatetime | None = None
    freshness_status: Literal['fresh','unavailable'] = 'unavailable'
    valid_until: AwareDatetime | None = None
    error_category: str | None = None
    timeframe_availability: dict[str,str] = {'1D':'unavailable','1H':'unavailable','15M':'unavailable','4H':'unsupported'}


class OfflineProjectionSource:
    def __init__(self, path, *, clock=lambda:datetime.now(UTC)):
        self.path = Path(path).absolute()
        if self.path.suffixes[-2:] != ['.synthetic','.sqlite3']:
            raise ValueError('Offline source must be a synthetic archive')
        self.clock = clock

    def read(self, identity=None):
        require_resolved_cleanup()
        try:
            with closing(sqlite3.connect(self.path.as_uri()+'?mode=ro',uri=True)) as connection:
                connection.execute('PRAGMA query_only=ON')
                if (connection.execute('PRAGMA application_id').fetchone()[0] != APPLICATION_ID
                        or connection.execute('PRAGMA user_version').fetchone()[0] != SCHEMA_VERSION):
                    raise ProjectionError('offline_archive_schema_mismatch')
                metadata = dict(connection.execute('SELECT key,value FROM archive_metadata'))
                if (metadata.get('kind') != 'synthetic-only'
                        or tuple(json.loads(metadata.get('required_timeframes','[]'))) != MVP_TIMEFRAMES):
                    raise ProjectionError('offline_archive_policy_mismatch')
                view = project_analysis(connection,identity,limits=CanonicalLimits(8_000_000,1000,1000,1000,8_000_000),
                    max_payload_bytes=8_000_000,freshness_at=self.clock())
                self._require_current_candles(metadata, view)
                return view
        except sqlite3.Error:
            raise ProjectionError('offline_archive_unavailable') from None
        except (ValueError,TypeError,KeyError) as error:
            if isinstance(error,ProjectionError):
                raise
            raise ProjectionError('offline_archive_invalid') from None


    @staticmethod
    def _require_current_candles(metadata, view):
        path = Path(metadata['candle_store_path'])
        if not path.is_absolute() or path.suffixes[-2:] != ['.synthetic','.sqlite3']:
            raise ProjectionError('offline_candle_source_invalid')
        with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as connection:
            connection.execute('PRAGMA query_only=ON')
            connection.execute('BEGIN')
            if connection.execute('PRAGMA user_version').fetchone()[0] != 1:
                raise ProjectionError('offline_candle_schema_mismatch')
            latest = {}
            for row in connection.execute("SELECT request_json FROM ingestions WHERE "
                    "series_id='siftingio:XAUUSD:request-ledger:commodities-v1' ORDER BY ingestion_id DESC"):
                value = json.loads(row[0])
                if value.get('event') == 'retrieval' and value.get('interval') in MVP_TIMEFRAMES:
                    latest.setdefault(value['interval'],value)
                    if len(latest) == len(MVP_TIMEFRAMES):
                        break
            if (set(latest) != set(MVP_TIMEFRAMES)
                    or any(value.get('status') != 'complete' for value in latest.values())
                    or {value.get('retrieval_id') for value in latest.values()} != set(view.retrieval_completeness)):
                raise ProjectionError('current_retrieval_not_eligible')
            for value in latest.values():
                rows = connection.execute("SELECT provenance_json FROM ingestions WHERE "
                    "series_id LIKE 'siftingio:%:commodities-utc-v1' AND json_extract(request_json,'$.retrieval_id')=?",
                    (value['retrieval_id'],)).fetchall()
                if not rows or any(json.loads(row[0]).get('input_kind') != 'synthetic' for row in rows):
                    raise ProjectionError('offline_candle_source_invalid')


def create_app(archive_path=None, *, clock=lambda:datetime.now(UTC)):
    """Build a dormant app; source construction validates only the path, never opens it."""
    path = archive_path if archive_path is not None else os.environ.get('XAU_OFFLINE_ARCHIVE')
    source = OfflineProjectionSource(path,clock=clock) if path else None
    app = FastAPI(title='XAUUSD offline synthetic MVP',version='0.1.0')
    app.add_api_route('/health',health,response_model=HealthResponse,methods=['GET'])

    @app.get('/api/v1/analysis/{analysis_id}',response_model=AnalysisProjection)
    def read_analysis(analysis_id: str):
        if source is None:
            raise HTTPException(503,'analysis_projection_unavailable')
        try:
            return source.read(analysis_id)
        except ProjectionNotFound:
            raise HTTPException(404,'analysis_not_found') from None
        except SiftingError:
            raise HTTPException(503,'cleanup_unresolved') from None
        except ProjectionError as error:
            raise HTTPException(409,str(error)) from None

    @app.get('/api/v1/market-data/status',response_model=OfflineMarketStatus)
    def status():
        if source is None:
            return OfflineMarketStatus(error_category='offline_source_not_configured')
        try:
            view = source.read()
            return OfflineMarketStatus(analysis_available=True,analysis_id=view.analysis_id,
                updated_at=view.market_data_timestamp,freshness_status='fresh',valid_until=view.valid_until,
                timeframe_availability=view.timeframe_availability)
        except (ProjectionError,SiftingError) as error:
            return OfflineMarketStatus(error_category=str(error))
    return app
