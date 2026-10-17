"""Optional language-model backend (Microsoft Foundry / Azure OpenAI).

Forkcast runs fully without a model: every line has a deterministic template.
When these environment variables are set, the Narrator asks a Foundry model
deployment to rewrite the English casual line in a livelier broadcast voice,
and the Skeptic re-verifies every number before it can air.

    AZURE_OPENAI_ENDPOINT     https://<resource>.openai.azure.com/
    AZURE_OPENAI_API_KEY      key (or leave unset and use Entra ID via DefaultAzureCredential)
    AZURE_OPENAI_DEPLOYMENT   e.g. gpt-4o-mini
    AZURE_OPENAI_API_VERSION  default 2024-10-21
"""
from __future__ import annotations

import os

SYSTEM = (
    "You are the on-air voice of a football broadcast. Rewrite the line you are given so it sounds "
    "natural and exciting when spoken, in at most 30 words. Keep every number exactly as written, keep "
    "names exactly as written, add no new facts, numbers, records or superlatives. Output only the line."
)

_client = None


def enabled() -> bool:
    return bool(os.getenv("AZURE_OPENAI_ENDPOINT") and os.getenv("AZURE_OPENAI_DEPLOYMENT"))


def _get_client():
    global _client
    if _client is not None:
        return _client
    from openai import AzureOpenAI  # imported lazily so the package is optional

    kw = {"azure_endpoint": os.environ["AZURE_OPENAI_ENDPOINT"],
          "api_version": os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21"), "timeout": 6.0, "max_retries": 1}
    key = os.getenv("AZURE_OPENAI_API_KEY")
    if key:
        kw["api_key"] = key
    else:
        from azure.identity import DefaultAzureCredential, get_bearer_token_provider

        kw["azure_ad_token_provider"] = get_bearer_token_provider(
            DefaultAzureCredential(), "https://cognitiveservices.azure.com/.default")
    _client = AzureOpenAI(**kw)
    return _client


def rewrite(line: str) -> str | None:
    """Return a rewritten line, or None when no model is configured or the call fails."""
    if not enabled():
        return None
    try:
        resp = _get_client().chat.completions.create(
            model=os.environ["AZURE_OPENAI_DEPLOYMENT"],
            messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": line}],
            temperature=0.7,
            max_tokens=80,
        )
        out = (resp.choices[0].message.content or "").strip().strip('"')
        return out or None
    except Exception:  # network, quota, content filter: the template line airs instead
        return None
