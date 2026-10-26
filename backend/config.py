"""Model wiring for TNAT.

The course key is restricted to gpt-6-luna, so that is the default. The grading
staff place their .env one directory ABOVE the cloned repo, so the search starts
here and walks upward.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from openai import AsyncOpenAI
from pydantic_ai.models.openai import OpenAIResponsesModel
from pydantic_ai.providers.openai import OpenAIProvider

HERE = Path(__file__).resolve().parent
REPO = HERE.parent

# backend/ → repo root → the folder the graders drop their .env into → upward
for folder in (HERE, REPO, *REPO.parents[:4]):
    if (folder / ".env").is_file():
        load_dotenv(folder / ".env", override=False)
        ENV_FOUND = str(folder / ".env")
        break
else:
    ENV_FOUND = None

MODEL_NAME = os.getenv("TNAT_MODEL", "gpt-6-luna")
PORTKEY_BASE_URL = os.getenv("PORTKEY_BASE_URL", "https://api.portkey.ai/v1").rstrip("/")
REQUEST_TIMEOUT = 60.0

# Spend guards. A runaway loop is the expensive failure mode, so cap it here
# rather than hoping the prompt holds.
MAX_REQUESTS_PER_RUN = 6
MAX_TOOL_CALLS_PER_RUN = 10
MAX_MESSAGE_CHARS = 1500


def api_key_present() -> bool:
    """True when a key is configured. Never returns the key itself."""
    return bool(os.getenv("PORTKEY_API_KEY", "").strip() or os.getenv("OPENAI_API_KEY", "").strip())


def _api_key() -> tuple[str, str]:
    """(key, which) — prefer Portkey, fall back to a direct OpenAI key."""
    pk = os.getenv("PORTKEY_API_KEY", "").strip()
    if pk:
        return pk, "portkey"
    oa = os.getenv("OPENAI_API_KEY", "").strip()
    if oa:
        return oa, "openai"
    raise RuntimeError(
        "No API key found. Put PORTKEY_API_KEY (or OPENAI_API_KEY) in a .env "
        "in this folder or the one above it."
    )


@lru_cache(maxsize=1)
def build_model() -> OpenAIResponsesModel:
    key, which = _api_key()
    if which == "portkey":
        client = AsyncOpenAI(api_key=key, base_url=PORTKEY_BASE_URL,
                             default_headers={"x-portkey-provider": "openai"},
                             timeout=REQUEST_TIMEOUT)
    else:
        client = AsyncOpenAI(api_key=key, timeout=REQUEST_TIMEOUT)
    return OpenAIResponsesModel(MODEL_NAME, provider=OpenAIProvider(openai_client=client))


def which_key() -> str:
    try:
        return _api_key()[1]
    except RuntimeError:
        return "none"
