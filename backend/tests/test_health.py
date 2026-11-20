import json
import os
from datetime import UTC, datetime
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

import pytest
from pydantic import ValidationError

from app.config import Settings, load_sifting_api_key
from app.main import HealthResponse, app, health


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = {key: value for key, value in os.environ.items() if not key.startswith("XAUUSD_")}
    env["XAUUSD_PORT"] = str(port)
    env.pop("SIFTING_API_KEY", None)
    env["HOME"] = str(tmp_path_factory.mktemp("backend-home"))
    process = subprocess.Popen([sys.executable, "-m", "app"], env=env)
    base = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if process.poll() is not None:
                pytest.fail("Backend exited before readiness")
            try:
                with urlopen(base + "/health", timeout=1) as response:
                    assert response.status == 200
                break
            except (URLError, TimeoutError):
                time.sleep(0.1)
        else:
            pytest.fail("Backend did not become ready")
        yield base
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def test_import_and_utc_health():
    before = datetime.now(UTC)
    response = health()
    assert response.status == "ok"
    assert response.timestamp.utcoffset().total_seconds() == 0
    assert before <= response.timestamp <= datetime.now(UTC)


def test_http_health_and_contract(server):
    with urlopen(server + "/health", timeout=2) as response:
        assert response.status == 200
        assert response.headers["content-type"] == "application/json"
        payload = json.load(response)
    model = HealthResponse.model_validate(payload)
    assert set(payload) == {"status", "service", "timestamp"}
    assert model.service == "XAUUSD AI Analyst"
    assert payload["timestamp"].endswith("Z")
    assert model.timestamp.utcoffset().total_seconds() == 0
    with pytest.raises(ValidationError):
        HealthResponse.model_validate({**payload, "timestamp": "2026-01-15T12:00:00"})
    with pytest.raises(ValidationError):
        HealthResponse.model_validate({**payload, "status": "invented"})


def test_market_data_status_is_provider_labeled_and_secret_free(server):
    with urlopen(server + "/api/v1/market-data/status", timeout=2) as response:
        payload = json.load(response)
    assert payload["provider"] == "siftingio"
    assert payload["source_label"] == "SiftingIO provider data; not broker bid/ask"
    assert payload["analysis_status"] == "NO TRADE — INSUFFICIENT EVIDENCE"
    assert [item["target_candles"] for item in payload["timeframes"]] == [200, 300, 300]
    assert payload["analysis_available"] is False
    assert payload["updated_at"] is None
    assert all(item["error_category"] == "startup_ingestion_disabled"
               and item["retrieval_status"] == "not_attempted"
               and item["actual_candles"] == 0 for item in payload["timeframes"])
    assert "SIFTING_API_KEY" not in json.dumps(payload)


@pytest.mark.parametrize("credential_in_environment", [False, True])
def test_startup_has_no_provider_or_storage_side_effects(tmp_path, credential_in_environment):
    secret = tmp_path / ".config/xauusd-ai-analyst/sifting.env"
    secret.parent.mkdir(parents=True)
    secret.write_text("SIFTING_API_KEY=file-secret-sentinel\n")
    secret.chmod(0o600)
    env = {key: value for key, value in os.environ.items()
           if not key.startswith("XAUUSD_") and key != "SIFTING_API_KEY"}
    env["HOME"] = str(tmp_path)
    if credential_in_environment:
        env["SIFTING_API_KEY"] = "environment-secret-sentinel"
    script = r'''
import asyncio
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
from unittest.mock import patch
from app import config
from app.data import ingestion, siftingio, storage

calls = []
def forbidden(*args, **kwargs):
    calls.append("forbidden startup side effect")
    raise AssertionError(calls[-1])

async def check():
    with patch.object(config, "load_sifting_api_key", forbidden), \
         patch.object(Path, "home", forbidden), \
         patch.object(siftingio, "SiftingIOClient", forbidden), \
         patch.object(ingestion, "MarketDataPipeline", forbidden), \
         patch.object(storage, "CandleStore", forbidden), \
         patch.object(sqlite3, "connect", forbidden), \
         patch.object(subprocess, "Popen", forbidden), \
         patch.object(socket.socket, "connect", forbidden), \
         patch.object(socket.socket, "connect_ex", forbidden):
        from app.main import app, health, read_analysis, market_data_status
        from fastapi import HTTPException
        from starlette.requests import Request
        request = Request({"type": "http", "app": app})
        async with app.router.lifespan_context(app):
            assert health().status == "ok"
            payload = market_data_status(request).model_dump(mode="json")
            assert payload["updated_at"] is None
            assert payload["analysis_available"] is False
            assert payload["sufficiency_statuses"] == []
            assert payload["analysis_status"] == "NO TRADE — INSUFFICIENT EVIDENCE"
            for frame in payload["timeframes"]:
                assert frame["retrieval_status"] == "not_attempted"
                assert frame["error_category"] == "startup_ingestion_disabled"
                assert frame["actual_candles"] == 0
                assert frame["retrieval_id"] is None
                assert frame["first_opened_at"] is frame["last_opened_at"] is None
                assert frame["missing_openings"] == []
            assert "sentinel" not in json.dumps(payload)
            assert not hasattr(app.state, "candle_store")
            try:
                read_analysis("unconfigured", request)
            except HTTPException as exc:
                assert (exc.status_code, exc.detail) == (503, "analysis_projection_unavailable")
            else:
                raise AssertionError("analysis unexpectedly available")
        assert calls == []
        assert os.environ.get("SIFTING_API_KEY") in (None, "environment-secret-sentinel")

asyncio.run(check())
'''
    result = subprocess.run([sys.executable, "-c", script], env=env,
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert "sentinel" not in result.stdout + result.stderr
    assert not (tmp_path / ".local").exists()


def test_openapi_contract(server):
    with urlopen(server + "/openapi.json", timeout=2) as response:
        schema = json.load(response)
    contract = json.loads((Path(__file__).parents[2] / "docs/health.schema.json").read_text())
    assert schema["components"]["schemas"]["HealthResponse"] == contract
    assert schema["paths"]["/health"]["get"]["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/HealthResponse"
    }
    assert set(schema["paths"]) == {"/health", "/api/v1/analysis/{analysis_id}", "/api/v1/market-data/status"}
    assert schema["paths"]["/api/v1/analysis/{analysis_id}"]["get"]["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/AnalysisProjection"
    }
    assert set(app.openapi()["paths"]) == {"/health", "/api/v1/analysis/{analysis_id}", "/api/v1/market-data/status"}


def test_no_execution_endpoint(server):
    with pytest.raises(HTTPError) as error:
        urlopen(server + "/execute", timeout=2)
    assert error.value.code == 404


def test_environment_defaults(monkeypatch):
    for key in list(os.environ):
        if key.startswith("XAUUSD_"):
            monkeypatch.delenv(key)
    assert Settings.from_environment() == Settings(host="127.0.0.1", port=8000)
    monkeypatch.setenv("XAUUSD_PORT", "8123")
    assert Settings.from_environment().port == 8123


def test_sifting_secret_file_loading_is_process_only_and_private(tmp_path, monkeypatch):
    path = tmp_path / "sifting.env"
    path.write_text("OTHER=value\nSIFTING_API_KEY=secret-sentinel\n")
    path.chmod(0o600)
    monkeypatch.delenv("SIFTING_API_KEY", raising=False)
    assert load_sifting_api_key(path)
    assert os.environ["SIFTING_API_KEY"] == "secret-sentinel"
    monkeypatch.setenv("SIFTING_API_KEY", "process-value")
    assert load_sifting_api_key(path)
    assert os.environ["SIFTING_API_KEY"] == "process-value"


def test_sifting_secret_file_rejects_broad_permissions_without_echo(tmp_path, monkeypatch):
    path = tmp_path / "sifting.env"
    path.write_text("SIFTING_API_KEY=secret-sentinel\n")
    path.chmod(0o644)
    monkeypatch.delenv("SIFTING_API_KEY", raising=False)
    with pytest.raises(ValueError) as error:
        load_sifting_api_key(path)
    assert "secret-sentinel" not in str(error.value)


@pytest.mark.parametrize("key,value", [
    ("XAUUSD_HOST", "0.0.0.0"), ("XAUUSD_HOST", "localhost"),
    ("XAUUSD_PORT", "bad"), ("XAUUSD_PORT", "0"),
    ("XAUUSD_PORT", "65536"), ("XAUUSD_API_KEY", "placeholder"),
])
def test_invalid_environment_fails_closed(monkeypatch, key, value):
    monkeypatch.setenv(key, value)
    with pytest.raises(ValidationError):
        Settings.from_environment()


def test_validated_native_dependencies_and_sqlite():
    import sqlite3
    import numpy as np
    import pandas as pd

    assert np.mean([1.0, 2.0, 3.0]) == 2.0
    assert pd.Series([1.0, 2.0, 3.0]).rolling(2).mean().iloc[-1] == 2.5
    with sqlite3.connect(":memory:") as connection:
        assert connection.execute("select 1").fetchone() == (1,)
