"""Provider-independent structured analysis result and evidence validator."""

from decimal import Decimal, ROUND_HALF_UP
from enum import StrEnum
import re
from typing import Annotated, Literal

from pydantic import BeforeValidator, BaseModel, ConfigDict, Field, model_validator

from app.ai.config import Protocol
from app.ai.evidence import EvidenceDecimal, EvidencePacket, QualityStatus, Timeframe, assess_sufficiency
from app.data.contracts import UTCInstant, exact_decimal


class AnalysisModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Bias(StrEnum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


class TradeStance(StrEnum):
    BUY_SETUP = "BUY SETUP"
    SELL_SETUP = "SELL SETUP"
    WAIT = "WAIT"
    NO_TRADE = "NO TRADE"


class Direction(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"


class EvidenceSufficiencyLabel(StrEnum):
    SUFFICIENT = "sufficient"
    PARTIAL = "partial"
    INSUFFICIENT = "insufficient"


class ValidationState(StrEnum):
    VERIFIED = "verified"
    UNVERIFIED = "unverified"
    INVALID = "invalid"


class AnalysisOrigin(StrEnum):
    MODEL = "model"
    DETERMINISTIC_GATE = "deterministic_insufficient_evidence"


class ClaimPurpose(StrEnum):
    MARKET_FACT = "market_fact"
    DATA_QUALITY = "data_quality"
    CONFLICT = "conflict"


class Claim(AnalysisModel):
    text: str = Field(min_length=1)
    evidence_ids: tuple[str, ...] = ()
    numeric_values: tuple["NumericReference", ...] = ()
    timeframe: Timeframe | None = None
    purpose: ClaimPurpose = ClaimPurpose.MARKET_FACT


class NumericReference(AnalysisModel):
    value: Annotated[Decimal, BeforeValidator(exact_decimal), Field(allow_inf_nan=False)]
    evidence_id: str = Field(min_length=1)


class PriceLevel(AnalysisModel):
    value: Annotated[Decimal, BeforeValidator(exact_decimal), Field(gt=0, allow_inf_nan=False)]
    evidence_id: str = Field(min_length=1)


class PriceZone(AnalysisModel):
    low: PriceLevel
    high: PriceLevel

    @model_validator(mode="after")
    def ordered(self):
        if self.low.value > self.high.value:
            raise ValueError("Price zone low must not exceed high")
        return self


class RiskReward(AnalysisModel):
    ratio: Annotated[Decimal, BeforeValidator(exact_decimal), Field(gt=0, allow_inf_nan=False)]
    calculation: Literal["reward_divided_by_risk"] = "reward_divided_by_risk"


class TimeframeAnalysis(AnalysisModel):
    timeframe: Timeframe
    direction: Literal["BULLISH", "BEARISH", "NEUTRAL", "UNAVAILABLE"]
    structure: tuple[Claim, ...] = ()
    supporting_evidence_ids: tuple[str, ...] = ()
    conflicting_evidence_ids: tuple[str, ...] = ()
    data_quality_warnings: tuple[Claim, ...] = ()


class SetupAssessment(AnalysisModel):
    setup_type: Claim | None = None
    direction: Direction | None = None
    required_conditions: tuple[Claim, ...] = ()
    entry_zone: PriceZone | None = None
    trigger_conditions: tuple[Claim, ...] = ()
    invalidation_conditions: tuple[Claim, ...] = ()
    stop_loss: PriceLevel | None = None
    stop_reasoning: tuple[Claim, ...] = ()
    target: PriceLevel | None = None
    target_reasoning: tuple[Claim, ...] = ()
    risk_reward: RiskReward | None = None


class ProviderMetadata(AnalysisModel):
    provider_id: str = Field(min_length=1)
    model_id: str = Field(min_length=1)
    protocol: Protocol
    analysis_request_id: str = Field(min_length=1)
    generated_at: UTCInstant
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    cost_usd: EvidenceDecimal | None = Field(default=None, ge=0)
    validation_status: ValidationState


class AnalysisResponse(AnalysisModel):
    schema_version: Literal["1.0"] = "1.0"
    analysis_id: str = Field(min_length=1)
    origin: AnalysisOrigin = AnalysisOrigin.MODEL
    bias: Bias
    trade_stance: TradeStance
    rationale: tuple[Claim, ...] = Field(min_length=1)
    evidence_sufficiency: EvidenceSufficiencyLabel
    timeframes: tuple[TimeframeAnalysis, ...]
    setup: SetupAssessment = Field(default_factory=SetupAssessment)
    confidence_explanation: tuple[Claim, ...] = ()
    conflicting_evidence: tuple[Claim, ...] = ()
    missing_information: tuple[Claim, ...] = ()
    invalidating_conditions: tuple[Claim, ...] = ()
    reasons_to_avoid: tuple[Claim, ...] = ()
    provider_metadata: ProviderMetadata | None = None
    validation_status: ValidationState = ValidationState.UNVERIFIED

    @model_validator(mode="after")
    def provider_origin_consistency(self):
        if (self.origin == AnalysisOrigin.MODEL) != (self.provider_metadata is not None):
            raise ValueError("Model reports require provider metadata; deterministic gate reports must omit it")
        return self


class ResponseValidation(AnalysisModel):
    valid: bool
    errors: tuple[str, ...] = ()
    status: ValidationState


def _claims(response: AnalysisResponse) -> tuple[Claim, ...]:
    claims = list(response.rationale + response.confidence_explanation + response.conflicting_evidence +
                  response.invalidating_conditions + response.reasons_to_avoid + response.missing_information)
    for item in response.timeframes:
        claims.extend(item.structure + item.data_quality_warnings)
    if response.setup.setup_type:
        claims.append(response.setup.setup_type)
    claims.extend(response.setup.required_conditions + response.setup.trigger_conditions +
                  response.setup.invalidation_conditions + response.setup.stop_reasoning + response.setup.target_reasoning)
    return tuple(claims)


def validate_response(packet: EvidencePacket, response: AnalysisResponse) -> ResponseValidation:
    """Check references and all explicit levels against the exact input packet."""
    errors: list[str] = []
    if response.analysis_id != packet.analysis_id:
        errors.append("Analysis ID does not match the evidence packet")
    records = {item.evidence_id: item for item in packet.evidence}
    sources = {item.source_id: item for item in packet.sources}
    timeframe_packet = {item.timeframe: item for item in packet.timeframes}
    if {item.timeframe for item in response.timeframes} != set(packet.requested_timeframes):
        errors.append("Response timeframe set must exactly match requested timeframes")
    if len({item.timeframe for item in response.timeframes}) != len(response.timeframes):
        errors.append("Response timeframe identifiers must be unique")
    usable = set(assess_sufficiency(packet).usable_evidence_ids)
    gate_warnings = set(assess_sufficiency(packet).warnings)
    quality_claims = {id(claim) for claim in response.missing_information + response.reasons_to_avoid}
    conflict_claims = {id(claim) for claim in response.conflicting_evidence}
    for section in response.timeframes:
        quality_claims.update(id(claim) for claim in section.data_quality_warnings)
    for claim in _claims(response):
        allowed_nonusable = (
            claim.purpose == ClaimPurpose.DATA_QUALITY and id(claim) in quality_claims
        ) or (
            claim.purpose == ClaimPurpose.CONFLICT and id(claim) in conflict_claims
        )
        if claim.purpose != ClaimPurpose.MARKET_FACT and not allowed_nonusable:
            errors.append("Claim purpose is not valid in this response section")
        if claim.timeframe is not None and claim.timeframe not in timeframe_packet:
            errors.append("Claim timeframe was not requested in the evidence packet")
            continue
        if claim in response.confidence_explanation and re.search(r"\b\d+(?:\.\d+)?\s*%", claim.text):
            errors.append("Confidence must be explained qualitatively, without a percentage")
        gate_reason = response.origin == AnalysisOrigin.DETERMINISTIC_GATE and (
            (claim in response.rationale and claim.text == "NO TRADE — DATA NOT VERIFIED. Required evidence gates did not pass.") or
            (claim in response.missing_information and claim.text in gate_warnings)
        )
        if (not claim.evidence_ids and not gate_reason) or any(item not in records for item in claim.evidence_ids):
            errors.append("Claim references missing evidence IDs")
            continue
        if any(item.evidence_id not in claim.evidence_ids or item.evidence_id not in records or records[item.evidence_id].value != item.value for item in claim.numeric_values):
            errors.append("Numeric claim does not match its cited evidence value")
        for evidence_id in claim.evidence_ids:
            record = records[evidence_id]
            if evidence_id not in usable and not allowed_nonusable:
                errors.append(f"Claim references non-verified evidence: {evidence_id}")
            if claim.timeframe is not None and record.timeframe not in (None, claim.timeframe):
                errors.append(f"Claim timeframe conflicts with evidence: {evidence_id}")
            if claim.timeframe is not None and evidence_id not in timeframe_packet[claim.timeframe].evidence_ids:
                errors.append(f"Claim evidence is not listed in the timeframe packet: {evidence_id}")
            if claim.purpose != ClaimPurpose.CONFLICT and any(sources[source_id].instrument != packet.instrument for source_id in record.source_ids):
                errors.append(f"Claim evidence belongs to a conflicting instrument: {evidence_id}")
            if re.search(r"\b(news|sentiment|headline)\b", claim.text, re.IGNORECASE):
                errors.append("News or sentiment claims are unsupported by this evidence contract")
            # Numeric price literals must be represented as explicit, cited price levels.
            literals = re.findall(r"(?<![A-Za-z])\d[\d,]*(?:\.\d+)?(?![A-Za-z])", claim.text)
            for literal in literals:
                try:
                    value = Decimal(literal.replace(",", ""))
                except Exception:
                    continue
                explicit = any(level.value == value and level.evidence_id in claim.evidence_ids for level in _all_level_refs(response))
                explicit = explicit or any(ref.value == value and ref.evidence_id in claim.evidence_ids for ref in claim.numeric_values)
                if not explicit:
                    errors.append("Claim contains a price-like number without a cited numeric evidence value")
                    break
    for item in response.timeframes:
        expected = timeframe_packet.get(item.timeframe)
        if expected is None:
            continue
        cited = set(item.supporting_evidence_ids + item.conflicting_evidence_ids)
        if any(evidence_id not in records for evidence_id in cited):
            errors.append(f"{item.timeframe.value} references unknown evidence")
        if any(records[evidence_id].timeframe not in (None, item.timeframe) for evidence_id in cited if evidence_id in records):
            errors.append(f"{item.timeframe.value} references evidence from another timeframe")
        if any(evidence_id not in usable for evidence_id in cited):
            errors.append(f"{item.timeframe.value} cites unverified evidence")
        if any(evidence_id not in expected.evidence_ids for evidence_id in cited):
            errors.append(f"{item.timeframe.value} cites evidence not listed in its packet section")
        for claim in item.structure + item.data_quality_warnings:
            if any(evidence_id in records and records[evidence_id].timeframe not in (None, item.timeframe)
                   for evidence_id in claim.evidence_ids):
                errors.append(f"{item.timeframe.value} claim cites evidence from another timeframe")
        if expected.state.value != "available" and item.direction != "UNAVAILABLE":
            errors.append(f"Unavailable {item.timeframe.value} must be reported unavailable")
        if expected.state.value == "available" and item.direction != "UNAVAILABLE" and not (item.supporting_evidence_ids or item.structure):
            errors.append(f"Available {item.timeframe.value} assessment needs supporting evidence")
        if expected.state.value != "available" and (item.supporting_evidence_ids or item.conflicting_evidence_ids):
            errors.append(f"Unavailable {item.timeframe.value} cannot claim supporting/conflicting evidence")
    setup = response.setup
    levels = _all_level_refs(response)
    for level in levels:
        record = records.get(level.evidence_id)
        if record is None:
            errors.append("Price level references missing evidence")
        elif (record.value is None or record.value != level.value or record.quality != QualityStatus.VERIFIED
              or record.units != "USD_per_troy_ounce" or level.evidence_id not in usable):
            errors.append(f"Price level is not supported by its exact verified evidence: {level.evidence_id}")
    if setup.stop_loss is not None and not setup.stop_reasoning:
        errors.append("Stop-loss level requires cited reasoning")
    if setup.target is not None and not setup.target_reasoning:
        errors.append("Target level requires cited reasoning")
    if response.trade_stance in (TradeStance.BUY_SETUP, TradeStance.SELL_SETUP):
        expected_direction = Direction.LONG if response.trade_stance == TradeStance.BUY_SETUP else Direction.SHORT
        if setup.direction != expected_direction:
            errors.append("Setup direction conflicts with trade stance")
        expected_bias = Bias.BULLISH if response.trade_stance == TradeStance.BUY_SETUP else Bias.BEARISH
        if response.bias != expected_bias:
            errors.append("Directional setup conflicts with overall market bias")
        if response.evidence_sufficiency != EvidenceSufficiencyLabel.SUFFICIENT:
            errors.append("Directional setup requires a sufficient evidence assessment")
        if not setup.required_conditions or not setup.trigger_conditions or not setup.invalidation_conditions:
            errors.append("Directional setup requires preconditions, trigger and invalidation conditions")
        if not setup.stop_reasoning or not setup.target_reasoning:
            errors.append("Directional setup requires stop-loss and target reasoning")
    if (setup.entry_zone or setup.stop_loss or setup.target) and setup.direction is None:
        errors.append("Price levels require an explicit setup direction")
    if setup.entry_zone and setup.direction:
        low, high = setup.entry_zone.low.value, setup.entry_zone.high.value
        if setup.stop_loss:
            stop = setup.stop_loss.value
            if (setup.direction == Direction.LONG and stop >= low) or (setup.direction == Direction.SHORT and stop <= high):
                errors.append("Entry zone and stop level are inconsistent")
        if setup.target:
            target = setup.target.value
            if (setup.direction == Direction.LONG and target <= high) or (setup.direction == Direction.SHORT and target >= low):
                errors.append("Entry zone and target level are inconsistent")
    if setup.entry_zone and setup.stop_loss and setup.target and setup.direction:
        low, high, stop, target = setup.entry_zone.low.value, setup.entry_zone.high.value, setup.stop_loss.value, setup.target.value
        if setup.direction == Direction.LONG and not stop < low <= high < target:
            errors.append("Long entry, stop and target levels are inconsistent")
        if setup.direction == Direction.SHORT and not target < low <= high < stop:
            errors.append("Short entry, stop and target levels are inconsistent")
        risk = ((low + high) / 2 - stop) if setup.direction == Direction.LONG else (stop - (low + high) / 2)
        reward = (target - (low + high) / 2) if setup.direction == Direction.LONG else ((low + high) / 2 - target)
        if risk <= 0 or reward <= 0:
            errors.append("Risk and reward must both be positive")
        elif setup.risk_reward is not None:
            expected_ratio = (reward / risk).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
            if setup.risk_reward.ratio != expected_ratio:
                errors.append("Risk/reward does not match the supported levels")
        else:
            errors.append("Supported entry, stop and target levels require a risk/reward calculation")
    elif setup.risk_reward is not None:
        errors.append("Risk/reward requires supported entry, stop and target levels")
    if response.evidence_sufficiency == EvidenceSufficiencyLabel.SUFFICIENT and not assess_sufficiency(packet).sufficient:
        errors.append("Response claims sufficient evidence despite deterministic quality gates")
    sufficiency = assess_sufficiency(packet)
    if not sufficiency.sufficient:
        if response.trade_stance in (TradeStance.BUY_SETUP, TradeStance.SELL_SETUP):
            errors.append("Directional setup is prohibited by insufficient evidence gates")
        if not response.missing_information and not any(item.data_quality_warnings for item in response.timeframes):
            errors.append("Insufficient evidence must be reflected in warnings or missing information")
    if response.origin == AnalysisOrigin.DETERMINISTIC_GATE and (response.trade_stance != TradeStance.NO_TRADE or response.validation_status != ValidationState.VERIFIED):
        errors.append("Deterministic insufficient-evidence result must be verified NO TRADE")
    if response.origin == AnalysisOrigin.DETERMINISTIC_GATE:
        expected_refs = tuple(assess_sufficiency(packet).usable_evidence_ids)
        if (sufficiency.sufficient or response.bias != Bias.NEUTRAL
                or response.rationale != (Claim(text="NO TRADE — DATA NOT VERIFIED. Required evidence gates did not pass.", evidence_ids=expected_refs),)
                or response.missing_information != tuple(Claim(text=warning, evidence_ids=expected_refs) for warning in sufficiency.warnings)
                or response.setup != SetupAssessment()
                or any(item.direction != "UNAVAILABLE" or item.supporting_evidence_ids or item.conflicting_evidence_ids
                       or item.structure or item.data_quality_warnings
                       for item in response.timeframes)):
            errors.append("Deterministic gate result must match the packet's NO TRADE quality assessment")
    return ResponseValidation(valid=not errors, errors=tuple(dict.fromkeys(errors)),
                              status=ValidationState.VERIFIED if not errors else ValidationState.INVALID)


def _all_level_refs(response: AnalysisResponse) -> tuple[PriceLevel, ...]:
    setup = response.setup
    return tuple(level for level in (setup.entry_zone.low if setup.entry_zone else None,
                                     setup.entry_zone.high if setup.entry_zone else None,
                                     setup.stop_loss, setup.target) if level is not None)


def deterministic_no_trade(packet: EvidencePacket) -> AnalysisResponse:
    assessment = assess_sufficiency(packet)
    if assessment.sufficient:
        raise ValueError("A deterministic data-not-verified report requires insufficient evidence")
    references = tuple(item for item in assessment.usable_evidence_ids)
    rationale = (Claim(text="NO TRADE — DATA NOT VERIFIED. Required evidence gates did not pass.", evidence_ids=references),)
    result = AnalysisResponse(
        analysis_id=packet.analysis_id, origin=AnalysisOrigin.DETERMINISTIC_GATE,
        bias=Bias.NEUTRAL, trade_stance=TradeStance.NO_TRADE, rationale=rationale,
        evidence_sufficiency=EvidenceSufficiencyLabel.INSUFFICIENT,
        timeframes=tuple(TimeframeAnalysis(timeframe=item.timeframe,
            direction="UNAVAILABLE",
            supporting_evidence_ids=())
            for item in packet.timeframes),
        missing_information=tuple(Claim(text=warning, evidence_ids=references) for warning in assessment.warnings),
        validation_status=ValidationState.VERIFIED,
    )
    return result

