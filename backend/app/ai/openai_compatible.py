from dataclasses import dataclass, field
from datetime import UTC, datetime
import json
import socket
from typing import Mapping, Protocol as TypingProtocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.ai.config import Protocol, resolve_secret
from app.ai.manager import AIErrorKind, AIProviderError, ResolvedModel


class Message(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    role: str = Field(pattern=r"^(system|user|assistant)$")
    content: str


class AIRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    request_id: str = Field(min_length=1, max_length=128)
    messages: tuple[Message, ...] = Field(min_length=1)
    provider_id: str | None = None
    model_id: str | None = None


class UsageMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    input_tokens: int | None = Field(default=None, ge=0, strict=True)
    output_tokens: int | None = Field(default=None, ge=0, strict=True)
    total_tokens: int | None = Field(default=None, ge=0, strict=True)

    @model_validator(mode="after")
    def consistent_total(self):
        known = tuple(count for count in (self.input_tokens, self.output_tokens) if count is not None)
        if self.total_tokens is not None and (
            sum(known) > self.total_tokens or (len(known) == 2 and sum(known) != self.total_tokens)
        ):
            raise ValueError("Usage total must agree with the reported component counts")
        return self


class AIResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    request_id: str
    provider_id: str
    model_id: str
    content: str
    created_at: datetime
    usage: UsageMetadata | None = None


@dataclass(frozen=True)
class PreparedRequest:
    url: str
    headers: Mapping[str, str] = field(repr=False)
    body: bytes = field(repr=False)
    timeout_seconds: float


@dataclass(frozen=True)
class TransportResponse:
    status_code: int
    body: bytes
    headers: Mapping[str, str] | None = None


class Transport(TypingProtocol):
    def send(self, request: PreparedRequest) -> TransportResponse: ...


def _unique_fields(pairs):
    fields = {}
    for key, value in pairs:
        if key in fields:
            raise ValueError("Duplicate JSON field")
        fields[key] = value
    return fields


def _invalid_constant(_value):
    raise ValueError("Non-finite JSON number")


class OpenAICompatibleAdapter:
    """Chat Completions serialization/normalization; an injected transport owns all I/O."""

    def prepare(self, request: AIRequest, resolved: ResolvedModel, *, environ: dict[str, str] | None = None) -> PreparedRequest:
        resolved.require_usable()
        provider = resolved.provider
        if provider.protocol != Protocol.OPENAI_CHAT_COMPLETIONS:
            raise AIProviderError(AIErrorKind.UNSUPPORTED_PROTOCOL, "No adapter is implemented for this protocol")
        if request.provider_id is not None and request.provider_id != provider.provider_id:
            raise AIProviderError(AIErrorKind.NOT_CONFIGURED, "Request provider does not match resolved provider")
        if request.model_id is not None and request.model_id != resolved.model.model_id:
            raise AIProviderError(AIErrorKind.NOT_CONFIGURED, "Request model does not match resolved model")
        endpoint = provider.api_base_url.rstrip("/") + "/chat/completions"
        try:
            key = resolve_secret(provider.secret_env, environ)
        except RuntimeError:
            raise AIProviderError(AIErrorKind.MISSING_CREDENTIAL,
                                  "Required provider credential is not available") from None
        payload = {"model": resolved.model.model_id,
                   "messages": [message.model_dump() for message in request.messages]}
        return PreparedRequest(endpoint, {"Authorization": f"Bearer {key}",
                                           "Content-Type": "application/json"},
                               json.dumps(payload, separators=(",", ":")).encode(),
                               provider.request_timeout_seconds)

    def complete(self, request: AIRequest, resolved: ResolvedModel, transport: Transport,
                 *, environ: dict[str, str] | None = None) -> AIResponse:
        prepared = self.prepare(request, resolved, environ=environ)
        try:
            response = transport.send(prepared)
        except (TimeoutError, socket.timeout):
            raise AIProviderError(AIErrorKind.TIMEOUT, "AI provider request timed out") from None
        except OSError:
            raise AIProviderError(AIErrorKind.PROVIDER_UNAVAILABLE, "AI provider transport failed") from None
        if not 200 <= response.status_code < 300:
            raise self._http_error(response.status_code)
        try:
            payload = json.loads(response.body.decode("utf-8"), object_pairs_hook=_unique_fields,
                                 parse_constant=_invalid_constant)
            choice = payload["choices"][0]
            content = choice["message"]["content"]
            if not isinstance(content, str):
                raise ValueError
            content.encode("utf-8")
            usage_raw = payload.get("usage")
            usage = None
            if usage_raw is not None:
                if not isinstance(usage_raw, dict):
                    raise ValueError
                usage = UsageMetadata(input_tokens=usage_raw.get("prompt_tokens"),
                                      output_tokens=usage_raw.get("completion_tokens"),
                                      total_tokens=usage_raw.get("total_tokens"))
        except (ValueError, TypeError, KeyError, IndexError, RecursionError):
            raise AIProviderError(AIErrorKind.INVALID_RESPONSE, "AI provider returned an invalid Chat Completions response") from None
        return AIResponse(request_id=request.request_id, provider_id=resolved.provider.provider_id,
                          model_id=resolved.model.model_id, content=content,
                          created_at=datetime.now(UTC), usage=usage)

    @staticmethod
    def _http_error(status: int) -> AIProviderError:
        if status == 401:
            kind, detail = AIErrorKind.AUTHENTICATION_FAILURE, "AI provider rejected authentication"
        elif status == 402:
            kind, detail = AIErrorKind.QUOTA_EXHAUSTED, "AI provider reports exhausted credits or quota"
        elif status == 429:
            kind, detail = AIErrorKind.RATE_LIMITED, "AI provider rate limit reached"
        elif status >= 500:
            kind, detail = AIErrorKind.PROVIDER_UNAVAILABLE, "AI provider is unavailable"
        else:
            kind, detail = AIErrorKind.PROVIDER_REJECTED, "AI provider rejected the request"
        return AIProviderError(kind, detail, status_code=status)
