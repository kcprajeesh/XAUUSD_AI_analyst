from datetime import UTC, datetime, timedelta
import hashlib

import pytest
from pydantic import ValidationError

from app.data.provider_contracts import (
    CandleEvidence, Gate, GateEvidence, PageEvidence, ProviderEligibilityV1,
    RetrievalCompletenessV1,
)

NOW = datetime(2026, 11, 18, 8, 30, tzinfo=UTC)
START = datetime(2026, 11, 18, 8, 0, tzinfo=UTC)
END = datetime(2026, 11, 18, 8, 15, tzinfo=UTC)
PROVIDER = "synthetic-provider"
INTERVALS = ("5m", "15m", "1h", "1d")


def eligibility(*, denied=(), missing=()):
    return ProviderEligibilityV1(
        provider_id=PROVIDER, product_id="synthetic-plan", supported_intervals=INTERVALS,
        evidence=tuple(GateEvidence(gate=gate, finding="denied" if gate in denied else "permitted",
            authoritative_reference="synthetic://terms/v1",
            reviewed_at=NOW) for gate in Gate if gate not in missing),
    )


def candle(at, digest="a"):
    return CandleEvidence(opened_at=at, content_digest=hashlib.sha256(digest.encode()).hexdigest())


def page(ordinal=0, *, request_cursor=None, next_cursor=None, candles=None, provider=PROVIDER,
         interval="5m", invalid_timestamps=0):
    return PageEvidence(ordinal=ordinal, request_cursor=request_cursor, next_cursor=next_cursor,
        provider_id=provider, instrument_id="XAUUSD", interval=interval,
        candles=tuple(candles if candles is not None else (candle(START),)),
        invalid_timestamps=invalid_timestamps)


def completeness(pages=None, *, interval="5m", retrieved_at=NOW, stale_after=600):
    return RetrievalCompletenessV1(provider_id=PROVIDER, instrument_id="XAUUSD", interval=interval,
        requested_start=START, requested_end=END, retrieved_at=retrieved_at,
        stale_after_seconds=stale_after, supported_intervals=INTERVALS,
        pages=tuple(pages if pages is not None else (page(),)))


def test_provider_eligibility_requires_every_affirmative_gate_with_authoritative_evidence():
    assert eligibility().eligible
    unverified = eligibility(missing={Gate.EXTERNAL_AI})
    assert not unverified.eligible
    assert "external_ai:unknown" in unverified.unavailable_reasons
    denied = eligibility(denied={Gate.RAW_RETENTION})
    assert not denied.eligible
    assert "raw_retention:denied" in denied.unavailable_reasons
    with pytest.raises(ValidationError, match="authoritative evidence"):
        GateEvidence(gate=Gate.RETRIEVAL, finding="permitted")


def test_retrieval_completeness_accepts_whole_cursor_chain_only():
    pages = (page(next_cursor="next"), page(1, request_cursor="next", candles=(candle(START + timedelta(minutes=5)),)))
    assert completeness(pages).status(now=NOW) == "page_chain_complete"
    assert completeness((page(next_cursor="missing"),)).status(now=NOW) == "incomplete"
    assert completeness((page(), page(1, request_cursor=None))).status(now=NOW) == "incomplete"


@pytest.mark.parametrize("case,expected", [
    ("duplicate", "duplicate"), ("conflict", "conflicting"), ("invalid_time", "incomplete"),
    ("stale", "stale"), ("identity", "incomplete"), ("unsupported", "unsupported"),
])
def test_synthetic_contract_failure_fixtures(case, expected):
    if case == "duplicate":
        pages = (page(candles=(candle(START), candle(START))),)
    elif case == "conflict":
        pages = (page(next_cursor="next", candles=(candle(START, "one"),)),
                 page(1, request_cursor="next", candles=(candle(START, "two"),)))
    elif case == "invalid_time":
        pages = (page(candles=(candle(datetime(2026, 11, 18, 8, 0)),)),)
    elif case == "stale":
        assert completeness(retrieved_at=NOW - timedelta(seconds=601)).status(now=NOW) == expected
        return
    elif case == "identity":
        pages = (page(provider="different-provider"),)
    else:
        assert completeness(interval="4h").status(now=NOW) == expected
        return
    assert completeness(pages).status(now=NOW) == expected
