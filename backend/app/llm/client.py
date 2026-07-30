"""
Provider-agnostic LLM client (PLAN.md locked decision #6).

Two providers behind one `generate(prompt_system, prompt_user) -> str`
interface, selected by `settings.llm_provider`:

- "kimi"   — Kimi K2 via its OpenAI-compatible chat-completions endpoint
             (`openai` package with a custom base_url). Default.
- "claude" — Claude via the `anthropic` package.

The generator never instantiates these directly: FastAPI endpoints get a
client through the `get_llm_client` dependency, so tests inject a fake and
no test ever hits a real API. A missing API key raises
`LLMNotConfiguredError`; `get_llm_client` turns that into `None`, which the
generator treats as "go straight to the deterministic fallback".
"""

from typing import Protocol, runtime_checkable

from ..config import settings


class LLMError(Exception):
    """Any LLM call failure (network, API error, bad response shape)."""


class LLMNotConfiguredError(LLMError):
    """No API key (or unknown provider) configured."""


@runtime_checkable
class LLMClient(Protocol):
    def generate(self, prompt_system: str, prompt_user: str) -> str:
        """Return the model's raw text response."""
        ...


class KimiClient:
    """Kimi K2 (or any OpenAI-compatible endpoint) via the openai package."""

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        timeout: float = 60.0,
    ):
        if not api_key:
            raise LLMNotConfiguredError(
                "LLM_API_KEY is not set — cannot use the Kimi provider"
            )
        from openai import OpenAI

        self._client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout)
        self._model = model

    def generate(self, prompt_system: str, prompt_user: str) -> str:
        try:
            resp = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": prompt_system},
                    {"role": "user", "content": prompt_user},
                ],
                temperature=0.4,
            )
        except Exception as exc:  # openai raises its own exception hierarchy
            raise LLMError(f"Kimi request failed: {exc}") from exc
        content = resp.choices[0].message.content if resp.choices else None
        if not content:
            raise LLMError("Kimi returned an empty response")
        return content


class ClaudeClient:
    """Claude via the anthropic package."""

    def __init__(self, api_key: str, model: str, timeout: float = 60.0):
        if not api_key:
            raise LLMNotConfiguredError(
                "LLM_API_KEY is not set — cannot use the Claude provider"
            )
        from anthropic import Anthropic

        self._client = Anthropic(api_key=api_key, timeout=timeout)
        self._model = model

    def generate(self, prompt_system: str, prompt_user: str) -> str:
        try:
            msg = self._client.messages.create(
                model=self._model,
                max_tokens=4096,
                system=prompt_system,
                messages=[{"role": "user", "content": prompt_user}],
            )
        except Exception as exc:  # anthropic raises its own exception hierarchy
            raise LLMError(f"Claude request failed: {exc}") from exc
        text = "".join(block.text for block in msg.content if block.type == "text")
        if not text:
            raise LLMError("Claude returned an empty response")
        return text


def build_client() -> LLMClient:
    """Instantiate the configured provider. Raises LLMNotConfiguredError."""
    if settings.llm_provider == "kimi":
        return KimiClient(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            model=settings.llm_model,
            timeout=settings.llm_timeout_seconds,
        )
    if settings.llm_provider == "claude":
        return ClaudeClient(
            api_key=settings.llm_api_key,
            model=settings.llm_model,
            timeout=settings.llm_timeout_seconds,
        )
    raise LLMNotConfiguredError(
        f"Unknown LLM_PROVIDER '{settings.llm_provider}' (expected 'kimi' or 'claude')"
    )


def get_llm_client() -> LLMClient | None:
    """
    FastAPI dependency: the configured client, or None when no API key is
    configured (the generator then uses its deterministic fallback, so a
    week is always producible). Tests override this dependency with a fake.
    """
    try:
        return build_client()
    except LLMNotConfiguredError:
        return None
