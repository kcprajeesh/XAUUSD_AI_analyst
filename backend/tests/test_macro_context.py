from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.data.context import (ContextCompleteness, ContextPolicy, ContextSnapshot, ContextSource, EconomicEvent, FeedStatus, MacroObservation,
                              NewsReport, process_context)


NOW = datetime(2026, 11, 18, 12, tzinfo=UTC)
SOURCE = ContextSource(source_id="fixture", provider_id="synthetic", feed_id="fixture",
    eligibility="eligible", permission_evidence=("synthetic-only:test",), attribution="Synthetic test fixture")
POLICY = ContextPolicy(policy_id="synthetic-policy-v1",
    max_retrieval_age_seconds={name: 3600 for name in ("calendar", "macro", "news", "sentiment")},
    max_publication_delay_seconds={name: 3600 for name in ("calendar", "macro", "news", "sentiment")})


def coverage(*names):
    return ({name: ContextCompleteness.VERIFIED for name in names},
            {name: f"synthetic-only:{name}-page-chain" for name in names})


def event(**kwargs):
    values = {"event_id": "cpi-1", "event_name": "CPI release", "currency": "USD", "scheduled_at": NOW,
        "retrieved_at": NOW, "importance": "high", "source_id": "fixture", "revision_id": "r1",
        "completeness": "verified"}
    return EconomicEvent(**(values | kwargs))


def test_calendar_keeps_scheduled_events_distinct_from_actual_values():
    upcoming = event()
    published = event(actual="3.1", forecast="3.0", previous="3.2", published_at=NOW + timedelta(minutes=1),
                      retrieved_at=NOW + timedelta(minutes=2), revision_id="r2", revision_of="r1")
    complete, evidence = coverage("calendar")
    result = process_context(retrieved_at=NOW + timedelta(minutes=2), source_registry_version="fixture-registry-v1",
        sources=(SOURCE,), events=(upcoming, published), policy=POLICY, feed_completeness=complete, completeness_evidence=evidence)
    assert result.feed_status["calendar"] == FeedStatus.AVAILABLE
    assert result.events[0].actual is None and result.events[1].actual == "3.1"
    with pytest.raises(ValidationError, match="publication timestamp"):
        event(actual="3.1")


def test_unverified_source_missing_policy_and_incomplete_values_fail_closed():
    unverified = SOURCE.model_copy(update={"eligibility": "unverified", "permission_evidence": (), "attribution": None})
    record = MacroObservation(observation_id="m1", series="cpi", period="2026-10", value="3.1", units="percent",
        published_at=NOW, retrieved_at=NOW, source_id="fixture", revision_id="r1", completeness="verified")
    complete, evidence = coverage("macro")
    result = process_context(retrieved_at=NOW, source_registry_version="r1", sources=(unverified,), macro=(record,), policy=POLICY,
        feed_completeness=complete, completeness_evidence=evidence)
    assert result.feed_status["macro"] == FeedStatus.UNVERIFIED
    result = process_context(retrieved_at=NOW, source_registry_version="r1", sources=(SOURCE,), macro=(record,),
        feed_completeness=complete, completeness_evidence=evidence)
    assert result.feed_status["macro"] == FeedStatus.UNVERIFIED
    incomplete = record.model_copy(update={"completeness": "unknown"})
    result = process_context(retrieved_at=NOW, source_registry_version="r1", sources=(SOURCE,), macro=(incomplete,), policy=POLICY,
        feed_completeness=complete, completeness_evidence=evidence)
    assert result.feed_status["macro"] == FeedStatus.INCOMPLETE


def test_news_exact_duplicates_collapse_and_conflicting_reports_are_unavailable():
    base = dict(topic_id="fed-path", headline="Rates held", summary="Report summary", topic="central_bank",
        publication_at=NOW, retrieved_at=NOW, source_id="fixture", attribution="Synthetic fixture",
        credibility="secondary", revision_id="n1", directional_claim="bullish_gold")
    first = NewsReport(report_id="news-1", **base)
    duplicate = NewsReport(report_id="news-2", **base)
    conflicting = NewsReport(report_id="news-3", **(base | {"source_id": "fixture-2", "revision_id": "n2",
        "directional_claim": "bearish_gold"}))
    source2 = SOURCE.model_copy(update={"source_id": "fixture-2"})
    complete, evidence = coverage("news")
    result = process_context(retrieved_at=NOW, source_registry_version="r1", sources=(SOURCE, source2),
        news=(first, duplicate), policy=POLICY, feed_completeness=complete, completeness_evidence=evidence)
    assert len(result.news) == 1 and result.feed_status["news"] == FeedStatus.AVAILABLE
    result = process_context(retrieved_at=NOW, source_registry_version="r1", sources=(SOURCE, source2),
        news=(first, conflicting), policy=POLICY, feed_completeness=complete, completeness_evidence=evidence)
    assert len(result.news) == 2 and result.feed_status["news"] == FeedStatus.CONFLICTING


def test_stale_publication_and_retrieval_are_not_available():
    report = NewsReport(report_id="n1", topic_id="gold", headline="Update", summary="Summary", topic="gold",
        publication_at=NOW - timedelta(hours=3), retrieved_at=NOW, source_id="fixture", attribution="Fixture",
        credibility="primary", revision_id="n1")
    policy = POLICY.model_copy(update={"max_publication_delay_seconds": {name: 60 for name in POLICY.max_publication_delay_seconds}})
    complete, evidence = coverage("news")
    result = process_context(retrieved_at=NOW, source_registry_version="r1", sources=(SOURCE,), news=(report,), policy=policy,
        feed_completeness=complete, completeness_evidence=evidence)
    assert result.feed_status["news"] == FeedStatus.STALE


def test_row_validity_alone_does_not_prove_whole_feed_completeness():
    record = event()
    result = process_context(retrieved_at=NOW, source_registry_version="r1", sources=(SOURCE,), events=(record,), policy=POLICY)
    assert result.feed_status["calendar"] == FeedStatus.UNVERIFIED
    with pytest.raises(ValidationError, match="completeness evidence"):
        ContextSnapshot.model_validate(result.model_dump() | {
            "feed_status": result.feed_status | {"calendar": FeedStatus.AVAILABLE}})
