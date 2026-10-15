"""Where the outlook request is sent: OpenRouter in production, Token Harbor in development.

Both serve the same DeepSeek model through an OpenAI-shaped chat-completion
endpoint. OpenRouter is paid and is what the scheduled workflows use; Token
Harbor serves the model free and is for trying a prompt locally without
spending. The choice is never left to a missing key: a run inside GitHub
Actions is production and only ever uses OpenRouter, and a local run uses
Token Harbor unless OpenRouter is asked for by name.

Token Harbor's figures are not production's. It may serve the model at a
different precision, and nothing it returns should reach the tables the
screener reads -- see `tools.extract_transcript_outlook`, which does not write
a Token Harbor reading unless told to.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

OPENROUTER = "openrouter"
TOKENHARBOR = "tokenharbor"
PROVIDERS = (OPENROUTER, TOKENHARBOR)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
TOKENHARBOR_URL = "https://tokenharbor.ai/v1/chat/completions"
TOKENHARBOR_MODELS_URL = "https://tokenharbor.ai/v1/models"

OPENROUTER_MODEL = "deepseek/deepseek-v4.1-flash"
# Production's model, from the free tier: Token Harbor names its models without
# a vendor prefix, and the same name without ":free" is billed. Its catalogue
# is only listed to a key holder: `python -m tools.extract_transcript_outlook
# --list-models` prints it, and TOKENHARBOR_MODEL overrides this.
TOKENHARBOR_MODEL = "deepseek-v4.1-flash:free"

_KEY_VARIABLES = {OPENROUTER: "OPENROUTER_API_KEY", TOKENHARBOR: "TOKENHARBOR_API_KEY"}


class ProviderError(RuntimeError):
    """A provider that may not or cannot be used for this run."""


@dataclass(frozen=True)
class Provider:
    name: str
    url: str
    api_key: str
    model: str

    @property
    def stored_model_name(self) -> str:
        """The ``model_name`` a reading is stored under.

        OpenRouter's keeps the name every stored outlook already has. Token
        Harbor's is prefixed, so a development reading is never mistaken for
        production's or counted as a call already read.
        """
        return self.model if self.name == OPENROUTER else f"{self.name}/{self.model}"

    @property
    def is_production(self) -> bool:
        return self.name == OPENROUTER


def in_production(environ: Mapping[str, str]) -> bool:
    """Whether this run is a scheduled workflow rather than someone's machine."""
    return str(environ.get("GITHUB_ACTIONS", "")).strip().lower() == "true"


def resolve_provider(
    requested: str | None = None,
    model: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> Provider:
    """The provider for this run, with its key.

    ``requested`` (or ``OUTLOOK_PROVIDER``) names one; otherwise production
    uses OpenRouter and development Token Harbor. Production refuses Token
    Harbor outright. ``model`` overrides the provider's default model.
    """
    environ = os.environ if environ is None else environ
    name = (requested or environ.get("OUTLOOK_PROVIDER") or "").strip().lower()
    if not name:
        name = OPENROUTER if in_production(environ) else TOKENHARBOR
    if name not in PROVIDERS:
        raise ProviderError(f"unknown outlook provider {name!r}; expected one of {', '.join(PROVIDERS)}")
    if name == TOKENHARBOR and in_production(environ):
        raise ProviderError("production uses OpenRouter only; Token Harbor is for development")

    variable = _KEY_VARIABLES[name]
    api_key = str(environ.get(variable, "")).strip()
    if not api_key:
        hint = "" if name == OPENROUTER else " (or pass --provider openrouter, which is paid)"
        raise ProviderError(f"{variable} is not set (environment or .env){hint}")

    if name == OPENROUTER:
        return Provider(OPENROUTER, OPENROUTER_URL, api_key, model or OPENROUTER_MODEL)
    default = str(environ.get("TOKENHARBOR_MODEL", "")).strip() or TOKENHARBOR_MODEL
    return Provider(TOKENHARBOR, TOKENHARBOR_URL, api_key, model or default)
