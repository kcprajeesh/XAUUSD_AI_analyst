import gzip
import json
import traceback
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.ai.evidence import Timeframe
from app.data.ingestion import MarketDataPipeline, build_evidence, fetch_pages
from app.data.quota import RequestGate, RequestPolicy
from app.data.siftingio import SiftingError, SiftingIOClient
from app.data.storage import CandleStore

NOW = datetime(2026, 11, 18, 8, 30, tzinfo=UTC)
START = datetime(2026, 11, 18, 4, 0, tzinfo=UTC)


def response_transport(payload, *, zipped=False, status=200):
    body = json.dumps(payload).encode()
    if zipped:
        body = gzip.compress(body)
    seen = []
    def transport(request, timeout):
        seen.append((request, timeout))
        return status, {}, body
    return transport, seen


def bars(interval="1h", count=4, offset=0):
    data = []
    for index in range(count):
        opened = START + timedelta(hours=index + offset)
        data.append({"t": int(opened.timestamp() * 1000), "o": 2000.10 + index + offset,
            "h": 2001.50 + index + offset, "l": 1999.50 + index + offset,
            "c": 2001.00 + index + offset, "v": 1000 + index + offset})
    return {"meta": {"symbol": "XAUUSD", "interval": interval, "as_of": "2026-11-18T08:30:00Z", "next_cursor": None}, "data": data}


def client(monkeypatch, transport, **kwargs):
    monkeypatch.setenv("SIFTING_API_KEY", "synthetic-test-key")
    return SiftingIOClient(transport=transport, **kwargs)


def test_gzip_historical_decimal_and_auth_header(monkeypatch):
    transport, seen = response_transport(bars(), zipped=True)
    c = client(monkeypatch, transport)
    page = c.historical("1h", START, START + timedelta(hours=4), retrieved_at=NOW, limit=4)
    assert len(page.candles) == 4
    assert page.candles[0].open == Decimal("2000.1")
    assert page.candles[0].volume_type.value == "tick_count"
    assert seen[0][0].get_header("X-api-key") == "synthetic-test-key"
    assert seen[0][1] == (5.0, 15.0)


def test_invalid_tick_count_is_unavailable_and_flagged_while_ohlc_is_kept(monkeypatch):
    payload = bars(count=1)
    payload["data"][0]["v"] = 1.5
    page = client(monkeypatch, response_transport(payload)[0]).historical("1h", START,
        START + timedelta(hours=1), retrieved_at=NOW, limit=2)
    assert page.candles[0].volume is None
    assert "unusual_tick_count_range_unverified" in page.candles[0].quality_flags


def test_forming_candle_and_duplicates_are_explicit(monkeypatch):
    payload = bars(count=2)
    transport, _ = response_transport(payload)
    page = client(monkeypatch, transport).historical("1h", START, START + timedelta(hours=4),
        retrieved_at=START + timedelta(hours=1, minutes=30), limit=2)
    assert len(page.candles) == 2
    assert page.candles[0].opened_at < page.candles[1].opened_at
    assert [c.state.value for c in page.candles] == ["closed", "forming"]
    payload["data"].append(payload["data"][0].copy())
    transport, _ = response_transport(payload)
    with pytest.raises(SiftingError, match="duplicate_candles"):
        client(monkeypatch, transport).historical("1h", START, START + timedelta(hours=4), retrieved_at=NOW, limit=3)
    payload["data"].pop()
    payload["data"].reverse()
    transport, _ = response_transport(payload)
    with pytest.raises(SiftingError, match="provider_order_invalid"):
        client(monkeypatch, transport).historical("1h", START, START + timedelta(hours=4), retrieved_at=NOW, limit=2)
    transport, _ = response_transport(payload)
    page = client(monkeypatch, transport).historical("1h", START, START + timedelta(hours=4),
        retrieved_at=NOW, limit=2, order="desc")
    assert page.candles[0].opened_at > page.candles[1].opened_at


def test_missing_cursor_short_page_is_terminal_but_full_page_is_unverified(monkeypatch):
    payload = bars(count=1); payload["meta"].pop("next_cursor")
    transport, _ = response_transport(payload)
    short = client(monkeypatch, transport).historical("1h", START, START + timedelta(hours=4), retrieved_at=NOW, limit=2)
    assert short.pagination_verified and short.next_cursor is None
    payload = bars(count=2); payload["meta"].pop("next_cursor")
    transport, _ = response_transport(payload)
    full = client(monkeypatch, transport).historical("1h", START, START + timedelta(hours=4), retrieved_at=NOW, limit=2)
    assert not full.pagination_verified


def test_provider_response_cannot_exceed_requested_limit(monkeypatch):
    transport, _ = response_transport(bars(count=2))
    with pytest.raises(SiftingError, match="series_mismatch"):
        client(monkeypatch, transport).historical("1h", START, START + timedelta(hours=4), retrieved_at=NOW, limit=1)


def test_redirect_response_is_not_followed(monkeypatch):
    monkeypatch.setenv("SIFTING_API_KEY", "synthetic")
    calls = []
    class Response:
        status = 302
        headers = {}
        def read(self, _limit): return b"{}"
    class Connection:
        sock = None
        def __init__(self, *_args, **_kwargs): pass
        def request(self, *_args, **_kwargs): calls.append("request")
        def getresponse(self): return Response()
        def close(self): calls.append("close")
    monkeypatch.setattr("app.data.siftingio.http.client.HTTPSConnection", Connection)
    with pytest.raises(SiftingError, match="provider_error"):
        SiftingIOClient().historical("1h", START, START + timedelta(hours=4), retrieved_at=NOW)
    assert calls == ["request", "close"]


def test_no_key_invalid_ohlc_and_endpoint_rejection(monkeypatch):
    monkeypatch.delenv("SIFTING_API_KEY", raising=False)
    c = SiftingIOClient(transport=lambda *_: pytest.fail("network transport called"))
    with pytest.raises(SiftingError, match="not_configured"):
        c.historical("1h", START, NOW)
    payload = bars(); payload["data"][0]["l"] = 3000
    transport, _ = response_transport(payload)
    with pytest.raises(SiftingError, match="invalid_ohlc"):
        client(monkeypatch, transport).historical("1h", START, START + timedelta(hours=4), retrieved_at=NOW)
    with pytest.raises(SiftingError, match="configuration_security_rejection"):
        SiftingIOClient(endpoint="http://api.sifting.io")
    monkeypatch.setenv("SIFTING_API_KEY", "fake")
    with pytest.raises(ValueError, match="Unsupported interval"):
        client(monkeypatch, lambda *_: pytest.fail("4H must not be requested")).historical("4h", START, NOW)


def test_snapshot_and_malformed_json(monkeypatch):
    transport, seen = response_transport({"data": [{"s": "XAUUSD", "p": "2012.50", "b": "2012.40",
        "a": "2012.60", "B": "12", "A": "15", "t": int(NOW.timestamp() * 1000)}]})
    snap = client(monkeypatch, transport).snapshot(retrieved_at=NOW)
    assert snap.price == Decimal("2012.50") and snap.bid == Decimal("2012.40")
    assert snap.source_at == NOW and "api_key" not in seen[0][0].full_url
    transport, _ = response_transport({"bad": True})
    with pytest.raises(SiftingError, match="invalid_snapshot"):
        client(monkeypatch, transport).snapshot(retrieved_at=NOW)
    transport, _ = response_transport({}, zipped=False)
    def bad_json(*_): return (200, {}, b"not-json")
    with pytest.raises(SiftingError, match="invalid_json"):
        client(monkeypatch, bad_json).snapshot(retrieved_at=NOW)


def test_last_trade_validates_identity_price_size_and_utc_timestamp(monkeypatch):
    transport, seen = response_transport({"s": "XAUUSD", "p": "3738.62", "P": "14",
        "t": int(datetime(2026, 11, 19, 6, 21, 22, tzinfo=UTC).timestamp() * 1000)})
    trade = client(monkeypatch, transport).last_trade(retrieved_at=NOW)
    assert trade.provider_id == "siftingio" and trade.symbol == "XAUUSD"
    assert trade.price == Decimal("3738.62") and trade.size == Decimal("14")
    assert trade.source_at == datetime(2026, 11, 19, 6, 21, 22, tzinfo=UTC)
    assert seen[0][0].full_url.endswith("/v1/last/trade/commodities/XAUUSD")
    for invalid in ({"s": "XAGUSD", "p": "1", "P": "1", "t": 1},
                    {"s": "XAUUSD", "p": "NaN", "P": "1", "t": 1},
                    {"s": "XAUUSD", "p": "1", "P": "1", "t": "invalid"}):
        with pytest.raises(SiftingError, match="invalid_last_trade"):
            client(monkeypatch, response_transport(invalid)[0]).last_trade(retrieved_at=NOW)


def test_auth_quota_errors_and_duplicate_guard(monkeypatch):
    monkeypatch.setenv("SIFTING_API_KEY", "fake")
    for status, expected in ((401, "authentication_failure"), (402, "quota_exhausted"), (429, "rate_limited"), (500, "provider_error")):
        c = client(monkeypatch, lambda *_args, s=status: (s, {}, b"{}"))
        with pytest.raises(SiftingError, match=expected):
            c.historical("1h", START, NOW)
    gate = RequestGate(RequestPolicy(max_requests_per_minute=1))
    gate.begin("x", NOW)
    with pytest.raises(RuntimeError, match="duplicate_request"):
        gate.begin("x", NOW)
    gate.finish("x")
    with pytest.raises(RuntimeError, match="request_quota_exhausted"):
        gate.begin("y", NOW)
    gate = RequestGate(RequestPolicy(paused=True))
    with pytest.raises(RuntimeError, match="provider_paused"):
        gate.begin("paused", NOW)


def test_transport_timeout_and_dns_error_are_normalized(monkeypatch):
    monkeypatch.setenv("SIFTING_API_KEY", "fake")
    for error, expected in ((TimeoutError(), "timeout"), (OSError("dns"), "network_error")):
        c = SiftingIOClient(transport=lambda *_args, e=error: (_ for _ in ()).throw(e))
        with pytest.raises(SiftingError, match=expected):
            c.snapshot(retrieved_at=NOW)


@pytest.mark.parametrize("exception,category", [(TimeoutError, "timeout"), (OSError, "network_error")])
def test_transport_traceback_excludes_provider_details(monkeypatch, exception, category):
    sentinel = "sk-synthetic-provider-detail"
    def transport(*_):
        raise exception(sentinel)
    with pytest.raises(SiftingError) as error:
        client(monkeypatch, transport).snapshot(retrieved_at=NOW)
    assert error.value.category == category
    assert sentinel not in "".join(traceback.format_exception(error.value))


@pytest.mark.parametrize("source_timestamp", ["sk-synthetic-provider-timestamp", "0001-01-01T00:00:00+23:59"])
@pytest.mark.parametrize("kind", ["historical", "snapshot"])
def test_invalid_provider_timestamp_is_sanitized_and_normalized(monkeypatch, source_timestamp, kind):
    payload = bars() if kind == "historical" else {"data": [{"s": "XAUUSD", "p": "2012.50", "t": source_timestamp}]}
    if kind == "historical":
        payload["meta"]["as_of"] = source_timestamp
    c = client(monkeypatch, response_transport(payload)[0])
    with pytest.raises(SiftingError) as error:
        if kind == "historical":
            c.historical("1h", START, NOW, retrieved_at=NOW)
        else:
            c.snapshot(retrieved_at=NOW)
    assert error.value.category == ("invalid_response" if kind == "historical" else "invalid_snapshot")
    assert source_timestamp not in "".join(traceback.format_exception(error.value))


def test_store_revisions_and_h4_remains_unsupported_without_policy(monkeypatch, tmp_path):
    transport, _ = response_transport(bars())
    c = client(monkeypatch, transport)
    page = c.historical("1h", START, START + timedelta(hours=4), retrieved_at=NOW, limit=4)
    db = tmp_path / "market.sqlite"
    with CandleStore(db) as store:
        store.persist_sifting_page("1h", START, START + timedelta(hours=4), page)
        records = store.sifting_candles("1h")
        assert len(records) == 4
        assert store.coverage("siftingio:XAUUSD:1h:commodities-utc-v1").closed_count == 4
        # Identical source values from a later retrieval retain history without creating a revision.
        later = c.historical("1h", START, START + timedelta(hours=4), retrieved_at=NOW + timedelta(minutes=1), limit=4)
        store.persist_sifting_page("1h", START, START + timedelta(hours=4), later)
        assert len(store.sifting_history("1h", START)) == 2
        packet, suff = build_evidence(store, retrieved_at=NOW + timedelta(minutes=1),
            requested=(Timeframe.H1, Timeframe.H4))
        assert packet.timeframes[1].state.value == "unsupported"
        assert "unsupported_derivation" in {flag.value for flag in packet.timeframes[1].quality_flags}
        assert suff.statuses
        assert store.integrity_check() == (("ok",), ())
        changed_payload = bars()
        changed_payload["data"][0]["c"] = 2001.25
        changed_transport, _ = response_transport(changed_payload)
        changed = client(monkeypatch, changed_transport).historical("1h", START, START + timedelta(hours=4),
            retrieved_at=NOW + timedelta(minutes=2), limit=4)
        store.persist_sifting_page("1h", START, START + timedelta(hours=4), changed)
        revisions = store.connection.execute("SELECT COUNT(*) FROM historical_revisions").fetchone()[0]
        assert revisions == 1 and len(store.sifting_history("1h", START)) == 3


def test_cursor_pagination_and_snapshot_storage(monkeypatch, tmp_path):
    first = bars(count=2); first["meta"]["next_cursor"] = "cursor-2"
    second = bars(count=2, offset=2); second["meta"]["next_cursor"] = None
    responses = [json.dumps(first).encode(), json.dumps(second).encode(),
        json.dumps({"data": [{"s": "XAUUSD", "p": "2012.50", "b": "2012.40", "a": "2012.60",
            "t": int(NOW.timestamp() * 1000)}]}).encode()]
    requests = []
    def transport(request, _timeout):
        requests.append(request.full_url)
        return 200, {}, responses.pop(0)
    c = client(monkeypatch, transport)
    with CandleStore(tmp_path / "pages.sqlite") as store:
        ids = fetch_pages(c, store, "1h", START, START + timedelta(hours=4), limit=2, max_pages=2,
                          now=lambda: NOW)
        assert len(ids) == 2 and len(requests) == 2
        assert "cursor=cursor-2" in requests[1]
        snapshot = c.snapshot(retrieved_at=NOW)
        snapshot_ingestion = store.persist_sifting_snapshot(snapshot)
        assert store.latest_sifting_snapshot()["price"] == "2012.50"
        assert store.sifting_ingestion(snapshot_ingestion)["provenance"]["endpoint"] == "snapshot"
        assert store.connection.execute("SELECT COUNT(*) FROM ingestions").fetchone()[0] == 4


def test_empty_store_returns_insufficient_evidence_packet(tmp_path):
    with CandleStore(tmp_path / "empty.sqlite") as store:
        packet, suff = build_evidence(store, retrieved_at=NOW)
        assert all(frame.state.value != "available" for frame in packet.timeframes)
        assert next(frame for frame in packet.timeframes if frame.timeframe == Timeframe.H4).state.value == "unsupported"
        assert "missing_timeframes" in {status.value for status in suff.statuses}
        assert store.sifting_retrieval_status("1h") is None
        assert "retrieval_incomplete" in {flag.value for frame in packet.timeframes
                                           if frame.timeframe == Timeframe.H1 for flag in frame.quality_flags}
        assert packet.timeframes[1].state.value == "unsupported"


def test_unknown_retrieval_status_returns_no_trade_without_network(tmp_path):
    from types import SimpleNamespace
    with CandleStore(tmp_path / "unknown.sqlite") as store:
        pipeline = MarketDataPipeline(SimpleNamespace(), store)
        result = pipeline.analyze(now=NOW)
        assert result.data_status == "NO TRADE — INSUFFICIENT EVIDENCE"
        assert not result.sufficiency.sufficient
        assert result.evidence_packet.requested_timeframes == (Timeframe.D1, Timeframe.H1, Timeframe.M15)
        assert all(frame.timeframe != Timeframe.H4 for frame in result.evidence_packet.timeframes)


def test_insufficient_requested_depth_returns_no_trade(monkeypatch, tmp_path):
    transport, _ = response_transport(bars(count=220))
    provider = client(monkeypatch, transport)
    with CandleStore(tmp_path / "minimum-depth.sqlite") as store:
        fetch_pages(provider, store, "1h", START, START + timedelta(hours=219),
            limit=500, now=lambda: START + timedelta(hours=221))
        result = MarketDataPipeline(provider, store).analyze(now=START + timedelta(hours=221),
            requested_timeframes=(Timeframe.H1,), minimum_candles={Timeframe.H1: 300})
        assert result.data_status == "NO TRADE — INSUFFICIENT EVIDENCE"
        assert not result.sufficiency.sufficient


def test_personal_analysis_profile_keeps_h4_unavailable_when_explicitly_requested(tmp_path):
    from types import SimpleNamespace
    with CandleStore(tmp_path / "h4-disabled.sqlite") as store:
        result = MarketDataPipeline(SimpleNamespace(), store).analyze(
            now=NOW, requested_timeframes=(Timeframe.D1, Timeframe.H1, Timeframe.M15, Timeframe.H4))
        h4 = next(frame for frame in result.evidence_packet.timeframes if frame.timeframe == Timeframe.H4)
        assert h4.state.value == "unsupported"
        assert "NO TRADE" in result.data_status
        assert not result.sufficiency.sufficient


def test_complete_retrieval_can_supply_verified_price_evidence(monkeypatch, tmp_path):
    payload = bars(count=220)
    transport, _ = response_transport(payload)
    retrieval_time = START + timedelta(hours=221)
    with CandleStore(tmp_path / "complete.sqlite") as store:
        pipeline = MarketDataPipeline(client(monkeypatch, transport), store)
        fetch_pages(pipeline.client, store, "1h", START, START + timedelta(hours=219), limit=500,
                    now=lambda: retrieval_time)
        assert store.sifting_retrieval_status("1h") == "complete"
        packet, sufficiency = build_evidence(store, retrieved_at=retrieval_time, requested=(Timeframe.H1,),
            freshness_seconds={Timeframe.H1: 7200}, minimum_candles={Timeframe.H1: 200})
        assert sufficiency.sufficient
        assert any(item.quality.value == "verified" for item in packet.evidence)


def test_analysis_uses_only_latest_whole_retrieval_and_marks_its_missing_buckets(monkeypatch, tmp_path):
    with CandleStore(tmp_path / "whole-retrieval.sqlite") as store:
        complete = client(monkeypatch, response_transport(bars(count=4))[0])
        fetch_pages(complete, store, "1h", START, START + timedelta(hours=4), limit=4, now=lambda: NOW)
        partial = client(monkeypatch, response_transport(bars(count=1, offset=2))[0])
        fetch_pages(partial, store, "1h", START + timedelta(hours=1), START + timedelta(hours=4),
                    limit=4, now=lambda: NOW + timedelta(minutes=1))
        result, _ = build_evidence(store, retrieved_at=NOW + timedelta(minutes=1), requested=(Timeframe.H1,))
        timeframe = result.timeframes[0]
        assert len(timeframe.candles) == 1
        assert timeframe.candles[0].opened_at == START + timedelta(hours=2)
        assert timeframe.candles[0].retrieval_id == store.sifting_retrieval("1h")["retrieval_id"]
        assert timeframe.candles[0].revision_id.startswith("rev-")
        assert result.sources[0].retrieval_id == timeframe.candles[0].retrieval_id
        assert timeframe.missing_openings == (START + timedelta(hours=1), START + timedelta(hours=3))
        assert "missing_candles" in {flag.value for flag in timeframe.quality_flags}


def test_pipeline_persists_request_ledger_and_hard_stops(monkeypatch, tmp_path):
    monkeypatch.setenv("SIFTING_API_KEY", "synthetic")
    c = SiftingIOClient(transport=lambda *_: (503, {}, b"{}"))
    with CandleStore(tmp_path / "quota.sqlite") as store:
        pipeline = MarketDataPipeline(c, store, request_policy=RequestPolicy(max_requests_per_minute=1))
        with pytest.raises(SiftingError, match="provider_error"):
            pipeline.snapshot(now=NOW)
        assert len(store.sifting_request_times()) == 1
        with pytest.raises(SiftingError, match="request_quota_exhausted"):
            pipeline.snapshot(now=NOW + timedelta(seconds=1))
        assert len(store.sifting_request_times()) == 1


def test_failed_second_page_is_not_current_and_preserves_previous_complete_data(monkeypatch, tmp_path):
    monkeypatch.setenv("SIFTING_API_KEY", "synthetic")
    path = tmp_path / "batch.sqlite"
    with CandleStore(path) as store:
        first_client = client(monkeypatch, response_transport(bars(count=4))[0])
        pipeline = MarketDataPipeline(first_client, store)
        fetch_pages(pipeline.client, store, "1h", START, START + timedelta(hours=4), limit=4, max_pages=2, now=lambda: NOW)
        before = store.sifting_candles("1h")
        coverage_before = store.connection.execute("SELECT coverage_json FROM coverage WHERE series_id='siftingio:XAUUSD:1h:commodities-utc-v1'").fetchone()[0]
        first = bars(count=2); first["meta"]["next_cursor"] = "next"
        responses = [json.dumps(first).encode()]
        calls = []
        def fail_second(request, _timeout):
            calls.append(request.full_url)
            if len(calls) == 1:
                return 200, {}, responses.pop()
            raise TimeoutError()
        pipeline.client = client(monkeypatch, fail_second)
        pipeline.client.request_gate = RequestGate(on_request=store.log_sifting_request, on_outcome=store.finish_sifting_request)
        with pytest.raises(SiftingError, match="timeout"):
            fetch_pages(pipeline.client, store, "1h", START, START + timedelta(hours=4), limit=2, max_pages=2, now=lambda: NOW)
        assert store.sifting_candles("1h") == before
        assert store.connection.execute("SELECT coverage_json FROM coverage WHERE series_id='siftingio:XAUUSD:1h:commodities-utc-v1'").fetchone()[0] == coverage_before
        assert store.sifting_retrieval_status("1h") == "failed"
        result = pipeline.analyze(now=NOW + timedelta(hours=1), freshness_seconds={Timeframe.H1: 10**9})
        assert result.data_status == "NO TRADE — INSUFFICIENT EVIDENCE"
        assert not result.sufficiency.sufficient
        assert result.evidence_packet.timeframes[0].candles == ()
        assert all(item.quality.value != "verified" for item in result.evidence_packet.evidence)


@pytest.mark.parametrize("pages,category", [
    ([("a", 0), ("a", 2)], "pagination_cursor_repeated"),
    ([("a", 0), ("b", 2), ("a", 4)], "pagination_cursor_repeated"),
    ([("a", 0), (None, 0)], "pagination_overlap"),
    ([("a", 2), (None, 0)], "pagination_out_of_order"),
    ([("a", 0)], "page_limit_reached"),
])
def test_rejected_pagination_stays_out_of_current(monkeypatch, tmp_path, pages, category):
    class FakeClient:
        def __init__(self): self.index = 0
        def historical(self, *_args, **_kwargs):
            cursor, offset = pages[self.index]; self.index += 1
            payload = bars(count=2, offset=offset)
            from app.data.siftingio import Page
            transport, _ = response_transport(payload)
            page = client(monkeypatch, transport).historical("1h", START, START + timedelta(hours=10), retrieved_at=NOW + timedelta(days=1), limit=2)
            return page.model_copy(update={"next_cursor": cursor, "pagination_verified": True})
    with CandleStore(tmp_path / f"{category}.sqlite") as store:
        with pytest.raises(SiftingError, match=category):
            fetch_pages(FakeClient(), store, "1h", START, START + timedelta(hours=10), limit=2,
                        max_pages=1 if category == "page_limit_reached" else 4, now=lambda: NOW)
        assert store.sifting_candles("1h") == ()
        assert store.sifting_retrieval_status("1h") == "incomplete"


def test_empty_page_with_cursor_fails_closed(monkeypatch, tmp_path):
    class EmptyCursor:
        def historical(self, *_args, **_kwargs):
            payload = bars(count=1)
            transport, _ = response_transport(payload)
            page = client(monkeypatch, transport).historical("1h", START, START + timedelta(hours=4), retrieved_at=NOW, limit=2)
            return page.model_copy(update={"candles": (), "raw_count": 0, "next_cursor": "continued"})
    with CandleStore(tmp_path / "empty-cursor.sqlite") as store:
        with pytest.raises(SiftingError, match="empty_page_with_cursor"):
            fetch_pages(EmptyCursor(), store, "1h", START, START + timedelta(hours=4), limit=2, now=lambda: NOW)
        assert store.sifting_candles("1h") == ()
        assert store.sifting_retrieval_status("1h") == "incomplete"


def test_quality_warning_survives_to_evidence_and_blocks_verified_volume(monkeypatch, tmp_path):
    transport, _ = response_transport(bars(count=4))
    page = client(monkeypatch, transport).historical("1h", START, START + timedelta(hours=4), retrieved_at=NOW, limit=4)
    with CandleStore(tmp_path / "quality.sqlite") as store:
        store.persist_sifting_page("1h", START, START + timedelta(hours=4), page)
        packet, sufficiency = build_evidence(store, retrieved_at=NOW, requested=(Timeframe.H1,))
        candle = packet.timeframes[0].candles[-1]
        assert candle.volume_type.value == "tick_count"
        assert "unusual_tick_count_range_unverified" in {flag.value for flag in candle.quality_flags}
        assert any("tick-count range is unusual" in warning for warning in sufficiency.warnings)
        volume = next(item for item in packet.evidence if item.evidence_type.value == "volume")
        assert volume.volume_type.value == "tick_count" and volume.quality.value == "insufficient_quality"
        assert "spike" not in volume.description.lower()


@pytest.mark.parametrize("field,value", [
    ("provider_id", "other"), ("feed_id", "other"), ("instrument_id", "xau-usd:spot-other"),
    ("interval", "15m"), ("opened_at", "not-a-timestamp"),
    ("opened_at", "2026-11-18T10:00:00Z"), ("low", "3000"),
])
def test_sifting_persistence_revalidates_identity_range_and_candles(monkeypatch, tmp_path, field, value):
    transport, _ = response_transport(bars(count=4))
    page = client(monkeypatch, transport).historical("1h", START, START + timedelta(hours=4), retrieved_at=NOW, limit=4)
    raw = page.model_dump(mode="python")
    raw["candles"][0][field] = value
    class InvalidPage:
        def model_dump(self): return raw
    with CandleStore(tmp_path / f"bad-{field}.sqlite") as store:
        with pytest.raises(Exception):
            store.persist_sifting_page("1h", START, START + timedelta(hours=4), InvalidPage())
        assert store.sifting_candles("1h") == ()


def test_sifting_persistence_rollback_keeps_previous_current_rows(monkeypatch, tmp_path):
    transport, _ = response_transport(bars(count=4))
    page = client(monkeypatch, transport).historical("1h", START, START + timedelta(hours=4), retrieved_at=NOW, limit=4)
    with CandleStore(tmp_path / "rollback.sqlite") as store:
        store.persist_sifting_page("1h", START, START + timedelta(hours=4), page)
        before = store.sifting_candles("1h")
        store.connection.execute("CREATE TRIGGER fail_sifting BEFORE INSERT ON candle_records BEGIN SELECT RAISE(ABORT,'injected'); END")
        changed = tuple(c.model_copy(update={"close": c.close - Decimal('0.01'),
            "retrieved_at": NOW + timedelta(minutes=1)}) for c in page.candles)
        bad_page = page.model_copy(update={"candles": changed, "retrieved_at": NOW + timedelta(minutes=1)})
        with pytest.raises(Exception):
            store.persist_sifting_page("1h", START, START + timedelta(hours=4), bad_page)
        assert store.sifting_candles("1h") == before
        assert store.integrity_check() == (("ok",), ())


@pytest.mark.parametrize("status,outcome", [(200, "succeeded"), (401, "authentication_failure"),
    (402, "quota_exhausted"), (429, "rate_limited"), (500, "provider_error")])
def test_request_outcome_is_persisted(monkeypatch, tmp_path, status, outcome):
    monkeypatch.setenv("SIFTING_API_KEY", "synthetic")
    transport = (lambda *_: (status, {}, json.dumps(bars(count=1)).encode()))
    with CandleStore(tmp_path / f"outcome-{status}.sqlite") as store:
        pipeline = MarketDataPipeline(client(monkeypatch, transport), store)
        try:
            pipeline.client.historical("1h", START, START + timedelta(hours=4), retrieved_at=NOW, limit=1)
        except SiftingError:
            pass
        request = json.loads(store.connection.execute("SELECT request_json FROM ingestions WHERE series_id LIKE '%request-ledger%' AND json_extract(request_json,'$.event')='http_request'").fetchone()[0])
        assert request["outcome"] == outcome
        assert "api_key" not in request and "authorization" not in request


def test_invalid_response_outcome_is_persisted(monkeypatch, tmp_path):
    monkeypatch.setenv("SIFTING_API_KEY", "synthetic")
    with CandleStore(tmp_path / "invalid-response.sqlite") as store:
        pipeline = MarketDataPipeline(client(monkeypatch, lambda *_: (200, {}, b'{"wrong":true}')), store)
        with pytest.raises(SiftingError, match="invalid_response"):
            pipeline.client.historical("1h", START, START + timedelta(hours=4), retrieved_at=NOW)
        request = json.loads(store.connection.execute("SELECT request_json FROM ingestions WHERE series_id LIKE '%request-ledger%' AND json_extract(request_json,'$.event')='http_request'").fetchone()[0])
        assert request["outcome"] == "invalid_response"


@pytest.mark.parametrize("error,outcome", [(TimeoutError(), "timeout"), (OSError("offline"), "network_error"),
    (RuntimeError("unexpected"), "unexpected_error")])
def test_transport_failures_are_logged_and_gate_is_released(monkeypatch, tmp_path, error, outcome):
    monkeypatch.setenv("SIFTING_API_KEY", "synthetic")
    with CandleStore(tmp_path / f"transport-{outcome}.sqlite") as store:
        pipeline = MarketDataPipeline(client(monkeypatch, lambda *_: (_ for _ in ()).throw(error)), store)
        with pytest.raises((SiftingError, RuntimeError)):
            pipeline.client.historical("1h", START, START + timedelta(hours=4), retrieved_at=NOW, limit=1)
        request = json.loads(store.connection.execute("SELECT request_json FROM ingestions WHERE series_id LIKE '%request-ledger%' AND json_extract(request_json,'$.event')='http_request'").fetchone()[0])
        assert request["outcome"] == outcome
        gate = pipeline.client.request_gate
        assert not gate._active


@pytest.mark.parametrize("thresholds,minimum,expected", [
    (None, 200, False), ({}, 200, False),
    ({Timeframe.M15: 7200}, 200, False),
    ({Timeframe.H1: 1}, 200, False),
    ({Timeframe.H1: 7200}, 221, False),
    ({Timeframe.H1: 7200}, 220, True),
])
def test_closed_candle_readiness(monkeypatch, tmp_path, thresholds, minimum, expected):
    from app.ai.evidence import assess_sufficiency
    transport, _ = response_transport(bars(count=221))
    as_of = START + timedelta(hours=220, minutes=30)
    with CandleStore(tmp_path / "closed.sqlite") as store:
        fetch_pages(client(monkeypatch, transport), store, "1h", START,
                    START + timedelta(hours=220), now=lambda: as_of)
        packet, suff = build_evidence(store, retrieved_at=as_of, requested=(Timeframe.H1,),
            freshness_seconds=thresholds, minimum_candles={Timeframe.H1: minimum})
        assert len(store.sifting_retrieval("1h")["candles"]) == 221
        assert len(packet.timeframes[0].candles) == 220
        assert all(c.status.value == "closed" for c in packet.timeframes[0].candles)
        eligible = {c.candle_id for c in packet.timeframes[0].candles}
        assert all(set(e.candle_refs) <= eligible for e in packet.evidence)
        assert suff.sufficient is expected
        assert assess_sufficiency(packet).sufficient is expected


def test_pagination_does_not_poll_but_still_counts_quota(monkeypatch, tmp_path):
    first = bars(count=2); first["meta"]["next_cursor"] = "next"
    payloads = [first, bars(count=2, offset=2)]
    def transport(*_):
        return 200, {}, json.dumps(payloads.pop(0)).encode()
    provider = client(monkeypatch, transport, request_gate=RequestGate(RequestPolicy(
        minimum_poll_interval_seconds=60, max_requests_per_minute=2, max_concurrent_requests=1)))
    with CandleStore(tmp_path / "paced.sqlite") as store:
        assert len(fetch_pages(provider, store, "1h", START, START + timedelta(hours=4),
            limit=2, max_pages=2, now=lambda: NOW)) == 2
        with pytest.raises(SiftingError, match="minimum_poll_interval"):
            provider.historical("1h", START, NOW, retrieved_at=NOW)
        with pytest.raises(SiftingError, match="minimum_poll_interval"):
            provider.historical("1h", START, NOW, retrieved_at=NOW, cursor="next")


@pytest.mark.parametrize("kwargs", [
    {"interval": "4h"}, {"interval": "5m"}, {"max_pages": 0},
    {"max_pages": 101}, {"max_pages": True}, {"limit": 2001}, {"limit": 0},
    {"start": NOW, "end": START},
])
def test_refresh_request_rejects_unsupported_or_unbounded_values(kwargs):
    from app.data.ingestion import RefreshRequest
    values = dict(interval="1h", start=START, end=NOW)
    values.update(kwargs)
    with pytest.raises(ValueError):
        RefreshRequest(**values)


def test_supplied_cursor_has_no_polling_privilege(monkeypatch):
    transport, seen = response_transport(bars(count=1))
    provider = client(monkeypatch, transport, request_gate=RequestGate(RequestPolicy(
        minimum_poll_interval_seconds=60, max_requests_per_minute=5)))
    provider.historical("1h", START, NOW, retrieved_at=NOW)
    with pytest.raises(SiftingError, match="minimum_poll_interval"):
        provider.historical("1h", START, NOW, retrieved_at=NOW, cursor="user-cursor")
    assert len(seen) == 1


def test_pagination_admission_cannot_cross_gate_or_survive_close(monkeypatch):
    transport, seen = response_transport(bars(count=1))
    provider = client(monkeypatch, transport)
    foreign = RequestGate().pagination()
    with pytest.raises(SiftingError, match="pagination_not_authorized"):
        provider.historical("1h", START, NOW, retrieved_at=NOW, _pagination=foreign)
    own = provider.request_gate.pagination()
    own.close()
    with pytest.raises(SiftingError, match="pagination_not_authorized"):
        provider.historical("1h", START, NOW, retrieved_at=NOW, _pagination=own)
    assert not seen
