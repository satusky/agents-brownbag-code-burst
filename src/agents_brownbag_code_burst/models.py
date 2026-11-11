"""The shared model factory: ``llm = get_model()``.

Two endpoint shapes are supported:

* Azure OpenAI's OpenAI-compatible endpoint (URL ends in ``/openai/v1``), or any
  other OpenAI-compatible server: uses ``ChatOpenAI(base_url=...)``.
* A classic Azure OpenAI deployment (``https://<name>.openai.azure.com`` plus
  ``OPENAI_API_VERSION``): uses ``AzureChatOpenAI``.

Structured output defaults to ``method="function_calling"``. On the workshop
endpoint, the ``json_schema`` method corrupted ``date`` fields (for example
``2026-11-10`` came back as ``1020-11-10``), while function calling returned
correct dates. Set ``STRUCTURED_OUTPUT_METHOD=json_schema`` to compare.

Reasoning models keep their reasoning to themselves unless asked. Set
``REASONING_SUMMARY=auto`` (or ``concise``/``detailed``) and every model streams a
summary of its reasoning through the Responses API. Off by default.
"""

from __future__ import annotations

from typing import Any

from langchain_openai import AzureChatOpenAI, ChatOpenAI

from agents_brownbag_code_burst.config import get_settings


class ModelNotConfigured(RuntimeError):
    pass


class DemoChatOpenAI(ChatOpenAI):
    """ChatOpenAI whose ``with_structured_output`` uses the configured default method."""

    structured_output_method: str = "function_calling"

    def with_structured_output(self, schema=None, *, method=None, **kwargs: Any):
        return super().with_structured_output(schema, method=method or self.structured_output_method, **kwargs)


class DemoAzureChatOpenAI(AzureChatOpenAI):
    """AzureChatOpenAI with the same structured-output default."""

    structured_output_method: str = "function_calling"

    def with_structured_output(self, schema=None, *, method=None, **kwargs: Any):
        return super().with_structured_output(schema, method=method or self.structured_output_method, **kwargs)


def _is_classic_azure(url: str, api_version: str | None) -> bool:
    return bool(api_version) and "/openai/v1" not in url and ".azure.com" in url


def get_model(**overrides: Any) -> ChatOpenAI:
    """Return a chat model for the configured endpoint.

    Keyword arguments override the defaults, for example
    ``get_model(model="another-deployment", max_retries=0)``.
    """
    s = get_settings()
    if not s.configured:
        raise ModelNotConfigured(
            "Model endpoint is not configured. Set " + ", ".join(s.missing) + " in .env (see .env.example)."
        )
    common: dict[str, Any] = {
        "api_key": s.api_key,
        "max_retries": s.max_retries,
        "timeout": s.timeout,
        "structured_output_method": s.structured_output_method,
    }
    if s.reasoning_summary:  # also switches langchain-openai to the Responses API
        common["reasoning"] = {"summary": s.reasoning_summary}
    if _is_classic_azure(s.base_url, s.api_version):
        params = {"azure_endpoint": s.base_url, "azure_deployment": s.model, "api_version": s.api_version, **common}
        return DemoAzureChatOpenAI(**{**params, **overrides})
    params = {"base_url": s.base_url, "model": s.model, **common}
    return DemoChatOpenAI(**{**params, **overrides})
