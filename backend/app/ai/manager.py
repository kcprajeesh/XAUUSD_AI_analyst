from dataclasses import dataclass
from enum import StrEnum

from app.ai.config import AIConfiguration, ModelConfig, ProviderConfig, Protocol, resolve_secret


class ProviderStatus(StrEnum):
    NOT_CONFIGURED = "not_configured"
    DISABLED = "disabled"
    MISSING_CREDENTIAL = "missing_credential"
    UNVERIFIED_MODEL = "unverified_model"
    UNSUPPORTED_PROTOCOL = "unsupported_protocol"
    SECURITY_REJECTION = "configuration_security_rejection"
    CONFIGURED = "configured"


class AIErrorKind(StrEnum):
    NOT_CONFIGURED = "not_configured"
    DISABLED = "disabled"
    MISSING_CREDENTIAL = "missing_credential"
    UNVERIFIED_MODEL = "unverified_model"
    UNSUPPORTED_PROTOCOL = "unsupported_protocol"
    AUTHENTICATION_FAILURE = "authentication_failure"
    QUOTA_EXHAUSTED = "quota_or_credit_exhausted"
    RATE_LIMITED = "rate_limited"
    TIMEOUT = "timeout"
    INVALID_RESPONSE = "invalid_response"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    SECURITY_REJECTION = "configuration_security_rejection"
    PROVIDER_REJECTED = "provider_rejected_request"
    DUPLICATE_REQUEST = "duplicate_request"
    COST_UNKNOWN = "cost_unknown"


class AIProviderError(RuntimeError):
    def __init__(self, kind: AIErrorKind, detail: str, *, status_code: int | None = None):
        super().__init__(detail)
        self.kind = kind
        self.detail = detail
        self.status_code = status_code


@dataclass(frozen=True)
class ResolvedModel:
    provider: ProviderConfig
    model: ModelConfig
    status: ProviderStatus

    def require_usable(self) -> None:
        if self.status == ProviderStatus.UNVERIFIED_MODEL:
            raise AIProviderError(AIErrorKind.UNVERIFIED_MODEL, "Configured model has not been verified")
        if self.status != ProviderStatus.CONFIGURED:
            mapping = {
                ProviderStatus.DISABLED: AIErrorKind.DISABLED,
                ProviderStatus.MISSING_CREDENTIAL: AIErrorKind.MISSING_CREDENTIAL,
                ProviderStatus.UNSUPPORTED_PROTOCOL: AIErrorKind.UNSUPPORTED_PROTOCOL,
                ProviderStatus.SECURITY_REJECTION: AIErrorKind.SECURITY_REJECTION,
            }
            raise AIProviderError(mapping.get(self.status, AIErrorKind.NOT_CONFIGURED),
                                  f"Provider is not usable: {self.status.value}")


class ProviderManager:
    """In-memory provider registry; it never discovers or selects a fallback implicitly."""

    def __init__(self, configuration: AIConfiguration | None = None):
        configuration = configuration or AIConfiguration()
        self._providers = {provider.provider_id: provider for provider in configuration.providers}
        self.default_provider_id = configuration.default_provider_id
        self.fallback_provider_id = configuration.fallback_provider_id
        self.fallback_enabled = False
        self.safeguards = configuration.safeguards

    def register_provider(self, provider: ProviderConfig) -> None:
        self._providers[provider.provider_id] = provider

    def list_providers(self) -> tuple[ProviderConfig, ...]:
        return tuple(self._providers[key] for key in sorted(self._providers))

    def get_provider(self, provider_id: str) -> ProviderConfig:
        try:
            return self._providers[provider_id]
        except KeyError as error:
            raise AIProviderError(AIErrorKind.NOT_CONFIGURED, "Requested provider is not configured") from error

    def set_enabled(self, provider_id: str, enabled: bool) -> None:
        provider = self.get_provider(provider_id)
        values = provider.model_dump(mode="python")
        values["enabled"] = enabled
        self._providers[provider_id] = ProviderConfig.model_validate(values)

    def register_model(self, provider_id: str, model: ModelConfig, *, make_default: bool = False) -> None:
        provider = self.get_provider(provider_id)
        models = {item.model_id: item for item in provider.models}
        models[model.model_id] = model
        values = provider.model_dump(mode="python")
        values["models"] = tuple(models.values())
        if make_default or values["default_model_id"] is None:
            values["default_model_id"] = model.model_id
        self._providers[provider_id] = ProviderConfig.model_validate(values)

    def set_default(self, provider_id: str, model_id: str | None = None) -> None:
        provider = self.get_provider(provider_id)
        chosen = model_id or provider.default_model_id
        if chosen is None or chosen not in {model.model_id for model in provider.models}:
            raise AIProviderError(AIErrorKind.NOT_CONFIGURED, "Requested default model is not configured")
        self.default_provider_id = provider_id
        if chosen != provider.default_model_id:
            self.register_model(provider_id, next(m for m in provider.models if m.model_id == chosen), make_default=True)

    def status(self, provider_id: str, model_id: str | None = None) -> ProviderStatus:
        provider = self._providers.get(provider_id)
        if provider is None:
            return ProviderStatus.NOT_CONFIGURED
        if not provider.enabled:
            return ProviderStatus.DISABLED
        chosen = model_id or provider.default_model_id
        model = next((item for item in provider.models if item.model_id == chosen), None)
        if model is None:
            return ProviderStatus.NOT_CONFIGURED
        try:
            resolve_secret(provider.secret_env)
        except RuntimeError:
            return ProviderStatus.MISSING_CREDENTIAL
        if not model.verified:
            return ProviderStatus.UNVERIFIED_MODEL
        if provider.protocol != Protocol.OPENAI_CHAT_COMPLETIONS:
            return ProviderStatus.UNSUPPORTED_PROTOCOL
        try:
            check = provider.endpoint_check()
        except ValueError:
            return ProviderStatus.SECURITY_REJECTION
        if not check.is_local and not check.dns_verified:
            return ProviderStatus.SECURITY_REJECTION
        return ProviderStatus.CONFIGURED

    def resolve(self, provider_id: str | None = None, model_id: str | None = None) -> ResolvedModel:
        selected_provider = provider_id or self.default_provider_id
        if selected_provider is None:
            raise AIProviderError(AIErrorKind.NOT_CONFIGURED, "No default provider is configured")
        provider = self.get_provider(selected_provider)
        selected_model = model_id or provider.default_model_id
        model = next((item for item in provider.models if item.model_id == selected_model), None)
        if model is None:
            raise AIProviderError(AIErrorKind.NOT_CONFIGURED, "Requested model is not configured for this provider")
        resolved = ResolvedModel(provider, model, self.status(selected_provider, selected_model))
        if resolved.status != ProviderStatus.UNVERIFIED_MODEL:
            resolved.require_usable()
        return resolved

