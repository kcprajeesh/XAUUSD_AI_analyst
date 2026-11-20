"""Synthetic freshness/lookback scenarios; numerical limits are test-only evidence."""
from datetime import UTC, datetime, timedelta

import pytest

from app.data.freshness import (AgeLimit, Completeness, FreshnessPolicyV1, MarketCalendarState,
    RetrievalCandidate, SourcePermission, evaluate_freshness)


NOW = datetime(2026, 11, 18, 12, tzinfo=UTC)
FIXTURE = "synthetic://test-policy-threshold"


def policy(*, fallback=False, configured=True):
    age = (("1h", AgeLimit(7200, FIXTURE)),) if configured else ()
    publication_delay = (("1h", AgeLimit(600, FIXTURE)),) if configured else ()
    retrieval_delay = (("1h", AgeLimit(120, FIXTURE)),) if configured else ()
    lookback = (("1h", AgeLimit(86400, FIXTURE)),) if fallback else ()
    return FreshnessPolicyV1("fixture-policy-v1", age, lookback, publication_delay, retrieval_delay, fallback)


def candidate(retrieval="new", *, age=60, publication_delay=5, retrieval_delay=30,
              current=True, completeness=Completeness.VERIFIED,
              permission=SourcePermission.ELIGIBLE, digest="a" * 64, invalidated=False):
    event_at = NOW - timedelta(seconds=age)
    published = event_at + timedelta(seconds=publication_delay)
    completed = published + timedelta(seconds=retrieval_delay)
    return RetrievalCandidate(retrieval, "1h", "synthetic", event_at, published,
        completed, completeness, permission, current, digest, invalidated)


def evaluate(p, candidates, *, calendar=MarketCalendarState.OPEN, calendar_ref=None):
    return evaluate_freshness(p, tuple(candidates), timeframe="1h", as_of=NOW,
        calendar_state=calendar, calendar_evidence_reference=calendar_ref)


def test_missing_thresholds_never_become_fresh_by_default():
    assert evaluate(policy(configured=False), [candidate()]).reason == "freshness_threshold_unconfigured"
    with pytest.raises(ValueError, match="positive values"):
        AgeLimit(0, FIXTURE)


def test_event_age_and_publication_delay_are_evaluated_separately():
    assert evaluate(policy(), [candidate(age=7201)]).reason == "market_data_stale"
    assert evaluate(policy(), [candidate(age=1000, publication_delay=601)]).reason == "provider_publication_delay_exceeded"
    assert evaluate(policy(), [candidate(age=1000, retrieval_delay=121)]).reason == "retrieval_completion_delay_exceeded"
    decision = evaluate(policy(), [candidate(age=90, publication_delay=40, retrieval_delay=30)])
    assert (decision.state, decision.selected_retrieval_id, decision.event_age_seconds,
            decision.publication_delay_seconds, decision.retrieval_delay_seconds) == ("eligible", "new", 90, 40, 30)


def test_incomplete_denied_and_unknown_sources_are_unavailable():
    assert evaluate(policy(), [candidate(completeness=Completeness.INCOMPLETE)]).state == "unavailable"
    assert evaluate(policy(), [candidate(permission=SourcePermission.UNVERIFIED)]).reason == "source_permission_unverified"
    assert evaluate(policy(), [candidate(permission=SourcePermission.DENIED)]).state == "unavailable"


def test_historical_fallback_requires_explicit_switch_and_bounded_lookback():
    old = candidate("old", age=5000, current=False)
    assert evaluate(policy(), [old]).reason == "historical_fallback_disabled_or_unbounded"
    assert evaluate(policy(fallback=True), [old]).selected_retrieval_id == "old"
    too_old = candidate("too-old", age=90000, current=False)
    assert evaluate(policy(fallback=True), [too_old]).reason == "market_data_stale"


def test_conflicting_latest_retrievals_and_market_calendar_unknown_fail_closed():
    one = candidate("one", digest="a" * 64)
    two = candidate("two", digest="b" * 64)
    assert evaluate(policy(), [one, two]).reason == "conflicting_retrievals"
    closed_without_evidence = evaluate(policy(), [one], calendar=MarketCalendarState.HOLIDAY_CONFIRMED)
    assert closed_without_evidence.reason == "market_calendar_unverified"
    closed_with_evidence = evaluate(policy(), [one], calendar=MarketCalendarState.CLOSED_CONFIRMED,
                                    calendar_ref="synthetic://calendar-evidence")
    assert closed_with_evidence.state == "eligible"
    assert evaluate(policy(), [candidate(age=-1, publication_delay=0)]).reason == "candidate_timestamp_in_future"


def test_invalidation_closures_holidays_and_missing_timeframes_fail_closed():
    assert evaluate(policy(), [candidate(invalidated=True)]).reason == "evidence_invalidated"
    holiday = evaluate(policy(), [candidate()], calendar=MarketCalendarState.HOLIDAY_CONFIRMED,
                       calendar_ref="synthetic://holiday-calendar")
    assert holiday.state == "eligible"
    assert evaluate_freshness(policy(), (candidate(),), timeframe="15m", as_of=NOW,
        calendar_state=MarketCalendarState.OPEN).reason == "freshness_threshold_unconfigured"
    assert evaluate_freshness(policy(), (candidate(),), timeframe="1h", as_of=NOW,
        calendar_state=MarketCalendarState.HOLIDAY_CONFIRMED).reason == "market_calendar_unverified"


def test_h4_remains_unavailable_under_deferred_policy():
    decision = evaluate_freshness(policy(), (), timeframe="4h", as_of=NOW,
        calendar_state=MarketCalendarState.OPEN)
    assert decision.reason == "h4_policy_deferred"
    with pytest.raises(ValueError, match="deferred"):
        FreshnessPolicyV1("bad", (), (), (), (), False, h4_policy_approved=True)
