from enum import StrEnum
import ipaddress
import json
import math
import os
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


class Protocol(StrEnum):
    OPENAI_CHAT_COMPLETIONS = "openai_chat_completions"
    ANTHROPIC_MESSAGES = "anthropic_messages"
    CUSTOM = "custom"
    LOCAL = "local"


class ProviderType(StrEnum):
    AGENTROUTER = "agentrouter"
    OPENAI_COMPATIBLE = "openai_compatible"
    CUSTOM = "custom"
    LOCAL = "local"


class Capability(StrEnum):
    UNVERIFIED = "unverified"
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"


class ModelConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    model_id: str = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")
    display_name: str = Field(min_length=1, max_length=160)
    verified: bool = False
    structured_output: Capability = Capability.UNVERIFIED
    streaming: Capability = Capability.UNVERIFIED
    usage_reporting: Capability = Capability.UNVERIFIED
    idempotency: Capability = Capability.UNVERIFIED


class EndpointCheck(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    url: str
    is_local: bool
    dns_verified: bool


def validate_endpoint(url: str, *, local_provider: bool = False) -> EndpointCheck:
    if not isinstance(url, str) or not url or url != url.strip():
        raise ValueError("API base URL must be a non-empty URL without surrounding whitespace")
    try:
        parts = urlsplit(url)
        host = parts.hostname
        port = parts.port
    except ValueError:
        raise ValueError("API base URL is invalid") from None
    if parts.scheme not in {"https", "http"} or not host or parts.username or parts.password:
        raise ValueError("API base URL must use HTTPS and cannot contain credentials")
    if parts.query or parts.fragment:
        raise ValueError("API base URL cannot contain a query or fragment")
    if port is not None and not 1 <= port <= 65535:
        raise ValueError("API base URL port is invalid")

    normalized_host = host.rstrip(".").lower()
    decoded_path = unquote(parts.path)
    if re.search(r"(api[-_]?key|access[-_]?token|secret|password|authorization|bearer)", decoded_path, re.I):
        raise ValueError("API base URL path cannot contain credential-like material")
    try:
        address = ipaddress.ip_address(normalized_host)
    except ValueError:
        address = None
    is_loopback = normalized_host == "localhost" or normalized_host.endswith(".localhost")
    is_local = is_loopback or bool(address and (address.is_loopback or address.is_private or address.is_link_local))
    if local_provider:
        if not is_local:
            raise ValueError("Local providers must use a loopback or private IP endpoint")
    else:
        if parts.scheme != "https":
            raise ValueError("Remote provider endpoints require HTTPS")
        if is_local or normalized_host.endswith(".local"):
            raise ValueError("Remote provider endpoints cannot target local/private hosts")
        if address and not address.is_global:
            raise ValueError("Remote provider endpoint IP must be globally routable")
        if not re.fullmatch(r"[a-z0-9.-]+", normalized_host) or ".." in normalized_host:
            raise ValueError("Remote provider endpoint hostname is invalid")
    return EndpointCheck(url=url, is_local=is_local, dns_verified=bool(address))


class ProviderConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    provider_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,63}$")
    display_name: str = Field(min_length=1, max_length=120)
    provider_type: ProviderType
    enabled: bool = False
    api_base_url: str
    protocol: Protocol
    secret_env: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{1,127}$")
    models: tuple[ModelConfig, ...] = ()
    default_model_id: str | None = None
    request_timeout_seconds: float = Field(default=30, gt=0, le=600, allow_inf_nan=False)
    settings: dict[str, str | int | float | bool] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_identity_and_endpoint(self) -> "ProviderConfig":
        if len({model.model_id for model in self.models}) != len(self.models):
            raise ValueError("Model IDs must be unique within a provider")
        model_ids = {model.model_id for model in self.models}
        if self.default_model_id is not None and self.default_model_id not in model_ids:
            raise ValueError("Default model must be registered for this provider")
        if (self.provider_type == ProviderType.LOCAL) != (self.protocol == Protocol.LOCAL):
            raise ValueError("Local provider type and local protocol must be selected together")
        validate_endpoint(self.api_base_url, local_provider=self.provider_type == ProviderType.LOCAL)
        unsafe_setting = re.compile(r"(secret|token|password|credential|api.?key|auth)", re.I)
        if any(unsafe_setting.search(key) for key in self.settings):
            raise ValueError("Provider settings cannot contain credential-like fields")
        if any(isinstance(value, float) and not math.isfinite(value) for value in self.settings.values()):
            raise ValueError("Provider settings must contain finite scalar values")
        return self

    def endpoint_check(self) -> EndpointCheck:
        return validate_endpoint(self.api_base_url, local_provider=self.provider_type == ProviderType.LOCAL)


class UsageSafeguards(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    max_cost_per_request_usd: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    daily_request_limit: int | None = Field(default=None, ge=1)
    daily_usage_limit: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    daily_usage_unit: str | None = Field(default=None, pattern=r"^(usd|tokens)$")
    max_concurrent_requests: int | None = Field(default=None, ge=1)
    duplicate_window_seconds: int | None = Field(default=None, ge=1)
    paused: bool = False

    @model_validator(mode="after")
    def usage_unit_required_with_limit(self) -> "UsageSafeguards":
        if (self.daily_usage_limit is None) != (self.daily_usage_unit is None):
            raise ValueError("Daily usage limit and unit must be configured together")
        return self


class AIConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    providers: tuple[ProviderConfig, ...] = ()
    default_provider_id: str | None = None
    fallback_provider_id: str | None = None
    safeguards: UsageSafeguards = Field(default_factory=UsageSafeguards)

    @model_validator(mode="after")
    def valid_provider_selection(self) -> "AIConfiguration":
        provider_ids = [provider.provider_id for provider in self.providers]
        if len(set(provider_ids)) != len(provider_ids):
            raise ValueError("Provider IDs must be unique")
        for provider_id in (self.default_provider_id, self.fallback_provider_id):
            if provider_id is not None and provider_id not in provider_ids:
                raise ValueError("Default and fallback providers must be configured")
        return self


def load_configuration(path: str | Path) -> AIConfiguration:
    """Load non-secret JSON settings; credentials are resolved separately at runtime."""
    try:
        raw = Path(path).read_text(encoding="utf-8")
    except OSError as error:
        raise ValueError("AI configuration file could not be read") from error
    try:
        return AIConfiguration.model_validate_json(raw)
    except (ValidationError, ValueError):
        raise ValueError("AI configuration is invalid; sensitive values were not included") from None


def resolve_secret(environment_name: str | None, environ: dict[str, str] | None = None) -> str:
    if environment_name is None:
        raise RuntimeError("Provider has no credential reference configured")
    value = (os.environ if environ is None else environ).get(environment_name)
    if not value:
        raise RuntimeError(f"Required credential environment variable is missing: {environment_name}")
    return value
