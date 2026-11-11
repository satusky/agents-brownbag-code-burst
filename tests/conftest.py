import os

# Load .env first (via config), then fill in placeholders so the snippets can be
# imported and compiled offline. Constructing a model makes no network call.
import agents_brownbag_code_burst.config  # noqa: F401

os.environ.setdefault("AZURE_OPENAI_URL", "https://example.invalid/openai/v1")
os.environ.setdefault("AZURE_OPENAI_API_KEY", "offline-placeholder")
os.environ.setdefault("TEST_MODEL_NAME", "offline-placeholder")
