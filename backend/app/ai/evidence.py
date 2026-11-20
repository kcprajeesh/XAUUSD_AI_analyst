"""Provider-neutral, versioned evidence contracts for XAUUSD analysis."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
import re
from typing import Annotated, Literal
from types import MappingProxyType

from pydantic import (AfterValidator, BaseModel, BeforeValidator, ConfigDict, Field,
                      PlainSerializer, StrictInt, model_validator)

from app.data.contracts import UTCInstant, exact_decimal


class EvidenceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


EvidenceDecimal = Annotated[Decimal, BeforeValidator(exact_decimal), Field(allow_inf_nan=False)]
PositivePrice = Annotated[Decimal, BeforeValidator(exact_decimal), Field(gt=0, allow_inf_nan=False)]


class Timeframe(StrEnum):
    D1 = "1D"
    H4 = "4H"
    H1 = "1H"
    M15 = "15M"
    M5 = "5M"


ReadinessLimits = Annotated[
    dict[Timeframe, Annotated[StrictInt, Field(gt=0)]],
    AfterValidator(lambda values: MappingProxyType(dict(values))),
    PlainSerializer(lambda values: dict(values), return_type=dict[Timeframe, int]),
]


class InstrumentType(StrEnum):
    OTC_SPOT = "otc_spot"
    BROKER_CFD = "broker_cfd"
    COMEX_GC = "comex_gc"
    LBMA_BENCHMARK = "lbma_benchmark"


class EvidenceType(StrEnum):
    TREND = "trend"
    DIRECTIONAL_STRUCTURE = "directional_structure"
    SWING_HIGH = "swing_high"
    SWING_LOW = "swing_low"
    BOS = "bos"
    CHOCH = "choch"
    LIQUIDITY_HIGH = "liquidity_high"
    LIQUIDITY_LOW = "liquidity_low"
    LIQUIDITY_SWEEP = "liquidity_sweep"
    FAIR_VALUE_GAP = "fair_value_gap"
    ORDER_BLOCK = "order_block"
    EMA = "ema"
    VWAP = "vwap"
    RSI = "rsi"
    MOMENTUM = "momentum"
    ATR = "atr"
    VOLATILITY = "volatility"
    VOLUME = "volume"
    SESSION = "session"
    KILL_ZONE = "kill_zone"
    SUPPORT = "support"
    RESISTANCE = "resistance"


class VolumeType(StrEnum):
    TICK_COUNT = "tick_count"
    EXCHANGE_TRADED = "exchange_traded_volume"
    CONTRACT = "contract_volume"
    UNKNOWN = "unknown"
    UNSPECIFIED = "unspecified"


class QualityStatus(StrEnum):
    VERIFIED = "verified"
    PROVISIONAL = "provisional"
    INSUFFICIENT = "insufficient_quality"
    STALE = "stale"
    INVALID = "invalid"
    UNSUPPORTED = "unsupported"


class CandleState(StrEnum):
    FORMING = "forming"
    CLOSED = "closed"
    UNVERIFIED = "unverified"


class CandleOrigin(StrEnum):
    NATIVE = "native"
    AGGREGATED = "aggregated"


class TimeframeState(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    UNSUPPORTED = "unsupported"


class DataQualityFlag(StrEnum):
    MISSING_CANDLES = "missing_candles"
    INVALID_CANDLES = "invalid_candles"
    DUPLICATE_CANDLES = "duplicate_candles"
    OUTLIER = "outlier"
    STALE = "stale"
    CONFLICTING_SOURCE = "conflicting_source"
    FORMING_CANDLE = "forming_candle"
    UNSUPPORTED_DERIVATION = "unsupported_derivation"
    INCOMPLETE_CONTEXT = "incomplete_context"
    RETRIEVAL_INCOMPLETE = "retrieval_incomplete"
    UNVERIFIED_TICK_COUNT_RANGE = "unusual_tick_count_range_unverified"


class InstrumentIdentity(EvidenceModel):
    canonical_symbol: Literal["XAUUSD"] = "XAUUSD"
    asset_class: Literal["precious_metal"] = "precious_metal"
    instrument_id: str = Field(min_length=1)
    instrument_type: InstrumentType
    quote_currency: Literal["USD"] = "USD"

    @model_validator(mode="after")
    def qualified_identity(self):
        patterns = {
            InstrumentType.OTC_SPOT: r"^xau-usd:spot-[a-z0-9-]+$",
            InstrumentType.BROKER_CFD: r"^xau-usd:cfd:[a-z0-9-]+$",
            InstrumentType.COMEX_GC: r"^comex:gc:\d{4}-(0[1-9]|1[0-2])$",
            InstrumentType.LBMA_BENCHMARK: r"^lbma:gold:usd:(AM|PM)$",
        }
        if not re.fullmatch(patterns[self.instrument_type], self.instrument_id):
            raise ValueError("Instrument ID must preserve its instrument type and qualifier")
        return self


class SourceIdentity(EvidenceModel):
    source_id: str = Field(min_length=1)
    retrieval_id: str | None = None
    completeness_evidence_id: str | None = None
    instrument: InstrumentIdentity
    provider_id: str = Field(min_length=1)
    feed_id: str = Field(min_length=1)
    series_id: str = Field(min_length=1)
    provider_symbol: str = Field(min_length=1)
    retrieved_at: UTCInstant
    price_normalization: Literal[
        "source_decimal_text", "json_numeric_token_decimal", "float_shortest_roundtrip", "other_documented"
    ]
    source_price_precision: str | None = None


class EvidenceCandle(EvidenceModel):
    candle_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    retrieval_id: str | None = None
    revision_id: str | None = None
    timeframe: Timeframe
    opened_at: UTCInstant
    closed_at: UTCInstant | None = None
    status: CandleState
    origin: CandleOrigin = CandleOrigin.NATIVE
    open: PositivePrice
    high: PositivePrice
    low: PositivePrice
    close: PositivePrice
    volume_value: Annotated[Decimal, BeforeValidator(exact_decimal), Field(ge=0, allow_inf_nan=False)] | None = None
    volume_type: VolumeType = VolumeType.UNSPECIFIED
    source_candle_ids: tuple[str, ...] = ()
    quality_flags: tuple[DataQualityFlag, ...] = ()

    @model_validator(mode="after")
    def validate_candle(self):
        if not (self.low <= self.open <= self.high and self.low <= self.close <= self.high):
            raise ValueError("OHLC must satisfy low <= open/close <= high")
        if self.volume_value is None and self.volume_type in (VolumeType.TICK_COUNT, VolumeType.EXCHANGE_TRADED, VolumeType.CONTRACT):
            raise ValueError("A specified volume type requires an observed volume value")
        if self.closed_at is not None and self.closed_at <= self.opened_at:
            raise ValueError("Candle close must be after its opening")
        duration = {Timeframe.D1: timedelta(days=1), Timeframe.H4: timedelta(hours=4),
                    Timeframe.H1: timedelta(hours=1), Timeframe.M15: timedelta(minutes=15),
                    Timeframe.M5: timedelta(minutes=5)}[self.timeframe]
        if self.closed_at is not None and self.closed_at - self.opened_at != duration:
            raise ValueError("Candle boundaries must match the declared timeframe")
        elapsed = self.opened_at - datetime(1970, 1, 1, tzinfo=UTC)
        if elapsed % duration:
            raise ValueError("Candle opening must align to a UTC timeframe boundary")
        if self.closed_at is None and self.status != CandleState.UNVERIFIED:
            raise ValueError("A candle without a verified boundary must be unverified")
        if self.closed_at is not None and self.status == CandleState.UNVERIFIED:
            raise ValueError("A candle with a known boundary must be forming or closed")
        if self.origin == CandleOrigin.AGGREGATED and not self.source_candle_ids:
            raise ValueError("Aggregated candles must identify their source candles")
        if self.origin == CandleOrigin.NATIVE and self.source_candle_ids:
            raise ValueError("Native candles cannot claim aggregated source candles")
        return self


class TimeframeEvidence(EvidenceModel):
    timeframe: Timeframe
    state: TimeframeState
    origin: CandleOrigin | None = None
    source_ids: tuple[str, ...] = ()
    candles: tuple[EvidenceCandle, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    missing_openings: tuple[UTCInstant, ...] = ()
    quality_flags: tuple[DataQualityFlag, ...] = ()

    @model_validator(mode="after")
    def consistent_state(self):
        if self.state == TimeframeState.AVAILABLE and (not self.candles or self.origin is None):
            raise ValueError("Available timeframes require candles and native/aggregated origin")
        if self.state == TimeframeState.AVAILABLE and len(self.source_ids) != 1:
            raise ValueError("An available timeframe must select exactly one source series")
        if self.state != TimeframeState.AVAILABLE and self.candles:
            raise ValueError("Unavailable timeframes cannot contain usable candles")
        if any(c.timeframe != self.timeframe for c in self.candles):
            raise ValueError("Candle timeframe must match its containing timeframe")
        if self.origin is not None and any(c.origin != self.origin for c in self.candles):
            raise ValueError("Native and aggregated candles cannot be mixed in one timeframe")
        if self.missing_openings and DataQualityFlag.MISSING_CANDLES not in self.quality_flags:
            raise ValueError("Missing candle openings require a missing-candles quality flag")
        return self


class EvidenceRecord(EvidenceModel):
    evidence_id: str = Field(min_length=1)
    evidence_type: EvidenceType
    description: str = Field(min_length=1)
    value: EvidenceDecimal | None = None
    units: str | None = None
    volume_type: VolumeType | None = None
    timeframe: Timeframe | None = None
    observed_at: UTCInstant
    source_ids: tuple[str, ...] = Field(min_length=1)
    calculation_method: str | None = None
    quality: QualityStatus
    candle_refs: tuple[str, ...] = ()

    @model_validator(mode="after")
    def derived_has_method(self):
        if self.evidence_type == EvidenceType.VOLUME and self.volume_type is None:
            raise ValueError("Volume evidence requires explicit volume semantics")
        if self.evidence_type != EvidenceType.VOLUME and self.volume_type is not None:
            raise ValueError("Volume semantics are valid only for volume evidence")
        if self.evidence_type != EvidenceType.VOLUME:
            if not self.calculation_method:
                raise ValueError("Derived observations require a calculation method")
        return self


class EvidencePacket(EvidenceModel):
    schema_version: Literal["1.0"] = "1.0"
    analysis_id: str = Field(min_length=1)
    analysis_at: UTCInstant
    display_timezone: Literal["Asia/Qatar"] = "Asia/Qatar"
    instrument: InstrumentIdentity
    sources: tuple[SourceIdentity, ...] = Field(min_length=1)
    requested_timeframes: tuple[Timeframe, ...] = Field(min_length=1)
    retrieved_at: UTCInstant
    timeframes: tuple[TimeframeEvidence, ...]
    freshness_max_age_seconds: ReadinessLimits = Field(default_factory=dict, validate_default=True)
    minimum_closed_candles: ReadinessLimits = Field(default_factory=dict, validate_default=True)
    evidence: tuple[EvidenceRecord, ...] = ()
    quality_flags: tuple[DataQualityFlag, ...] = ()

    def with_readiness(self, *, freshness=None, minimum_candles=None):
        """Return a validated packet whose existing requirements can only tighten."""
        values = self.model_dump(mode="python")
        for field, supplied, combine in (
            ("freshness_max_age_seconds", freshness, min),
            ("minimum_closed_candles", minimum_candles, max),
        ):
            if supplied is not None:
                # Validate before merging, including values that a tighter old value would mask.
                supplied = FreshnessPolicy(max_age_seconds=supplied).max_age_seconds
                old = values[field]
                values[field] = {key: combine(old[key], value) if key in old else value
                                 for key, value in dict(old, **supplied).items()}
        return type(self).model_validate(values)

    @model_validator(mode="after")
    def traceable_unique_evidence(self):
        if any(type(value) is not int or value <= 0 for limits in
               (self.freshness_max_age_seconds, self.minimum_closed_candles) for value in limits.values()):
            raise ValueError("Readiness limits must be positive integers")
        if self.retrieved_at > self.analysis_at:
            raise ValueError("Retrieval timestamp cannot follow analysis timestamp")
        if len(set(self.requested_timeframes)) != len(self.requested_timeframes):
            raise ValueError("Requested timeframes must be unique")
        if {item.timeframe for item in self.timeframes} != set(self.requested_timeframes):
            raise ValueError("Each requested timeframe must be represented exactly once")
        if len({item.timeframe for item in self.timeframes}) != len(self.timeframes):
            raise ValueError("Timeframe records must be unique")
        sources = {source.source_id: source for source in self.sources}
        evidence = {item.evidence_id: item for item in self.evidence}
        candles = {c.candle_id: c for tf in self.timeframes for c in tf.candles}
        if len(sources) != len(self.sources) or len(evidence) != len(self.evidence) or len(candles) != sum(len(tf.candles) for tf in self.timeframes):
            raise ValueError("Source, evidence and candle IDs must be unique")
        for tf in self.timeframes:
            if not set(tf.source_ids) <= sources.keys():
                raise ValueError("Timeframe references an unknown source")
            for candle in tf.candles:
                if candle.source_id not in sources or candle.source_id not in tf.source_ids:
                    raise ValueError("Candle must reference a timeframe source")
                source_retrieval = sources[candle.source_id].retrieved_at
                source_retrieval_id = sources[candle.source_id].retrieval_id
                if source_retrieval_id is not None and candle.retrieval_id != source_retrieval_id:
                    raise ValueError("Candle and source retrieval identities must match")
                if source_retrieval > self.retrieved_at:
                    raise ValueError("Source retrieval cannot follow packet retrieval")
                if candle.opened_at > source_retrieval:
                    raise ValueError("Candle opening cannot follow its source retrieval")
                if candle.status == CandleState.CLOSED and (candle.closed_at is None or candle.closed_at > source_retrieval):
                    raise ValueError("A closed candle must have a boundary at/before source retrieval")
                if candle.status == CandleState.FORMING and (candle.closed_at is None or candle.closed_at <= source_retrieval):
                    raise ValueError("Forming candle boundary must follow source retrieval")
                if candle.origin == CandleOrigin.AGGREGATED and not set(candle.source_candle_ids) <= candles.keys():
                    # Source candles may live in another timeframe; this packet must carry them.
                    raise ValueError("Aggregated candle sources must be present in the packet")
                if candle.origin == CandleOrigin.AGGREGATED:
                    inputs = tuple(candles[item] for item in candle.source_candle_ids)
                    if candle.timeframe != Timeframe.H4 or len(inputs) != 4 or len({item.source_id for item in inputs}) != 1 or any(
                        item.timeframe != Timeframe.H1 or item.status != CandleState.CLOSED or item.origin != CandleOrigin.NATIVE
                        for item in inputs
                    ) or inputs[0].source_id != candle.source_id:
                        raise ValueError("Aggregated 4H candles require four native, closed 1H source candles")
                    inputs = tuple(sorted(inputs, key=lambda item: item.opened_at))
                    expected_hour = inputs[0].opened_at.hour
                    if expected_hour not in (0, 4, 8, 12, 16, 20) or any(
                        item.opened_at != inputs[0].opened_at + timedelta(hours=index)
                        for index, item in enumerate(inputs)
                    ):
                        raise ValueError("Aggregated 4H sources must be consecutive and UTC-aligned")
                    if (candle.opened_at != inputs[0].opened_at or candle.closed_at != inputs[-1].closed_at
                            or candle.open != inputs[0].open or candle.high != max(item.high for item in inputs)
                            or candle.low != min(item.low for item in inputs) or candle.close != inputs[-1].close):
                        raise ValueError("Aggregated 4H OHLC and boundaries must match its source candles")
                    if candle.volume_value is not None and (
                        any(item.volume_value is None or item.volume_type != candle.volume_type for item in inputs)
                        or candle.volume_value != sum((item.volume_value for item in inputs if item.volume_value is not None), Decimal(0))
                    ):
                        raise ValueError("Aggregated volume must equal all four same-type source values")
        for item in self.evidence:
            if not set(item.source_ids) <= sources.keys() or not set(item.candle_refs) <= candles.keys():
                raise ValueError("Evidence provenance references must resolve within the packet")
            if item.timeframe is not None and item.candle_refs and any(candles[c].timeframe != item.timeframe for c in item.candle_refs):
                raise ValueError("Evidence candle references must match its timeframe")
            if item.observed_at > self.retrieved_at:
                raise ValueError("Evidence observation cannot follow source retrieval")
            if any(item.observed_at < candles[candle_id].opened_at for candle_id in item.candle_refs):
                raise ValueError("Evidence observation cannot predate a referenced candle")
        for timeframe in self.timeframes:
            if not set(timeframe.evidence_ids) <= evidence.keys():
                raise ValueError("Timeframe references an unknown evidence ID")
            if any(evidence[evidence_id].timeframe not in (None, timeframe.timeframe)
                   for evidence_id in timeframe.evidence_ids):
                raise ValueError("Timeframe evidence references must match its timeframe")
        refs_by_timeframe = {timeframe.timeframe: set(timeframe.evidence_ids) for timeframe in self.timeframes}
        if any(item.timeframe is not None and item.evidence_id not in refs_by_timeframe[item.timeframe]
               for item in self.evidence):
            raise ValueError("Every timeframe-scoped evidence record must be listed by its timeframe")
        return self


class FreshnessPolicy(EvidenceModel):
    """No universal age limit is assumed; set per-timeframe limits when approved."""
    max_age_seconds: ReadinessLimits = Field(default_factory=dict, validate_default=True)

    @model_validator(mode="after")
    def positive_age_limits(self):
        if any(value <= 0 for value in self.max_age_seconds.values()):
            raise ValueError("Configured freshness limits must be positive")
        return self


class SufficiencyStatus(StrEnum):
    SUFFICIENT = "sufficient"
    PARTIAL = "partial"
    STALE = "stale"
    MISSING_TIMEFRAMES = "missing_timeframes"
    CONFLICTING_INSTRUMENTS = "conflicting_instruments"
    INVALID_CANDLES = "invalid_candles"
    UNSUPPORTED_DERIVATION = "unsupported_derived_indicators"
    FORMING_CANDLES = "forming_candles"
    INCOMPLETE_CONTEXT = "incomplete_multitimeframe_context"


class EvidenceSufficiency(EvidenceModel):
    statuses: tuple[SufficiencyStatus, ...]
    usable_evidence_ids: tuple[str, ...]
    warnings: tuple[str, ...]

    @property
    def sufficient(self) -> bool:
        return self.statuses == (SufficiencyStatus.SUFFICIENT,)


def assess_sufficiency(packet: EvidencePacket, policy: FreshnessPolicy | None = None) -> EvidenceSufficiency:
    if policy is not None and any(
            tf not in packet.freshness_max_age_seconds or value < packet.freshness_max_age_seconds[tf]
            for tf, value in policy.max_age_seconds.items()):
        raise ValueError("Bind stricter freshness with packet.with_readiness before assessment")
    policy = policy or FreshnessPolicy(max_age_seconds=packet.freshness_max_age_seconds)
    flags = set(packet.quality_flags)
    flags.update(flag for timeframe in packet.timeframes for flag in timeframe.quality_flags)
    flags.update(flag for timeframe in packet.timeframes for candle in timeframe.candles for flag in candle.quality_flags)
    warnings: list[str] = []
    statuses: set[SufficiencyStatus] = set()
    if any(source.instrument != packet.instrument for source in packet.sources) or DataQualityFlag.CONFLICTING_SOURCE in flags:
        statuses.add(SufficiencyStatus.CONFLICTING_INSTRUMENTS)
        warnings.append("Source instrument identities conflict; feeds were not merged as equivalent.")
    if any(tf.state != TimeframeState.AVAILABLE for tf in packet.timeframes):
        statuses.add(SufficiencyStatus.MISSING_TIMEFRAMES)
        warnings.append("One or more requested timeframes are unavailable or unsupported.")
    if DataQualityFlag.INVALID_CANDLES in flags:
        statuses.add(SufficiencyStatus.INVALID_CANDLES)
        warnings.append("Invalid candle data is present in the quality report.")
    if DataQualityFlag.STALE in flags or any(item.quality == QualityStatus.STALE for item in packet.evidence):
        statuses.add(SufficiencyStatus.STALE)
        warnings.append("Evidence is explicitly marked stale.")
    if DataQualityFlag.UNSUPPORTED_DERIVATION in flags or any(
            item.quality == QualityStatus.UNSUPPORTED and item.evidence_type != EvidenceType.VWAP
            for item in packet.evidence):
        statuses.add(SufficiencyStatus.UNSUPPORTED_DERIVATION)
        warnings.append("One or more derived observations are unsupported.")
    if any(c.status != CandleState.CLOSED for tf in packet.timeframes for c in tf.candles):
        statuses.add(SufficiencyStatus.FORMING_CANDLES)
        warnings.append("Forming or unverified candles are present.")
    if DataQualityFlag.INCOMPLETE_CONTEXT in flags:
        statuses.add(SufficiencyStatus.INCOMPLETE_CONTEXT)
        warnings.append("Multi-timeframe context is explicitly incomplete.")
    if DataQualityFlag.RETRIEVAL_INCOMPLETE in flags:
        statuses.add(SufficiencyStatus.INCOMPLETE_CONTEXT)
        warnings.append("Historical retrieval did not complete successfully.")
    if DataQualityFlag.UNVERIFIED_TICK_COUNT_RANGE in flags:
        warnings.append("Provider tick-count range is unusual and unverified.")
    if flags & {DataQualityFlag.MISSING_CANDLES, DataQualityFlag.DUPLICATE_CANDLES, DataQualityFlag.OUTLIER}:
        statuses.add(SufficiencyStatus.PARTIAL)
        warnings.append("Candle coverage or quality is partial and must be reviewed.")
    for tf in packet.timeframes:
        age_limit = policy.max_age_seconds.get(tf.timeframe)
        embedded_limit = packet.freshness_max_age_seconds.get(tf.timeframe)
        if embedded_limit is not None:
            age_limit = min(age_limit, embedded_limit) if age_limit is not None else embedded_limit
        closed = tuple(c for c in tf.candles if c.status == CandleState.CLOSED)
        minimum = packet.minimum_closed_candles.get(tf.timeframe)
        if age_limit is None or minimum is None or len(closed) < minimum:
            statuses.add(SufficiencyStatus.INCOMPLETE_CONTEXT)
            warnings.append("Requested timeframe freshness/depth configuration is missing or closed-candle depth is insufficient.")
        if age_limit is not None and closed:
            latest = max(c.closed_at for c in closed)
            if (packet.analysis_at - latest).total_seconds() > age_limit:
                statuses.add(SufficiencyStatus.STALE)
                warnings.append("Requested timeframe evidence exceeds its configured freshness limit.")
    usable = tuple(item.evidence_id for item in packet.evidence
                   if item.quality == QualityStatus.VERIFIED
                   and all(next(s for s in packet.sources if s.source_id == source_id).instrument == packet.instrument
                           for source_id in item.source_ids))
    if not usable and not statuses:
        statuses.add(SufficiencyStatus.PARTIAL)
        warnings.append("No verified derived or observed evidence is available for interpretation.")
    if any(item.quality != QualityStatus.VERIFIED and item.evidence_type not in
           (EvidenceType.VOLUME, EvidenceType.VWAP)
           for item in packet.evidence) and not statuses:
        statuses.add(SufficiencyStatus.PARTIAL)
        warnings.append("Evidence includes provisional or insufficient-quality observations.")
    if not statuses:
        statuses.add(SufficiencyStatus.SUFFICIENT)
    elif statuses == {SufficiencyStatus.FORMING_CANDLES}:
        statuses.add(SufficiencyStatus.PARTIAL)
    return EvidenceSufficiency(statuses=tuple(sorted(statuses, key=lambda value: value.value)),
                               usable_evidence_ids=usable, warnings=tuple(warnings))
