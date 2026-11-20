from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from threading import Lock

from pydantic import BaseModel, ConfigDict, Field

from app.ai.config import UsageSafeguards
from app.ai.manager import AIErrorKind, AIProviderError


class UsageRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    request_id: str
    request_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    provider_id: str
    model_id: str
    started_at: datetime
    completed_at: datetime | None = None
    state: str = "started"
    estimated_cost_usd: Decimal | None = Field(default=None, ge=0)
    estimated_usage: Decimal | None = Field(default=None, ge=0)
    actual_cost_usd: Decimal | None = Field(default=None, ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    error_kind: str | None = None


@dataclass(frozen=True)
class Reservation:
    request_id: str
    request_hash: str


class UsageController:
    """In-memory safeguards and metadata ledger; persistence is intentionally deferred."""

    def __init__(self, safeguards: UsageSafeguards | None = None):
        self.safeguards = safeguards or UsageSafeguards()
        self._records: list[UsageRecord] = []
        self._active: dict[str, Reservation] = {}
        self._active_hashes: set[str] = set()
        self._paused_providers: set[str] = set()
        self._lock = Lock()

    @property
    def records(self) -> tuple[UsageRecord, ...]:
        with self._lock:
            return tuple(self._records)

    def pause(self, provider_id: str | None = None) -> None:
        with self._lock:
            if provider_id is None:
                self.safeguards = self.safeguards.model_copy(update={"paused": True})
            else:
                self._paused_providers.add(provider_id)

    def resume(self, provider_id: str | None = None) -> None:
        with self._lock:
            if provider_id is None:
                self.safeguards = self.safeguards.model_copy(update={"paused": False})
            else:
                self._paused_providers.discard(provider_id)

    def reserve(self, *, request_id: str, request_hash: str, provider_id: str, model_id: str,
                estimated_cost_usd: Decimal | None = None, estimated_daily_usage: Decimal | None = None,
                now: datetime | None = None) -> Reservation:
        now = now or datetime.now(UTC)
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("Reservation time must be timezone-aware")
        now = now.astimezone(UTC)
        record = UsageRecord(request_id=request_id, request_hash=request_hash,
            provider_id=provider_id, model_id=model_id, started_at=now,
            estimated_cost_usd=estimated_cost_usd, estimated_usage=estimated_daily_usage)
        estimated_cost_usd = record.estimated_cost_usd
        estimated_daily_usage = record.estimated_usage
        with self._lock:
            policy = self.safeguards
            if policy.paused or provider_id in self._paused_providers:
                raise AIProviderError(AIErrorKind.DISABLED, "AI requests are paused")
            if request_hash in self._active_hashes:
                raise AIProviderError(AIErrorKind.DUPLICATE_REQUEST, "An identical AI request is already running")
            if request_id in self._active or any(item.request_id == request_id for item in self._records):
                raise AIProviderError(AIErrorKind.DUPLICATE_REQUEST, "AI request ID has already been used")
            window = policy.duplicate_window_seconds
            if window is not None and any(
                record.request_hash == request_hash and record.started_at > now - timedelta(seconds=window)
                for record in self._records
            ):
                raise AIProviderError(AIErrorKind.DUPLICATE_REQUEST, "Identical AI request is within the suppression window")
            if policy.max_concurrent_requests is not None and len(self._active) >= policy.max_concurrent_requests:
                raise AIProviderError(AIErrorKind.RATE_LIMITED, "Configured concurrent AI request limit reached")
            today = now.date()
            todays = [record for record in self._records if record.started_at.date() == today]
            if policy.daily_request_limit is not None and len(todays) >= policy.daily_request_limit:
                raise AIProviderError(AIErrorKind.RATE_LIMITED, "Configured daily AI request limit reached")
            if policy.max_cost_per_request_usd is not None:
                if estimated_cost_usd is None:
                    raise AIProviderError(AIErrorKind.COST_UNKNOWN, "Cannot enforce configured per-request cost limit")
                if estimated_cost_usd > Decimal(str(policy.max_cost_per_request_usd)):
                    raise AIProviderError(AIErrorKind.RATE_LIMITED, "Estimated request cost exceeds configured limit")
            if policy.daily_usage_limit is not None:
                if estimated_daily_usage is None:
                    raise AIProviderError(AIErrorKind.COST_UNKNOWN, "Cannot enforce configured daily usage limit")
                unit = policy.daily_usage_unit
                if unit == "usd":
                    settled = [record for record in todays if record.state != "started"]
                    active = [record for record in todays if record.state == "started"]
                    prior = [record.actual_cost_usd for record in settled]
                    pending = [record.estimated_usage for record in active]
                    if any(value is None for value in prior + pending):
                        raise AIProviderError(AIErrorKind.COST_UNKNOWN, "Prior daily cost is unknown")
                else:
                    settled = [record for record in todays if record.state != "started"]
                    active = [record for record in todays if record.state == "started"]
                    if any(record.input_tokens is None or record.output_tokens is None for record in settled):
                        raise AIProviderError(AIErrorKind.COST_UNKNOWN, "Prior daily token usage is unknown")
                    prior = [Decimal(record.input_tokens + record.output_tokens) for record in settled]
                    pending = [record.estimated_usage for record in active]
                    if any(value is None for value in pending):
                        raise AIProviderError(AIErrorKind.COST_UNKNOWN, "Active daily token estimate is unknown")
                total = sum((value for value in prior if value is not None), Decimal(0))
                total += sum((value for value in pending if value is not None), Decimal(0))
                if total + estimated_daily_usage > Decimal(str(policy.daily_usage_limit)):
                    raise AIProviderError(AIErrorKind.RATE_LIMITED, "Estimated daily usage exceeds configured limit")
            reservation = Reservation(request_id, request_hash)
            self._active[request_id] = reservation
            self._active_hashes.add(request_hash)
            self._records.append(record)
            return reservation

    def finish(self, reservation: Reservation, *, actual_cost_usd: Decimal | None = None,
               input_tokens: int | None = None, output_tokens: int | None = None,
               error_kind: str | None = None, now: datetime | None = None) -> UsageRecord:
        now = now or datetime.now(UTC)
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("Completion time must be timezone-aware")
        now = now.astimezone(UTC)
        with self._lock:
            if self._active.get(reservation.request_id) != reservation:
                raise ValueError("Unknown or already completed AI request reservation")
            index = next(i for i, item in enumerate(self._records)
                         if item.request_id == reservation.request_id and item.state == "started")
            record = UsageRecord.model_validate({**self._records[index].model_dump(),
                "completed_at": now, "state": "failed" if error_kind else "completed",
                "actual_cost_usd": actual_cost_usd, "input_tokens": input_tokens,
                "output_tokens": output_tokens, "error_kind": error_kind,
            })
            self._active.pop(reservation.request_id)
            self._active_hashes.discard(reservation.request_hash)
            self._records[index] = record
            return record
