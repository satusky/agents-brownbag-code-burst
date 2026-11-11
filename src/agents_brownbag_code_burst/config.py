"""Settings read from environment variables (and a .env file, if present).

| Setting                     | Variable                 | Default          |
|-----------------------------|--------------------------|------------------|
| Endpoint URL                | AZURE_OPENAI_URL         | (required)       |
| API key                     | AZURE_OPENAI_API_KEY     | (required)       |
| Model / deployment name     | TEST_MODEL_NAME          | (required)       |
| API version (classic Azure) | OPENAI_API_VERSION       | unset            |
| Structured output method    | STRUCTURED_OUTPUT_METHOD | function_calling |
| Reasoning summaries         | REASONING_SUMMARY        | off              |
| Retries per model call      | LLM_MAX_RETRIES          | 3                |
| Model call timeout (s)      | LLM_TIMEOUT              | 120              |
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
EXAMPLES_DIR = PROJECT_ROOT / "examples"

# A .env in the current directory wins over the one at the project root.
load_dotenv(Path.cwd() / ".env")
load_dotenv(PROJECT_ROOT / ".env")


def _env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    if value is not None and value.strip() != "":
        return value.strip().strip('"').strip("'")
    return default


@dataclass(frozen=True)
class Settings:
    base_url: str | None
    api_key: str | None
    model: str | None
    api_version: str | None
    structured_output_method: str
    reasoning_summary: str | None  # auto/concise/detailed: models stream reasoning summaries
    max_retries: int
    timeout: float

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.api_key and self.model)

    @property
    def missing(self) -> list[str]:
        names = {"AZURE_OPENAI_URL": self.base_url, "AZURE_OPENAI_API_KEY": self.api_key, "TEST_MODEL_NAME": self.model}
        return [k for k, v in names.items() if not v]


def get_settings() -> Settings:
    """Read settings fresh from the environment on every call."""
    summary = _env("REASONING_SUMMARY")
    return Settings(
        base_url=_env("AZURE_OPENAI_URL"),
        api_key=_env("AZURE_OPENAI_API_KEY"),
        model=_env("TEST_MODEL_NAME"),
        api_version=_env("OPENAI_API_VERSION"),
        structured_output_method=_env("STRUCTURED_OUTPUT_METHOD", default="function_calling"),
        reasoning_summary=summary if summary and summary.lower() != "off" else None,
        max_retries=int(_env("LLM_MAX_RETRIES", default="3")),
        timeout=float(_env("LLM_TIMEOUT", default="120")),
    )
