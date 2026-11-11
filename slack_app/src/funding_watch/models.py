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

The web viewer edits system prompts without touching the graph code: it puts
``{"system_prompts": {default_text: replacement}}`` in the run's ``configurable``
and the model swaps the text in every system message it is sent.
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import SystemMessage
from langchain_core.prompt_values import ChatPromptValue
from langchain_core.runnables import ensure_config
from langchain_openai import AzureChatOpenAI, ChatOpenAI

from funding_watch.config import get_settings


class ModelNotConfigured(RuntimeError):
    pass


class SystemPromptSwap:
    """Replace system-prompt text per run, from ``config["configurable"]["system_prompts"]``.

    The node's config reaches the model through LangGraph's context, so swaps also
    apply inside subgraphs, Send workers and graphs invoked from a node.
    """

    def _convert_input(self, model_input):
        value = super()._convert_input(model_input)
        swaps = ensure_config().get("configurable", {}).get("system_prompts")
        if not swaps or not isinstance(value, ChatPromptValue):
            return value
        pairs = sorted(swaps.items(), key=lambda kv: -len(kv[0]))  # longest first

        def swap(text: str) -> str:
            for old, new in pairs:
                text = text.replace(old, new)
            return text

        return ChatPromptValue(messages=[
            m.model_copy(update={"content": swap(m.content)})
            if isinstance(m, SystemMessage) and isinstance(m.content, str) else m
            for m in value.messages
        ])


class WorkshopChatOpenAI(SystemPromptSwap, ChatOpenAI):
    """ChatOpenAI whose ``with_structured_output`` uses the configured default method."""

    structured_output_method: str = "function_calling"

    def with_structured_output(self, schema=None, *, method=None, **kwargs: Any):
        return super().with_structured_output(schema, method=method or self.structured_output_method, **kwargs)


class WorkshopAzureChatOpenAI(SystemPromptSwap, AzureChatOpenAI):
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
    if _is_classic_azure(s.base_url, s.api_version):
        params = {"azure_endpoint": s.base_url, "azure_deployment": s.model, "api_version": s.api_version, **common}
        return WorkshopAzureChatOpenAI(**{**params, **overrides})
    params = {"base_url": s.base_url, "model": s.model, **common}
    return WorkshopChatOpenAI(**{**params, **overrides})
