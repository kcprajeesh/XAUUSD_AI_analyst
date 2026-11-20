import json
import hashlib
import traceback
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.ai.config import (AIConfiguration, Capability, ModelConfig, Protocol,
                           ProviderConfig, ProviderType, UsageSafeguards,
                           load_configuration, resolve_secret, validate_endpoint)
from app.ai.manager import AIErrorKind, AIProviderError, ProviderManager, ProviderStatus, ResolvedModel
from app.ai.openai_compatible import (AIRequest, OpenAICompatibleAdapter,
                                      TransportResponse)
from app.ai.usage import UsageController
from app.config import Settings


def provider(**changes):
    values = {
        "provider_id": "test_remote", "display_name": "Test Remote",
        "provider_type": ProviderType.OPENAI_COMPATIBLE, "enabled": True,
        "api_base_url": "https://8.8.8.8/v1",
        "protocol": Protocol.OPENAI_CHAT_COMPLETIONS,
        "secret_env": "TEST_AI_KEY",
        "models": (ModelConfig(model_id="test/model", display_name="Test Model", verified=True),),
        "default_model_id": "test/model",
    }
    values.update(changes)
    return ProviderConfig(**values)


class MockTransport:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.request = None

    def send(self, request):
        self.request = request
        if self.error:
            raise self.error
        return self.response


def request():
    return AIRequest(request_id="offline-1", messages=({"role": "user", "content": "hello"},))


def request_hash(value):
    return hashlib.sha256(value.encode()).hexdigest()


def test_provider_configuration_and_agentrouter_remains_unverified(monkeypatch):
    monkeypatch.delenv("AGENTROUTER_API_KEY", raising=False)
    p = ProviderConfig(provider_id="agentrouter", display_name="AgentRouter",
        provider_type="agentrouter", api_base_url="https://co.agentrouter.org/v1",
        protocol="openai_chat_completions", secret_env="AGENTROUTER_API_KEY",
        models=(ModelConfig(model_id="gpt-6.1-sol", display_name="GPT-6.1 Sol"),),
        default_model_id="gpt-6.1-sol")
    manager = ProviderManager(AIConfiguration(providers=(p,), default_provider_id="agentrouter"))
    assert manager.status("agentrouter") == ProviderStatus.DISABLED
    with pytest.raises(AIProviderError) as disabled:
        manager.resolve()
    assert disabled.value.kind == AIErrorKind.DISABLED
    manager.set_enabled("agentrouter", True)
    assert manager.status("agentrouter") == ProviderStatus.MISSING_CREDENTIAL
    monkeypatch.setenv("AGENTROUTER_API_KEY", "synthetic-only")
    assert manager.resolve().status == ProviderStatus.UNVERIFIED_MODEL
    with pytest.raises(AIProviderError) as error:
        manager.resolve(model_id="absent")
    assert error.value.kind == AIErrorKind.NOT_CONFIGURED
    assert manager.fallback_enabled is False
    assert manager.fallback_provider_id is None


def test_registry_registration_default_override_and_disabled_rejection(monkeypatch):
    monkeypatch.setenv("TEST_AI_KEY", "synthetic-secret")
    manager = ProviderManager(AIConfiguration(providers=(provider(),), default_provider_id="test_remote"))
    second = ModelConfig(model_id="other", display_name="Other", verified=True)
    manager.register_model("test_remote", second)
    assert manager.resolve(model_id="other").model == second
    manager.set_default("test_remote", "other")
    assert manager.resolve().model == second
    manager.register_provider(provider(provider_id="another", display_name="Another"))
    assert [p.provider_id for p in manager.list_providers()] == ["another", "test_remote"]
    assert manager.resolve("another", "test/model").provider.provider_id == "another"
    with pytest.raises(AIProviderError):
        manager.resolve("missing")
    manager.set_enabled("test_remote", False)
    with pytest.raises(AIProviderError) as error:
        manager.resolve()
    assert error.value.kind == AIErrorKind.DISABLED


@pytest.mark.parametrize("url", [
    "http://remote.example/v1", "https://user:pass@example.com/v1",
    "file:///tmp/provider", "https://localhost/v1", "https://api.local/v1",
    "https://127.0.0.1/v1", "https://10.0.0.2/v1", "https://169.254.1.2/v1",
    "https://example.com/v1?api_key=x", "https://example.com/v1#frag",
    "https://example.com/v1/access_token/secret-value",
])
def test_unsafe_remote_endpoints_rejected(url):
    with pytest.raises(ValueError):
        validate_endpoint(url)


def test_invalid_endpoint_port_is_not_exposed_in_error_traceback():
    sentinel = "sk-synthetic-endpoint-port"
    with pytest.raises(ValueError) as error:
        validate_endpoint(f"https://8.8.8.8:{sentinel}/v1")
    assert str(error.value) == "API base URL is invalid"
    assert sentinel not in "".join(traceback.format_exception(error.value))


def test_local_endpoint_requires_explicit_local_provider():
    check = validate_endpoint("http://127.0.0.1:1234/v1", local_provider=True)
    assert check.is_local
    with pytest.raises(ValueError):
        validate_endpoint("http://127.0.0.1:1234/v1")
    with pytest.raises(ValidationError):
        provider(provider_type="local", protocol="local", api_base_url="http://example.com")


def test_hostname_requires_dns_validation_before_runtime_status(monkeypatch):
    monkeypatch.setenv("TEST_AI_KEY", "synthetic-secret")
    configured = provider(api_base_url="https://custom.example/v1")
    manager = ProviderManager(AIConfiguration(providers=(configured,), default_provider_id="test_remote"))
    assert manager.status("test_remote") == ProviderStatus.SECURITY_REJECTION
    assert configured.endpoint_check().dns_verified is False


def test_custom_provider_can_be_configured_and_fallback_stays_off(monkeypatch):
    monkeypatch.setenv("TEST_AI_KEY", "synthetic-secret")
    custom = provider(provider_id="custom_api", display_name="Custom API", provider_type="custom",
                      api_base_url="https://custom.example/v1")
    manager = ProviderManager(AIConfiguration(providers=(provider(), custom),
                                                default_provider_id="test_remote",
                                                fallback_provider_id="custom_api"))
    assert manager.fallback_provider_id == "custom_api"
    assert manager.fallback_enabled is False
    assert manager.status("custom_api", "test/model") == ProviderStatus.SECURITY_REJECTION
    with pytest.raises(AIProviderError) as rejected:
        manager.resolve("custom_api", "test/model")
    assert rejected.value.kind == AIErrorKind.SECURITY_REJECTION


def test_secret_resolver_missing_and_secret_not_in_configuration(monkeypatch):
    monkeypatch.delenv("TEST_AI_KEY", raising=False)
    with pytest.raises(RuntimeError, match="TEST_AI_KEY") as error:
        resolve_secret("TEST_AI_KEY")
    assert "synthetic-secret" not in str(error.value)
    configured = provider()
    assert "synthetic-secret" not in configured.model_dump_json()
    assert "synthetic-secret" not in repr(configured)


def test_missing_secret_is_normalized_and_not_echoed():
    resolved = ResolvedModel(provider(), provider().models[0], ProviderStatus.CONFIGURED)
    with pytest.raises(AIProviderError) as error:
        OpenAICompatibleAdapter().prepare(request(), resolved, environ={})
    assert error.value.kind == AIErrorKind.MISSING_CREDENTIAL
    assert "TEST_AI_KEY" not in str(error.value)


def test_mocked_openai_request_and_success_normalization():
    p = provider()
    resolved = ResolvedModel(p, p.models[0], ProviderStatus.CONFIGURED)
    body = json.dumps({"choices": [{"message": {"content": "evidence needed"}}],
                       "usage": {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14}}).encode()
    transport = MockTransport(TransportResponse(200, body))
    result = OpenAICompatibleAdapter().complete(request(), resolved, transport,
                                                 environ={"TEST_AI_KEY": "synthetic-secret"})
    assert transport.request.url == "https://8.8.8.8/v1/chat/completions"
    assert transport.request.timeout_seconds == 30
    assert transport.request.headers["Authorization"] == "Bearer synthetic-secret"
    assert json.loads(transport.request.body) == {
        "model": "test/model", "messages": [{"role": "user", "content": "hello"}],
    }
    assert result.provider_id == "test_remote"
    assert result.model_id == "test/model"
    assert result.usage.total_tokens == 14
    assert "synthetic-secret" not in repr(transport.request)
    assert "synthetic-secret" not in result.model_dump_json()


def test_mocked_malformed_timeout_and_provider_errors():
    adapter = OpenAICompatibleAdapter()
    p = provider()
    resolved = ResolvedModel(p, p.models[0], ProviderStatus.CONFIGURED)
    args = {"environ": {"TEST_AI_KEY": "synthetic-secret"}}
    with pytest.raises(AIProviderError) as malformed:
        adapter.complete(request(), resolved, MockTransport(TransportResponse(200, b"{}")), **args)
    assert malformed.value.kind == AIErrorKind.INVALID_RESPONSE
    with pytest.raises(AIProviderError) as timeout:
        adapter.complete(request(), resolved, MockTransport(error=TimeoutError()), **args)
    assert timeout.value.kind == AIErrorKind.TIMEOUT
    for status, kind in ((401, AIErrorKind.AUTHENTICATION_FAILURE),
                         (402, AIErrorKind.QUOTA_EXHAUSTED),
                         (403, AIErrorKind.PROVIDER_REJECTED),
                         (404, AIErrorKind.PROVIDER_REJECTED),
                         (409, AIErrorKind.PROVIDER_REJECTED),
                         (429, AIErrorKind.RATE_LIMITED),
                         (503, AIErrorKind.PROVIDER_UNAVAILABLE)):
        with pytest.raises(AIProviderError) as error:
            adapter.complete(request(), resolved, MockTransport(TransportResponse(status, b"secret body")), **args)
        assert error.value.kind == kind
        assert "secret body" not in str(error.value)


@pytest.mark.parametrize("field", ["prompt_tokens", "completion_tokens", "total_tokens"])
@pytest.mark.parametrize("count", [True, False, "14", 14.0, -1])
def test_provider_usage_rejects_coerced_or_negative_counts(field, count):
    payload = {"choices": [{"message": {"content": "synthetic"}}], "usage": {field: count}}
    p = provider()
    with pytest.raises(AIProviderError) as error:
        OpenAICompatibleAdapter().complete(request(), ResolvedModel(p, p.models[0], ProviderStatus.CONFIGURED),
            MockTransport(TransportResponse(200, json.dumps(payload).encode())),
            environ={"TEST_AI_KEY": "synthetic-secret"})
    assert error.value.kind == AIErrorKind.INVALID_RESPONSE


@pytest.mark.parametrize("usage", [[], "unknown", True, 14,
                                  {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 13},
                                  {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 15},
                                  {"prompt_tokens": 10, "total_tokens": 9},
                                  {"completion_tokens": 4, "total_tokens": 3}])
def test_provider_usage_rejects_malformed_or_inconsistent_metadata(usage):
    payload = {"choices": [{"message": {"content": "synthetic"}}], "usage": usage}
    p = provider()
    with pytest.raises(AIProviderError) as error:
        OpenAICompatibleAdapter().complete(request(), ResolvedModel(p, p.models[0], ProviderStatus.CONFIGURED),
            MockTransport(TransportResponse(200, json.dumps(payload).encode())),
            environ={"TEST_AI_KEY": "synthetic-secret"})
    assert error.value.kind == AIErrorKind.INVALID_RESPONSE


@pytest.mark.parametrize("usage", [None, {}, {"prompt_tokens": 0}, {"completion_tokens": 4},
                                  {"total_tokens": 14}, {"prompt_tokens": 10, "total_tokens": 14}])
def test_provider_usage_preserves_explicit_unknowns_and_partial_counts(usage):
    payload = {"choices": [{"message": {"content": "synthetic"}}], "usage": usage}
    p = provider()
    result = OpenAICompatibleAdapter().complete(request(), ResolvedModel(p, p.models[0], ProviderStatus.CONFIGURED),
        MockTransport(TransportResponse(200, json.dumps(payload).encode())),
        environ={"TEST_AI_KEY": "synthetic-secret"})
    if usage is None:
        assert result.usage is None
    else:
        assert result.usage.model_dump() == {"input_tokens": usage.get("prompt_tokens"),
                                             "output_tokens": usage.get("completion_tokens"),
                                             "total_tokens": usage.get("total_tokens")}


@pytest.mark.parametrize("body", [
    '{"choices":[{"message":{"content":"synthetic"}}]}'.encode("utf-16"),
    b'{"choices":[{"message":{"content":"sk-synthetic-secret","content":"synthetic"}}]}',
    b'{"choices":[{"message":{"content":"synthetic"}}],"usage":{"prompt_tokens":10,"prompt_tokens":1}}',
    b'{"choices":[{"message":{"content":"synthetic"}}],"extra":NaN}',
    b'{"choices":[{"message":{"content":"synthetic"}}],"extra":Infinity}',
    b'{"choices":[{"message":{"content":"\\ud800"}}]}',
])
def test_provider_json_rejects_ambiguous_or_non_utf8_documents_without_echoing_body(body):
    p = provider()
    with pytest.raises(AIProviderError) as error:
        OpenAICompatibleAdapter().complete(request(), ResolvedModel(p, p.models[0], ProviderStatus.CONFIGURED),
            MockTransport(TransportResponse(200, body)), environ={"TEST_AI_KEY": "synthetic-secret"})
    assert error.value.kind == AIErrorKind.INVALID_RESPONSE
    assert "sk-synthetic-secret" not in str(error.value)


@pytest.mark.parametrize("exception,kind", [(TimeoutError, AIErrorKind.TIMEOUT),
                                           (OSError, AIErrorKind.PROVIDER_UNAVAILABLE)])
def test_transport_failure_traceback_does_not_expose_provider_details(exception, kind):
    sentinel = "sk-synthetic-transport-detail"
    p = provider()
    with pytest.raises(AIProviderError) as error:
        OpenAICompatibleAdapter().complete(request(), ResolvedModel(p, p.models[0], ProviderStatus.CONFIGURED),
            MockTransport(error=exception(sentinel)), environ={"TEST_AI_KEY": "synthetic-secret"})
    assert error.value.kind == kind
    assert sentinel not in "".join(traceback.format_exception(error.value))


def test_unsupported_protocol_is_explicit():
    p = provider(protocol=Protocol.ANTHROPIC_MESSAGES)
    resolved = ResolvedModel(p, p.models[0], ProviderStatus.UNSUPPORTED_PROTOCOL)
    with pytest.raises(AIProviderError) as error:
        OpenAICompatibleAdapter().prepare(request(), resolved, environ={"TEST_AI_KEY": "synthetic-secret"})
    assert error.value.kind == AIErrorKind.UNSUPPORTED_PROTOCOL


def test_configuration_file_and_environment_path(tmp_path, monkeypatch):
    path = tmp_path / "ai.json"
    path.write_text(json.dumps({"providers": [], "default_provider_id": None,
                                "fallback_provider_id": None, "safeguards": {}}))
    assert load_configuration(path) == AIConfiguration()
    monkeypatch.setenv("XAUUSD_AI_CONFIG_FILE", str(path))
    assert Settings.from_environment().load_ai_configuration() == AIConfiguration()


def test_invalid_configuration_error_does_not_echo_secret_value(tmp_path):
    sentinel = "sk-synthetic-never-log-this"
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps({"providers": [{"secret_env": sentinel}]}))
    with pytest.raises(ValueError) as error:
        load_configuration(path)
    assert sentinel not in str(error.value)


def test_safeguard_configuration_has_no_invented_limits():
    policy = UsageSafeguards()
    assert policy.max_cost_per_request_usd is None
    assert policy.daily_request_limit is None
    assert policy.daily_usage_limit is None
    assert policy.max_concurrent_requests is None
    assert policy.duplicate_window_seconds is None
    assert policy.paused is False
    with pytest.raises(ValidationError):
        UsageSafeguards(daily_usage_limit=100)
    with pytest.raises(ValidationError):
        UsageSafeguards(max_cost_per_request_usd=float("nan"))


def test_usage_duplicate_pause_limits_and_metadata():
    now = datetime(2026, 11, 18, tzinfo=UTC)
    controller = UsageController(UsageSafeguards(daily_request_limit=2, max_concurrent_requests=1,
                                                   duplicate_window_seconds=60))
    first = controller.reserve(request_id="1", request_hash=request_hash("hash-1"), provider_id="p", model_id="m", now=now)
    with pytest.raises(AIProviderError) as duplicate:
        controller.reserve(request_id="2", request_hash=request_hash("hash-1"), provider_id="p", model_id="m", now=now)
    assert duplicate.value.kind == AIErrorKind.DUPLICATE_REQUEST
    with pytest.raises(AIProviderError) as concurrent:
        controller.reserve(request_id="2", request_hash=request_hash("hash-2"), provider_id="p", model_id="m", now=now)
    assert concurrent.value.kind == AIErrorKind.RATE_LIMITED
    record = controller.finish(first, actual_cost_usd=Decimal("0.25"), input_tokens=9,
                               output_tokens=3, now=now + timedelta(seconds=1))
    assert record.provider_id == "p" and record.model_id == "m"
    with pytest.raises(AIProviderError):
        controller.reserve(request_id="3", request_hash=request_hash("hash-1"), provider_id="p", model_id="m",
                           now=now + timedelta(seconds=2))
    controller.pause()
    with pytest.raises(AIProviderError) as paused:
        controller.reserve(request_id="4", request_hash=request_hash("hash-4"), provider_id="p", model_id="m", now=now)
    assert paused.value.kind == AIErrorKind.DISABLED
    controller.resume()


def test_provider_pause_and_resume_is_scoped():
    controller = UsageController()
    controller.pause("provider-a")
    with pytest.raises(AIProviderError):
        controller.reserve(request_id="a", request_hash=request_hash("a"), provider_id="provider-a", model_id="m")
    reservation = controller.reserve(request_id="b", request_hash=request_hash("b"), provider_id="provider-b", model_id="m")
    controller.finish(reservation)
    controller.resume("provider-a")
    reservation = controller.reserve(request_id="c", request_hash=request_hash("c"), provider_id="provider-a", model_id="m")
    controller.finish(reservation)


def test_cost_unknown_blocks_when_configured_and_monthly_cap_absent():
    controller = UsageController(UsageSafeguards(max_cost_per_request_usd=1))
    with pytest.raises(AIProviderError) as error:
        controller.reserve(request_id="1", request_hash=request_hash("h"), provider_id="p", model_id="m")
    assert error.value.kind == AIErrorKind.COST_UNKNOWN
    permitted = controller.reserve(request_id="1", request_hash=request_hash("h"), provider_id="p", model_id="m",
                                   estimated_cost_usd=Decimal("0.5"))
    controller.finish(permitted, actual_cost_usd=Decimal("0.4"))


def test_daily_usage_limit_accounts_for_prior_and_inflight_usage():
    now = datetime(2026, 11, 18, tzinfo=UTC)
    controller = UsageController(UsageSafeguards(daily_usage_limit=100, daily_usage_unit="tokens"))
    first = controller.reserve(request_id="1", request_hash=request_hash("one"), provider_id="p", model_id="m",
                               estimated_daily_usage=Decimal(60), now=now)
    with pytest.raises(AIProviderError) as error:
        controller.reserve(request_id="2", request_hash=request_hash("two"), provider_id="p", model_id="m",
                           estimated_daily_usage=Decimal(50), now=now)
    assert error.value.kind == AIErrorKind.RATE_LIMITED
    controller.finish(first, input_tokens=40, output_tokens=20, now=now + timedelta(seconds=1))
    with pytest.raises(AIProviderError) as error:
        controller.reserve(request_id="3", request_hash=request_hash("three"), provider_id="p", model_id="m",
                           estimated_daily_usage=Decimal(41), now=now + timedelta(seconds=2))
    assert error.value.kind == AIErrorKind.RATE_LIMITED


@pytest.mark.parametrize("cost", [None, Decimal("0.1")])
def test_daily_usd_limit_uses_the_reserved_daily_estimate(cost):
    now = datetime(2026, 11, 18, tzinfo=UTC)
    controller = UsageController(UsageSafeguards(daily_usage_limit=1, daily_usage_unit="usd"))
    first = controller.reserve(request_id="1", request_hash=request_hash("one"), provider_id="p", model_id="m",
                               estimated_cost_usd=cost, estimated_daily_usage=Decimal("0.6"), now=now)
    with pytest.raises(AIProviderError) as error:
        controller.reserve(request_id="2", request_hash=request_hash("two"), provider_id="p", model_id="m",
                           estimated_cost_usd=cost, estimated_daily_usage=Decimal("0.5"), now=now)
    assert error.value.kind == AIErrorKind.RATE_LIMITED
    controller.finish(first, actual_cost_usd=Decimal("0.4"), now=now + timedelta(seconds=1))
    second = controller.reserve(request_id="2", request_hash=request_hash("two"), provider_id="p", model_id="m",
                                estimated_cost_usd=cost, estimated_daily_usage=Decimal("0.5"), now=now)
    controller.finish(second, actual_cost_usd=Decimal("0.5"), now=now + timedelta(seconds=2))
    with pytest.raises(AIProviderError) as error:
        controller.reserve(request_id="3", request_hash=request_hash("three"), provider_id="p", model_id="m",
                           estimated_daily_usage=Decimal("0.11"), now=now)
    assert error.value.kind == AIErrorKind.RATE_LIMITED


@pytest.mark.parametrize("field", ["estimated_cost_usd", "estimated_daily_usage"])
@pytest.mark.parametrize("amount", [Decimal("-1"), Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity")])
def test_invalid_estimates_fail_validation_without_consuming_a_reservation(field, amount):
    controller = UsageController(UsageSafeguards(max_cost_per_request_usd=1,
                                                daily_usage_limit=1, daily_usage_unit="usd"))
    values = {"estimated_cost_usd": Decimal("0.1"), "estimated_daily_usage": Decimal("0.1")}
    with pytest.raises(ValidationError):
        controller.reserve(request_id="1", request_hash=request_hash("one"), provider_id="p", model_id="m",
                           **{**values, field: amount})
    assert controller.records == ()
    reservation = controller.reserve(request_id="1", request_hash=request_hash("one"), provider_id="p", model_id="m",
                                     **values)
    controller.finish(reservation, actual_cost_usd=Decimal("0.1"))


@pytest.mark.parametrize("values", [{"actual_cost_usd": Decimal("-1")}, {"actual_cost_usd": Decimal("NaN")},
                                    {"input_tokens": -1}, {"output_tokens": -1}])
def test_invalid_completion_metadata_preserves_the_active_reservation(values):
    controller = UsageController()
    reservation = controller.reserve(request_id="1", request_hash=request_hash("one"), provider_id="p", model_id="m")
    with pytest.raises(ValidationError):
        controller.finish(reservation, **values)
    assert controller.records[0].state == "started"
    assert controller.finish(reservation, actual_cost_usd=Decimal("0.1"), input_tokens=1, output_tokens=1).state == "completed"
