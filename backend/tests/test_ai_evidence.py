"""Synthetic offline evidence and response-contract tests; no provider calls."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.ai.config import Protocol
from app.ai.contracts import (
    AnalysisResponse, Bias, Claim, ClaimPurpose, Direction, EvidenceSufficiencyLabel,
    PriceLevel, PriceZone, ProviderMetadata, RiskReward, SetupAssessment, TimeframeAnalysis,
    TradeStance, ValidationState, deterministic_no_trade, validate_response,
)
from app.ai.analyst import (AnalystInterpretation, AnalystProvenance, AnalystResponseV1, AnalystStatus,
                            build_prompt, run_analyst)
from app.ai.evidence import (
    CandleOrigin, CandleState, DataQualityFlag, EvidenceCandle, EvidencePacket,
    EvidenceRecord, EvidenceType, FreshnessPolicy, InstrumentIdentity, InstrumentType,
    QualityStatus, SourceIdentity, SufficiencyStatus, Timeframe, TimeframeEvidence,
    TimeframeState, assess_sufficiency,
)


NOW = datetime(2026, 1, 15, 12, tzinfo=UTC)
INSTRUMENT = InstrumentIdentity(instrument_id="xau-usd:spot-aggregate", instrument_type=InstrumentType.OTC_SPOT)


def packet(*, missing_h4=False, forming=False, stale=False, conflict=False, flags=()):
    source = SourceIdentity(source_id="src-spot", instrument=INSTRUMENT, provider_id="synthetic",
        feed_id="synthetic-feed", series_id="synthetic:XAUUSD:1h", provider_symbol="XAUUSD",
        retrieved_at=NOW - timedelta(minutes=2), price_normalization="source_decimal_text", source_price_precision="unknown")
    sources = [source]
    if conflict:
        sources.append(SourceIdentity(source_id="src-cfd", instrument=InstrumentIdentity(
            instrument_id="xau-usd:cfd:sample-broker", instrument_type=InstrumentType.BROKER_CFD),
            provider_id="synthetic", feed_id="broker", series_id="synthetic:broker:1h", provider_symbol="XAUUSD",
            retrieved_at=NOW - timedelta(minutes=2), price_normalization="source_decimal_text", source_price_precision="unknown"))
    timeframes = []
    candles = []
    for tf in Timeframe:
        if missing_h4 and tf == Timeframe.H4:
            timeframes.append(TimeframeEvidence(timeframe=tf, state=TimeframeState.UNSUPPORTED,
                quality_flags=(DataQualityFlag.INCOMPLETE_CONTEXT,)))
            continue
        duration = {Timeframe.D1: timedelta(days=1), Timeframe.H4: timedelta(hours=4),
                    Timeframe.H1: timedelta(hours=1), Timeframe.M15: timedelta(minutes=15),
                    Timeframe.M5: timedelta(minutes=5)}[tf]
        if tf == Timeframe.D1:
            opened = NOW.replace(hour=0, minute=0, second=0, microsecond=0) - duration
        elif forming and tf == Timeframe.H1:
            opened = NOW - duration
        else:
            opened = NOW - duration * 2
        c = EvidenceCandle(candle_id=f"c-{tf.value}", source_id=source.source_id, timeframe=tf,
            opened_at=opened, closed_at=opened + duration,
            status=CandleState.FORMING if forming and tf == Timeframe.H1 else CandleState.CLOSED,
            origin=CandleOrigin.NATIVE, open="2001", high="2031", low="1990", close="2010")
        candles.append(c)
        timeframes.append(TimeframeEvidence(timeframe=tf, state=TimeframeState.AVAILABLE,
            origin=CandleOrigin.NATIVE, source_ids=(source.source_id,), candles=(c,),
            evidence_ids=(f"ev-{tf.value}",),
            quality_flags=(DataQualityFlag.FORMING_CANDLE,) if c.status == CandleState.FORMING else ()))
    records = []
    for tf in Timeframe:
        if missing_h4 and tf == Timeframe.H4:
            continue
        candle_value = next(candle for candle in candles if candle.timeframe == tf)
        records.append(EvidenceRecord(evidence_id=f"ev-{tf.value}", evidence_type=EvidenceType.TREND,
            description=f"Synthetic {tf.value} structure observation", value="2001", units="USD_per_troy_ounce",
            timeframe=tf, observed_at=NOW - timedelta(minutes=5) if forming and tf == Timeframe.H1 else candle_value.closed_at, source_ids=(source.source_id,),
            calculation_method="synthetic_fixture:v1", quality=QualityStatus.STALE if stale and tf == Timeframe.H1 else QualityStatus.VERIFIED,
            candle_refs=(f"c-{tf.value}",)))
    level_time = NOW - timedelta(minutes=5) if forming else NOW - timedelta(hours=1)
    for name, value in (("entry-low", "2000"), ("entry-high", "2002"), ("stop", "1990"), ("target", "2031")):
        records.append(EvidenceRecord(evidence_id=f"ev-{name}", evidence_type=EvidenceType.SUPPORT,
            description=f"Synthetic supported {name}", value=value, units="USD_per_troy_ounce", timeframe=Timeframe.H1,
            observed_at=level_time, source_ids=(source.source_id,),
            calculation_method="synthetic_fixture:explicit_level", quality=QualityStatus.VERIFIED,
            candle_refs=("c-1H",)))
    timeframes = [item.model_copy(update={"evidence_ids": item.evidence_ids + (
        tuple(f"ev-{name}" for name in ("entry-low", "entry-high", "stop", "target")) if item.timeframe == Timeframe.H1 else ())})
        for item in timeframes]
    return EvidencePacket(analysis_id="analysis-synthetic-1", analysis_at=NOW, instrument=INSTRUMENT,
        sources=tuple(sources), requested_timeframes=tuple(Timeframe), retrieved_at=NOW - timedelta(minutes=2),
        freshness_max_age_seconds={tf: 864000 for tf in Timeframe},
        minimum_closed_candles={tf: 1 for tf in Timeframe},
        timeframes=tuple(timeframes), evidence=tuple(records),
        quality_flags=tuple(flags) + ((DataQualityFlag.CONFLICTING_SOURCE,) if conflict else ()))


def packet_without_h4():
    data = packet()
    values = data.model_dump(mode="python")
    values["requested_timeframes"] = tuple(tf for tf in data.requested_timeframes if tf != Timeframe.H4)
    values["timeframes"] = tuple(item for item in data.timeframes if item.timeframe != Timeframe.H4)
    values["evidence"] = tuple(item for item in data.evidence if item.timeframe != Timeframe.H4)
    return EvidencePacket.model_validate(values)


def model_metadata():
    return ProviderMetadata(provider_id="synthetic-provider", model_id="synthetic-model",
        protocol=Protocol.OPENAI_CHAT_COMPLETIONS, analysis_request_id="req-synthetic",
        generated_at=NOW, validation_status=ValidationState.UNVERIFIED)


def analyst_provenance():
    return AnalystProvenance(input_manifest_id="input-fixture", input_manifest_digest="sha256:input",
        derived_manifest_id="derived-fixture", derived_manifest_digest="sha256:derived",
        provider_id="synthetic-provider", model_id="synthetic-model", analysis_request_id="req-synthetic",
        prompt_version="analyst-prompt-v1",
        configuration_metadata=(("temperature", 0), ("response_schema", "1.0"), ("external_calls_enabled", False)),
        created_at=NOW)


def empty_context():
    from app.data.context import ContextSnapshot
    return ContextSnapshot(retrieved_at=NOW, source_registry_version="fixture-only-v1",
        feed_status={name: "unavailable" for name in ("calendar", "macro", "news", "sentiment")},
        unavailable_reasons=("fixture_has_no_external_context",))


def analyst_report(data, analysis, *, context_ids=()):
    scenario = AnalystInterpretation(text="No conclusion without additional confirmation.",
        market_evidence_ids=("ev-1H",), context_record_ids=tuple(context_ids))
    return AnalystResponseV1(analysis=analysis, bullish_scenario=scenario, bearish_scenario=scenario,
        neutral_conditions=scenario)


def response(data, *, stance=TradeStance.BUY_SETUP, bias=Bias.BULLISH, changes=None):
    support = tuple(f"ev-{tf.value}" for tf in data.requested_timeframes if f"ev-{tf.value}" in {r.evidence_id for r in data.evidence})
    analyses = tuple(TimeframeAnalysis(timeframe=tf, direction="UNAVAILABLE" if next(t for t in data.timeframes if t.timeframe == tf).state != TimeframeState.AVAILABLE else "BULLISH",
        supporting_evidence_ids=(f"ev-{tf.value}",) if f"ev-{tf.value}" in support else ()) for tf in data.requested_timeframes)
    setup = SetupAssessment()
    if stance in (TradeStance.BUY_SETUP, TradeStance.SELL_SETUP):
        direction = Direction.LONG if stance == TradeStance.BUY_SETUP else Direction.SHORT
        low, high, stop, target = (Decimal("2000"), Decimal("2002"), Decimal("1990"), Decimal("2031"))
        if direction == Direction.SHORT:
            low, high, stop, target = Decimal("2010"), Decimal("2012"), Decimal("2031"), Decimal("1990")
        entry = PriceZone(low=PriceLevel(value=low, evidence_id="ev-entry-low" if direction == Direction.LONG else "ev-ev-1H"),
                          high=PriceLevel(value=high, evidence_id="ev-entry-high" if direction == Direction.LONG else "ev-ev-1H"))
        if direction == Direction.SHORT:
            # For short setup use evidence values that exist and exactly match the entry range.
            extra_evidence = (
                EvidenceRecord(evidence_id="ev-short-low", evidence_type=EvidenceType.SUPPORT, description="Synthetic short low", value="2010", units="USD_per_troy_ounce", timeframe=Timeframe.H1, observed_at=NOW - timedelta(minutes=5), source_ids=("src-spot",), calculation_method="synthetic_fixture", quality=QualityStatus.VERIFIED, candle_refs=("c-1H",)),
                EvidenceRecord(evidence_id="ev-short-high", evidence_type=EvidenceType.RESISTANCE, description="Synthetic short high", value="2012", units="USD_per_troy_ounce", timeframe=Timeframe.H1, observed_at=NOW - timedelta(minutes=5), source_ids=("src-spot",), calculation_method="synthetic_fixture", quality=QualityStatus.VERIFIED, candle_refs=("c-1H",)),
                EvidenceRecord(evidence_id="ev-short-stop", evidence_type=EvidenceType.RESISTANCE, description="Synthetic short stop", value="2031", units="USD_per_troy_ounce", timeframe=Timeframe.H1, observed_at=NOW - timedelta(minutes=5), source_ids=("src-spot",), calculation_method="synthetic_fixture", quality=QualityStatus.VERIFIED, candle_refs=("c-1H",)),
                EvidenceRecord(evidence_id="ev-short-target", evidence_type=EvidenceType.SUPPORT, description="Synthetic short target", value="1990", units="USD_per_troy_ounce", timeframe=Timeframe.H1, observed_at=NOW - timedelta(minutes=5), source_ids=("src-spot",), calculation_method="synthetic_fixture", quality=QualityStatus.VERIFIED, candle_refs=("c-1H",))
            )
            values = data.model_dump()
            values["evidence"] = (*data.evidence, *extra_evidence)
            values["timeframes"] = tuple({**tf.model_dump(), "evidence_ids": tf.evidence_ids + tuple(item.evidence_id for item in extra_evidence)} if tf.timeframe == Timeframe.H1 else tf.model_dump() for tf in data.timeframes)
            data = EvidencePacket.model_validate(values)
            entry = PriceZone(low=PriceLevel(value=low, evidence_id="ev-short-low"), high=PriceLevel(value=high, evidence_id="ev-short-high"))
        risk = (Decimal("2001") - stop) if direction == Direction.LONG else (stop - Decimal("2011"))
        reward = (target - Decimal("2001")) if direction == Direction.LONG else (Decimal("2011") - target)
        setup = SetupAssessment(direction=direction, required_conditions=(Claim(text="Wait for the synthetic trigger.", evidence_ids=("ev-1H",)),),
            trigger_conditions=(Claim(text="The synthetic trigger must be observed.", evidence_ids=("ev-1H",)),),
            invalidation_conditions=(Claim(text="Cancel if the supplied structure fails.", evidence_ids=("ev-1H",)),),
            entry_zone=entry, stop_loss=PriceLevel(value=stop, evidence_id="ev-stop" if direction == Direction.LONG else "ev-short-stop"),
            target=PriceLevel(value=target, evidence_id="ev-target" if direction == Direction.LONG else "ev-short-target"),
            stop_reasoning=(Claim(text="Stop level is tied to supplied structure.", evidence_ids=("ev-1H",)),),
            target_reasoning=(Claim(text="Target level is tied to supplied structure.", evidence_ids=("ev-1H",)),),
            risk_reward=RiskReward(ratio=(reward / risk).quantize(Decimal("0.0001"))))
    result = AnalysisResponse(analysis_id=data.analysis_id, bias=bias, trade_stance=stance,
        rationale=(Claim(text="Synthetic structure supports this interpretation.", evidence_ids=("ev-1H",)),),
        evidence_sufficiency=EvidenceSufficiencyLabel.SUFFICIENT, timeframes=analyses, setup=setup,
        provider_metadata=model_metadata(), validation_status=ValidationState.UNVERIFIED)
    if changes:
        values = result.model_dump()
        values.update(changes)
        result = AnalysisResponse.model_validate(values)
    return data, result


@pytest.mark.parametrize("stance,bias", [(TradeStance.BUY_SETUP, Bias.BULLISH), (TradeStance.SELL_SETUP, Bias.BEARISH)])
def test_supported_bullish_and_bearish_scenarios(stance, bias):
    data, result = response(packet(), stance=stance, bias=bias)
    assert validate_response(data, result).valid


def test_neutral_range_bound_and_valid_no_trade_responses():
    data, result = response(packet(), stance=TradeStance.WAIT, bias=Bias.NEUTRAL)
    assert validate_response(data, result).valid
    no_trade = result.model_copy(update={"trade_stance": TradeStance.NO_TRADE, "setup": SetupAssessment()})
    assert validate_response(data, no_trade).valid


@pytest.mark.parametrize("unrequested", [Timeframe.D1, Timeframe.H4, Timeframe.M15, Timeframe.M5])
def test_claim_on_unrequested_timeframe_returns_invalid_instead_of_crashing(unrequested):
    original = packet()
    values = original.model_dump(mode="python")
    values.update(requested_timeframes=(Timeframe.H1,),
                  timeframes=tuple(tf for tf in original.timeframes if tf.timeframe == Timeframe.H1),
                  evidence=tuple(record for record in original.evidence if record.timeframe == Timeframe.H1))
    data, report = response(EvidencePacket.model_validate(values), stance=TradeStance.WAIT)
    assert validate_response(data, report).valid
    report = report.model_copy(update={"rationale": tuple(
        claim.model_copy(update={"timeframe": unrequested}) for claim in report.rationale)})
    check = validate_response(data, report)
    assert not check.valid and check.status == ValidationState.INVALID
    assert "Claim timeframe was not requested in the evidence packet" in check.errors


def test_insufficient_evidence_and_missing_4h_get_deterministic_no_trade():
    data = packet(missing_h4=True)
    result = deterministic_no_trade(data)
    assert result.trade_stance == TradeStance.NO_TRADE
    assert validate_response(data, result).valid
    assert SufficiencyStatus.MISSING_TIMEFRAMES in assess_sufficiency(data).statuses


def test_forming_and_stale_evidence_are_not_sufficient():
    forming = packet(forming=True)
    stale = packet(stale=True)
    assert SufficiencyStatus.FORMING_CANDLES in assess_sufficiency(forming).statuses
    assert SufficiencyStatus.STALE in assess_sufficiency(stale).statuses
    assert SufficiencyStatus.STALE in assess_sufficiency(packet().with_readiness(freshness={Timeframe.H1: 60})).statuses
    assert not validate_response(stale, response(stale)[1]).valid
    stale_warning = Claim(text="1H source evidence is stale.", evidence_ids=("ev-1H",),
        timeframe=Timeframe.H1, purpose=ClaimPurpose.DATA_QUALITY)
    result = response(stale, stance=TradeStance.WAIT, bias=Bias.NEUTRAL)[1]
    timeframe_reports = tuple(item.model_copy(update={"direction": "UNAVAILABLE", "supporting_evidence_ids": (),
        "data_quality_warnings": (stale_warning,)}) if item.timeframe == Timeframe.H1 else item
        for item in result.timeframes)
    result = result.model_copy(update={"rationale": (Claim(text="Other timeframe evidence remains supplied.", evidence_ids=("ev-15M",)),),
        "evidence_sufficiency": EvidenceSufficiencyLabel.PARTIAL, "timeframes": timeframe_reports,
        "missing_information": (stale_warning,)})
    assert validate_response(stale, result).valid


def test_invalid_missing_outlier_and_unsupported_derivation_flags_close_sufficiency_gate():
    data = packet(flags=(DataQualityFlag.INVALID_CANDLES, DataQualityFlag.MISSING_CANDLES,
        DataQualityFlag.OUTLIER, DataQualityFlag.UNSUPPORTED_DERIVATION, DataQualityFlag.INCOMPLETE_CONTEXT))
    statuses = set(assess_sufficiency(data).statuses)
    assert {SufficiencyStatus.INVALID_CANDLES, SufficiencyStatus.PARTIAL,
        SufficiencyStatus.UNSUPPORTED_DERIVATION, SufficiencyStatus.INCOMPLETE_CONTEXT} <= statuses


def test_conflicting_instrument_identities_are_not_merged():
    data = packet(conflict=True)
    assert SufficiencyStatus.CONFLICTING_INSTRUMENTS in assess_sufficiency(data).statuses
    assert not validate_response(data, response(data)[1]).valid


@pytest.mark.parametrize("change,expected", [
    ({"rationale": (Claim(text="Claim with unknown evidence", evidence_ids=("missing",)),)}, "missing evidence"),
    ({"setup": SetupAssessment(direction=Direction.LONG, entry_zone=PriceZone(low=PriceLevel(value="2500", evidence_id="ev-entry-low"), high=PriceLevel(value="2501", evidence_id="ev-entry-high")))}, "not supported"),
    ({"timeframes": (TimeframeAnalysis(timeframe=Timeframe.H1, direction="BULLISH", supporting_evidence_ids=("ev-15M",)),)}, "timeframe"),
    ({"rationale": (Claim(text="Gold reacts to breaking news sentiment.", evidence_ids=("ev-1H",)),)}, "unsupported"),
    ({"rationale": (Claim(text="Gold is currently near 2001.5.", evidence_ids=("ev-1H",)),)}, "numeric evidence"),
])
def test_invalid_references_levels_timeframes_and_news(change, expected):
    data, base = response(packet())
    result = base.model_copy(update=change)
    check = validate_response(data, result)
    assert not check.valid
    assert any(expected in error.lower() for error in check.errors)


def test_bad_entry_stop_target_and_risk_reward_are_rejected():
    data, base = response(packet())
    bad_order = base.model_copy(update={"setup": base.setup.model_copy(update={
        "stop_loss": PriceLevel(value="2031", evidence_id="ev-target")})})
    assert any("inconsistent" in error for error in validate_response(data, bad_order).errors)
    bad_ratio = base.model_copy(update={"setup": base.setup.model_copy(update={
        "risk_reward": RiskReward(ratio="1")})})
    assert any("risk/reward" in error.lower() for error in validate_response(data, bad_ratio).errors)
    missing_levels = base.model_copy(update={"setup": base.setup.model_copy(update={
        "entry_zone": None, "risk_reward": RiskReward(ratio="2")})})
    assert any("requires supported" in error for error in validate_response(data, missing_levels).errors)


def test_provider_metadata_is_mandatory_for_model_reports():
    with pytest.raises(ValidationError):
        AnalysisResponse(analysis_id="a", bias=Bias.NEUTRAL, trade_stance=TradeStance.NO_TRADE,
            rationale=(Claim(text="Data unavailable", evidence_ids=("ev",)),),
            evidence_sufficiency=EvidenceSufficiencyLabel.INSUFFICIENT, timeframes=())


def test_confidence_explanation_rejects_percentages():
    data, base = response(packet(), stance=TradeStance.WAIT, bias=Bias.NEUTRAL)
    result = base.model_copy(update={"confidence_explanation": (
        Claim(text="Confidence is 80%.", evidence_ids=("ev-1H",)),)})
    assert any("qualitatively" in error for error in validate_response(data, result).errors)


def test_evidence_contract_rejects_duplicate_ids_float_prices_and_bad_ohlc():
    data = packet()
    values = data.model_dump()
    values["evidence"] = (*data.evidence, data.evidence[0])
    with pytest.raises(ValidationError):
        EvidencePacket.model_validate(values)
    with pytest.raises(ValidationError):
        EvidenceCandle(candle_id="float", source_id="src-spot", timeframe=Timeframe.H1,
            opened_at=NOW, status=CandleState.CLOSED, open=2001.1, high="2002", low="2000", close="2001")
    with pytest.raises(ValidationError):
        EvidenceCandle(candle_id="bad", source_id="src-spot", timeframe=Timeframe.H1,
            opened_at=NOW, status=CandleState.CLOSED, open="2001", high="2000", low="1990", close="2000")


def test_aggregated_4h_requires_aligned_closed_1h_sources_and_exact_ohlc():
    source = SourceIdentity(source_id="src", instrument=INSTRUMENT, provider_id="synthetic",
        feed_id="feed", series_id="series", provider_symbol="XAUUSD", retrieved_at=NOW,
        price_normalization="source_decimal_text", source_price_precision="unknown")
    start = datetime(2026, 1, 15, 8, tzinfo=UTC)
    inputs = tuple(EvidenceCandle(candle_id=f"h1-{index}", source_id="src", timeframe=Timeframe.H1,
        opened_at=start + timedelta(hours=index), closed_at=start + timedelta(hours=index + 1),
        status=CandleState.CLOSED, open=str(2000 + index), high=str(2002 + index),
        low=str(1999 + index), close=str(2001 + index)) for index in range(4))
    aggregate = EvidenceCandle(candle_id="h4", source_id="src", timeframe=Timeframe.H4,
        opened_at=start, closed_at=start + timedelta(hours=4), status=CandleState.CLOSED,
        origin=CandleOrigin.AGGREGATED, open="2000", high="2005", low="1999", close="2004",
        source_candle_ids=tuple(item.candle_id for item in inputs))
    packet = EvidencePacket(analysis_id="aggregation-test", analysis_at=NOW, instrument=INSTRUMENT,
        sources=(source,), requested_timeframes=(Timeframe.H4, Timeframe.H1), retrieved_at=NOW,
        timeframes=(TimeframeEvidence(timeframe=Timeframe.H4, state=TimeframeState.AVAILABLE,
                    origin=CandleOrigin.AGGREGATED, source_ids=("src",), candles=(aggregate,)),
                    TimeframeEvidence(timeframe=Timeframe.H1, state=TimeframeState.AVAILABLE,
                    origin=CandleOrigin.NATIVE, source_ids=("src",), candles=inputs)))
    assert packet.timeframes[0].candles[0].origin == CandleOrigin.AGGREGATED
    bad_values = packet.model_dump()
    bad_values["timeframes"][0]["candles"][0]["high"] = "2004"
    with pytest.raises(ValidationError):
        EvidencePacket.model_validate(bad_values)


def test_tick_count_is_retained_with_explicit_semantics():
    candle = EvidenceCandle(candle_id="tick", source_id="src-spot", timeframe=Timeframe.H1,
        opened_at=NOW, status=CandleState.UNVERIFIED, open="2001", high="2002", low="2000", close="2001",
        volume_value="622513355", volume_type="tick_count")
    assert candle.volume_value == Decimal("622513355")
    assert candle.volume_type.value == "tick_count"


def test_analyst_binds_manifests_and_validates_injected_response_without_network():
    data, result = response(packet_without_h4(), stance=TradeStance.WAIT, bias=Bias.NEUTRAL)
    prompts = []
    output = analyst_report(data, result)
    run = run_analyst(data, empty_context(), analyst_provenance(),
        lambda prompt: (prompts.append(prompt) or output.model_dump_json()), verify_binding=lambda _p: True)
    assert run.status == AnalystStatus.COMPLETE and run.analysis == result
    assert run.provenance.input_manifest_id == "input-fixture"
    assert run.provenance.derived_manifest_id == "derived-fixture"
    assert run.context_status["news"] == "unavailable"
    prompt = build_prompt(data, empty_context(), analyst_provenance())
    assert '"input_manifest_id":"input-fixture"' in prompt
    assert '"fixture_has_no_external_context"' in prompt
    assert len(prompts) == 1


def test_analyst_returns_deterministic_insufficient_evidence_without_calling_completion():
    data = packet(missing_h4=True)
    called = False

    def should_not_run(_prompt):
        nonlocal called
        called = True
        raise AssertionError("insufficient evidence must not be sent to a model")

    result = run_analyst(data, empty_context(), analyst_provenance(), should_not_run, verify_binding=lambda _p: True)
    assert result.status == AnalystStatus.INSUFFICIENT_EVIDENCE
    assert validate_response(data, result.analysis).valid
    assert result.analysis.trade_stance == TradeStance.NO_TRADE
    assert not called
    assert "One or more requested timeframes are unavailable or unsupported." in result.unavailable_inputs


@pytest.mark.parametrize("completion, expected", [
    (lambda _prompt: "not json", AnalystStatus.INVALID_RESPONSE),
    (lambda _prompt: (_ for _ in ()).throw(TimeoutError()), AnalystStatus.UNAVAILABLE),
])
def test_analyst_provider_failure_and_invalid_response_are_explicit(completion, expected):
    result = run_analyst(packet_without_h4(), empty_context(), analyst_provenance(), completion, verify_binding=lambda _p: True)
    assert result.status == expected and result.analysis is None and result.report is None and result.failure_reason


def test_analyst_rejects_ungrounded_news_or_price_claims():
    data, invalid = response(packet_without_h4(), stance=TradeStance.WAIT, bias=Bias.NEUTRAL)
    invalid = invalid.model_copy(update={"rationale": (
        Claim(text="News says gold reaches 9999.", evidence_ids=("ev-1H",)),)})
    result = run_analyst(data, empty_context(), analyst_provenance(),
                         lambda _prompt: analyst_report(data, invalid).model_dump_json(),
                         verify_binding=lambda _p: True)
    assert result.status == AnalystStatus.INVALID_RESPONSE and result.analysis is None
    assert result.failure_reason == "response_evidence_validation_failed"


def test_analyst_context_citations_require_an_available_feed():
    from app.data.context import (ContextCompleteness, ContextPolicy, ContextSource, NewsReport,
                                  context_record_reference, process_context)
    source = ContextSource(source_id="news-source", provider_id="synthetic", feed_id="fixture",
        eligibility="eligible", permission_evidence=("synthetic-only:test",), attribution="Fixture only")
    news = NewsReport(report_id="news-1", topic_id="gold", headline="Synthetic report", summary="Fixture summary",
        topic="gold", publication_at=NOW - timedelta(minutes=1), retrieved_at=NOW, source_id="news-source",
        attribution="Fixture only", credibility="secondary", revision_id="news-rev-1")
    policy = ContextPolicy(policy_id="synthetic-test-v1",
        max_retrieval_age_seconds={name: 3600 for name in ("calendar", "macro", "news", "sentiment")},
        max_publication_delay_seconds={name: 3600 for name in ("calendar", "macro", "news", "sentiment")})
    context = process_context(retrieved_at=NOW, source_registry_version="fixture-v1", sources=(source,),
        news=(news,), policy=policy, feed_completeness={"news": ContextCompleteness.VERIFIED},
        completeness_evidence={"news": "synthetic-only:page-chain"})
    data, analysis = response(packet_without_h4(), stance=TradeStance.WAIT, bias=Bias.NEUTRAL)
    report = analyst_report(data, analysis, context_ids=(context_record_reference("news", "news-source", "news-rev-1"),))
    result = run_analyst(data, context, analyst_provenance(), lambda _p: report.model_dump_json(),
                         verify_binding=lambda _p: True)
    assert result.status == AnalystStatus.COMPLETE
    unavailable = process_context(retrieved_at=NOW, source_registry_version="fixture-v1", sources=(source,), news=(news,))
    result = run_analyst(data, unavailable, analyst_provenance(), lambda _p: report.model_dump_json(),
                         verify_binding=lambda _p: True)
    assert result.status == AnalystStatus.INVALID_RESPONSE
    assert result.failure_reason == "response_evidence_validation_failed"


def test_analyst_requires_verified_manifest_binding_before_any_completion():
    invoked = False

    def completion(_prompt):
        nonlocal invoked
        invoked = True
        return "{}"

    result = run_analyst(packet(), empty_context(), analyst_provenance(), completion, verify_binding=lambda _p: False)
    assert result.status == AnalystStatus.UNAVAILABLE
    assert result.failure_reason == "immutable_manifest_binding_not_verified"
    assert not invoked


def test_analyst_scenario_rejects_uncited_numeric_market_claims():
    data, analysis = response(packet_without_h4(), stance=TradeStance.WAIT, bias=Bias.NEUTRAL)
    report = analyst_report(data, analysis).model_copy(update={
        "bullish_scenario": AnalystInterpretation(text="Gold may reach 9999.", market_evidence_ids=("ev-1H",))})
    result = run_analyst(data, empty_context(), analyst_provenance(), lambda _p: report.model_dump_json(),
                         verify_binding=lambda _p: True)
    assert result.status == AnalystStatus.INVALID_RESPONSE
    assert result.failure_reason == "response_evidence_validation_failed"
    assert "analyst_scenario_unsupported_numeric_claim" in result.unavailable_inputs


def test_analyst_rejects_available_h4_while_h4_policy_is_deferred():
    invoked = False

    def completion(_prompt):
        nonlocal invoked
        invoked = True
        return "{}"

    result = run_analyst(packet(), empty_context(), analyst_provenance(), completion, verify_binding=lambda _p: True)
    assert result.status == AnalystStatus.UNAVAILABLE
    assert result.failure_reason == "h4_policy_deferred"
    assert not invoked


@pytest.mark.parametrize("updates", [
    {"freshness_max_age_seconds": {}},
    {"freshness_max_age_seconds": {Timeframe.H1: 1}},
    {"minimum_closed_candles": {}},
    {"minimum_closed_candles": {tf: 300 for tf in Timeframe}},
])
def test_analyst_reassessment_enforces_packet_readiness(updates):
    data = packet_without_h4().model_copy(update=updates)
    def forbidden(_):
        raise AssertionError("Readiness failure must not call a model")
    result = run_analyst(data, empty_context(), analyst_provenance(), forbidden,
                         verify_binding=lambda _: True)
    assert result.status == AnalystStatus.INSUFFICIENT_EVIDENCE
    assert validate_response(data, result.analysis).valid


def test_readiness_values_are_strict_immutable_copies_and_roundtrip():
    ages = {tf: 864000 for tf in Timeframe}
    depths = {tf: 1 for tf in Timeframe}
    data = EvidencePacket.model_validate(dict(packet().model_dump(mode="python"),
        freshness_max_age_seconds=ages, minimum_closed_candles=depths))
    ages[Timeframe.H1] = 999999
    depths[Timeframe.H1] = 300
    assert data.freshness_max_age_seconds[Timeframe.H1] == 864000
    assert data.minimum_closed_candles[Timeframe.H1] == 1
    for values in (data.freshness_max_age_seconds, data.minimum_closed_candles,
                   FreshnessPolicy(max_age_seconds=ages).max_age_seconds):
        with pytest.raises(TypeError):
            values[Timeframe.H1] = 1
    restored = EvidencePacket.model_validate_json(data.model_dump_json())
    assert restored == data
    with pytest.raises(TypeError):
        restored.minimum_closed_candles[Timeframe.H1] = 1
    for invalid in (True, 1.5, "300", 0, -1):
        with pytest.raises(ValidationError):
            data.with_readiness(minimum_candles={Timeframe.H1: invalid})
        with pytest.raises(ValidationError):
            FreshnessPolicy(max_age_seconds={Timeframe.H1: invalid})


def test_stricter_supplied_policy_must_be_bound_and_survives_analyst():
    data = packet_without_h4()
    supplied = FreshnessPolicy(max_age_seconds={Timeframe.H1: 1})
    with pytest.raises(ValueError, match="Bind stricter freshness"):
        assess_sufficiency(data, supplied)
    bound = data.with_readiness(freshness=supplied.max_age_seconds)
    assert SufficiencyStatus.STALE in assess_sufficiency(bound, supplied).statuses
    # Looser reassessment and rebinding cannot erase the established limit.
    weaker = bound.with_readiness(freshness={Timeframe.H1: 999999})
    assert weaker.freshness_max_age_seconds[Timeframe.H1] == 1
    assert not assess_sufficiency(weaker, FreshnessPolicy(max_age_seconds={Timeframe.H1: 999999})).sufficient
    def forbidden(_):
        raise AssertionError("Stricter freshness must survive downstream")
    result = run_analyst(weaker, empty_context(), analyst_provenance(), forbidden, verify_binding=lambda _: True)
    assert result.status == AnalystStatus.INSUFFICIENT_EVIDENCE
    assert result.market_data_status == "stale"
    assert validate_response(weaker, result.analysis).valid


def test_depth_can_only_tighten_through_policy_binding():
    data = packet_without_h4().with_readiness(minimum_candles={Timeframe.H1: 300})
    data = data.with_readiness(minimum_candles={Timeframe.H1: 1})
    assert data.minimum_closed_candles[Timeframe.H1] == 300
    result = run_analyst(data, empty_context(), analyst_provenance(),
        lambda _: (_ for _ in ()).throw(AssertionError("Depth must survive")), verify_binding=lambda _: True)
    assert result.status == AnalystStatus.INSUFFICIENT_EVIDENCE
