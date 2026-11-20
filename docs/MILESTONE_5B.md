# Milestone 5B — Multi-Provider AI Infrastructure

**Status:** Offline infrastructure only. No live inference transport, endpoint call, scheduler, analysis engine, market-data request, or dashboard integration is active. AgentRouter / GPT-6.1 Sol is represented as the intended primary but remains unverified and disabled.

The preceding Stage 5A audit was in the conversation and was not saved as a project file. No Milestone 3 report was present in `docs/`; the existing Milestone 1, 2 and 4 reports/rollback records and current project rules were inspected before implementation.

## Implemented architecture

`backend/app/ai/` contains provider/model configuration, an in-memory registry and a transport-injected OpenAI-compatible Chat Completions adapter. `Settings` can point to an external JSON AI configuration using `XAUUSD_AI_CONFIG_FILE`; `Settings.load_ai_configuration()` validates it on explicit use. The existing health app does not load this file automatically, and `/health` remains the only application route.

Provider configs store a secret reference such as `AGENTROUTER_API_KEY`, never its value. Model IDs are scoped to their provider. Each model carries verified/unverified metadata and separate capability declarations for structured output, streaming, usage reporting and idempotency. Defaults can be selected globally or overridden per analysis through `ProviderManager.resolve(provider_id, model_id)`. Missing, disabled, unknown, unsupported and unverified configurations fail explicitly. Fallback is off and no fallback request path exists.

`OpenAICompatibleAdapter` prepares the conventional `/chat/completions` URL, JSON messages body, Bearer header and timeout, then calls only a supplied `Transport`. No HTTP transport implementation is present. Tests inject an in-memory mock. The adapter normalizes returned content, optional standard token-usage fields, timeout and HTTP errors; its behavior is a generic adapter contract, not proof that AgentRouter implements it.

`UsageController` provides in-memory request reservation, configured cost/daily/concurrency checks, duplicate suppression, global or per-provider pause/resume and usage metadata records. UTC calendar dates are used for its daily counts. It has no persistence and no real provider records have been created. Unknown cost blocks requests when the corresponding configured limit cannot be evaluated. It does not define a monthly cap, top-ups, purchases, or a billable runtime.

## Provider configuration example

Store configuration outside the repository, for example at `$HOME/.config/xauusd-ai-analyst/providers.json`. This example uses no credential value:

```json
{
  "providers": [
    {
      "provider_id": "agentrouter",
      "display_name": "AgentRouter",
      "provider_type": "agentrouter",
      "enabled": false,
      "api_base_url": "https://co.agentrouter.org/v1",
      "protocol": "openai_chat_completions",
      "secret_env": "AGENTROUTER_API_KEY",
      "models": [
        {
          "model_id": "gpt-6.1-sol",
          "display_name": "GPT-6.1 Sol",
          "verified": false,
          "structured_output": "unverified",
          "streaming": "unverified",
          "usage_reporting": "unverified",
          "idempotency": "unverified"
        }
      ],
      "default_model_id": "gpt-6.1-sol",
      "request_timeout_seconds": 30,
      "settings": {}
    }
  ],
  "default_provider_id": "agentrouter",
  "fallback_provider_id": null,
  "safeguards": {
    "max_cost_per_request_usd": null,
    "daily_request_limit": null,
    "daily_usage_limit": null,
    "daily_usage_unit": null,
    "max_concurrent_requests": null,
    "duplicate_window_seconds": null,
    "paused": false
  }
}
```

The provider is deliberately disabled; the model is explicitly unverified. Configure a path in the backend process environment with `XAUUSD_AI_CONFIG_FILE`. For any future authorized runtime, set the referenced key in the process environment without putting its value in this JSON, a project `.env`, or a shell history entry. In Termux, keep persistent secret material in the app-private home/config area with restrictive file permissions and inject it into the server process. Do not reuse Codex CLI credentials.

Custom OpenAI-compatible providers use `provider_type: "custom"` or `"openai_compatible"` and `protocol: "openai_chat_completions"`, with their own model IDs and environment reference. HTTPS is required for remote URLs. The `anthropic_messages`, `custom`, and `local` protocol values are representable, but no adapters for them are implemented.

## Endpoint and secret safety

Configuration rejects non-HTTPS remote URLs, embedded URL user/password, query/fragment material, credential-like URL paths, local/private/link-local remote IPs, and local hostname suffixes. Explicit local providers may use a loopback/private IP endpoint but must use the `local` provider type and protocol.

Hostname DNS resolution and redirect destination validation are not implemented. A remote hostname therefore remains a security-rejected provider status until a future transport can validate resolved addresses and every redirect target at connection time. No live transport exists in this milestone. A mock can exercise serialization only; it is not a path to provider inference.

`resolve_secret` reads a referenced environment variable only when explicitly called. Missing-secret errors name the variable reference but never include its value. Prepared-request representations hide headers and body. HTTP error details omit response bodies, which could echo sensitive input. Configuration load failures are sanitized. Do not log raw configuration dictionaries, request headers/bodies, prompts, or provider exception internals.

## Protocol and AgentRouter status

| Capability | Stage 5B status |
| --- | --- |
| OpenAI Chat Completions | Request/response shape implemented against a mock transport only. No production transport. |
| AgentRouter base URL | Configuration example uses the documented OpenAI-compatible base `https://co.agentrouter.org/v1`; this is not an endpoint test. |
| GPT-6.1 Sol ID | Representable as `gpt-6.1-sol`, marked unverified and provider disabled. Account availability and compatibility remain unverified. |
| JSON Schema / structured output | Capability remains `unverified`; adapter does not request it. |
| Streaming | Capability remains `unverified`; not implemented. |
| Usage reporting | Capability remains `unverified`; optional standard token counts are parsed if returned, not assumed. |
| Idempotency | Capability remains `unverified`; no idempotency header or automatic retry. |
| Anthropic Messages | Configuration enum only; unsupported by runtime adapter. |
| Custom native protocol | Configuration enum only; unsupported by runtime adapter. |
| Local inference | Explicit local configuration can be validated; no local adapter or runtime. |

The configured AgentRouter URL and protocol selection follow its [hosted integration guide](https://co.agentrouter.org/portal/guide), which documents the OpenAI-compatible `/v1` base URL and account-scoped model availability. The guide does not establish GPT-6.1 Sol support or the adapter capabilities marked unverified above. No call to the guide's model endpoint or to an inference endpoint was made.

## Usage safeguards

All numerical limits default to unset because the user has not assigned values. A configured per-request cost ceiling requires a caller-supplied estimate; it is not a guarantee against actual cost exceeding an inaccurate estimate. Configured daily usage likewise requires a comparable estimate and blocks when prior/provider cost metadata is unknown. There is no monthly cap. Daily boundaries use UTC in this initial in-memory controller; provider-specific reset times are not implemented.

Automatic top-ups, purchases, paid fallback and silent provider switching are absent. Duplicate suppression is in-memory and is not durable across restart. The usage record model supports local metadata only; no actual request has been recorded.

## Verification

Focused offline AI tests: **28 passed**. Full backend suite: **115 passed**. `.venv/bin/python -m pip check`: **No broken requirements found**. Tests use synthetic credentials and mock transports; they make no network calls. No dependencies or lock files changed.

The frontend and chart/data UI were not changed. The backend route set remains health-only. No scheduled execution, AI output schema for market analysis, deterministic evidence packet, SQLite usage ledger, or fallback mechanism was added.

## Files changed

- Modified `backend/app/config.py` to accept an optional AI configuration path and load validated JSON explicitly.
- Added `backend/app/ai/__init__.py`, `config.py`, `manager.py`, `openai_compatible.py`, and `usage.py`.
- Added `backend/tests/test_ai_infrastructure.py`.
- Added this milestone record.
- No frontend files, market-data modules/schema, dependency files, locks, credentials, or API routes changed.

## Rollback

1. Archive or remove the new `backend/app/ai/`, `backend/tests/test_ai_infrastructure.py`, and this document.
2. Restore `backend/app/config.py` from the pre-Stage-5B copy or remove the `ai_config_file` field and `load_ai_configuration()` method.
3. Remove any user-created external JSON config and process environment references separately; this milestone did not create them or modify credentials.
4. Run the backend tests and `pip check` after rollback. No database migration, provider account change, or deployed state needs reversal.

## Stop boundary

No live inference or API connectivity check was performed. AgentRouter and GPT-6.1 Sol remain unverified. Stage 5C, analysis-engine work, frontend integration and scheduled execution require separate explicit authorization.
