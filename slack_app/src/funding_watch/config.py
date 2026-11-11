"""Settings read from environment variables (and a .env file, if present).

Every setting has one primary name; a few older aliases are also accepted.

| Setting                     | Primary variable            | Aliases              | Default            |
|-----------------------------|-----------------------------|----------------------|--------------------|
| Endpoint URL                | AZURE_OPENAI_URL            | AZURE_ENDPOINT_URL   | (required)         |
| API key                     | AZURE_OPENAI_API_KEY        | AZURE_API_KEY        | (required)         |
| Model / deployment name     | TEST_MODEL_NAME             | LLM_MODEL            | (required)         |
| API version (classic Azure) | OPENAI_API_VERSION          | AZURE_API_VERSION    | unset              |
| Structured output method    | STRUCTURED_OUTPUT_METHOD    |                      | function_calling   |
| Retries per model call      | LLM_MAX_RETRIES             |                      | 3                  |
| Model call timeout (s)      | LLM_TIMEOUT                 |                      | 120                |
| Parallel model calls cap    | MAX_CONCURRENCY             |                      | 4                  |
| Funding data source         | FUNDING_SOURCE              |                      | fixtures           |
| Opportunity for the stages  | SEMINAR_OPPORTUNITY         |                      | per source         |
| Pinned "today" (optional)   | DEMO_TODAY                  |                      | the real date      |
| Slack: practice or live     | SLACK_MODE                  |                      | practice           |
| Slack bot token (live)      | SLACK_BOT_TOKEN             |                      | unset              |
| Slack app token (listener)  | SLACK_APP_TOKEN             |                      | unset              |
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"

# A .env in the current directory wins over the one at the project root.
load_dotenv(Path.cwd() / ".env")
load_dotenv(PROJECT_ROOT / ".env")


def _env(*names: str, default: str | None = None) -> str | None:
    for name in names:
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
    max_retries: int
    timeout: float
    max_concurrency: int
    funding_source: str
    seminar_opportunity: str | None
    demo_today: str
    slack_mode: str = "practice"
    slack_bot_token: str | None = None
    slack_app_token: str | None = None  # xapp-…: `funding-watch slack` listens for mentions

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.api_key and self.model)

    @property
    def missing(self) -> list[str]:
        names = {"AZURE_OPENAI_URL": self.base_url, "AZURE_OPENAI_API_KEY": self.api_key, "TEST_MODEL_NAME": self.model}
        return [k for k, v in names.items() if not v]

    @property
    def endpoint_host(self) -> str | None:
        """Host of the endpoint, safe to display (no key, no path)."""
        if not self.base_url:
            return None
        from urllib.parse import urlparse

        return urlparse(self.base_url).netloc or self.base_url

    def today(self) -> date:
        """The date used for every day count: the real date, unless DEMO_TODAY pins one."""
        if self.demo_today.lower() in {"today", "live", "now", ""}:
            return date.today()
        return date.fromisoformat(self.demo_today)


def get_settings() -> Settings:
    """Read settings fresh from the environment on every call."""
    source = _env("FUNDING_SOURCE", default="fixtures").lower()
    return Settings(
        base_url=_env("AZURE_OPENAI_URL", "AZURE_ENDPOINT_URL"),
        api_key=_env("AZURE_OPENAI_API_KEY", "AZURE_API_KEY"),
        model=_env("TEST_MODEL_NAME", "LLM_MODEL"),
        api_version=_env("OPENAI_API_VERSION", "AZURE_API_VERSION"),
        structured_output_method=_env("STRUCTURED_OUTPUT_METHOD", default="function_calling"),
        max_retries=int(_env("LLM_MAX_RETRIES", default="3")),
        timeout=float(_env("LLM_TIMEOUT", default="120")),
        max_concurrency=int(_env("MAX_CONCURRENCY", default="4")),
        funding_source=source,
        seminar_opportunity=_env("SEMINAR_OPPORTUNITY"),
        demo_today=_env("DEMO_TODAY", default="today"),
        slack_mode=_env("SLACK_MODE", default="practice").lower(),
        slack_bot_token=_env("SLACK_BOT_TOKEN"),
        slack_app_token=_env("SLACK_APP_TOKEN"),
    )
