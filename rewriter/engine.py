import asyncio
from .providers.ollama_provider import ollama_rewrite
from .providers.openrouter_provider import openrouter_rewrite
from .config import REWRITE_CONFIG


async def rewrite_text(text, prompt=None, provider=None):
    """
    Rewrite text to avoid copyright. Tries providers in fallback order.
    Returns rewritten text on success, original text on total failure.
    """
    if not text or not text.strip():
        return text

    # Skip rewriting for very short messages (dots, emojis, single words)
    stripped = text.strip()
    if len(stripped) < 5 or not any(c.isalpha() for c in stripped):
        return text

    # Always use the default prompt as base; append custom instructions if provided
    system_prompt = REWRITE_CONFIG["default_prompt"]
    if prompt:
        system_prompt += "\n\n[USER INSTRUCTION START]\n" + prompt[:500] + "\n[USER INSTRUCTION END]"

    # If specific provider requested
    if provider:
        providers = [provider]
    else:
        providers = REWRITE_CONFIG["provider_order"]

    last_error = None
    for prov in providers:
        try:
            if prov == "ollama":
                result = await ollama_rewrite(text, system_prompt)
            elif prov == "openrouter":
                result = await openrouter_rewrite(text, system_prompt)
            else:
                continue

            if result and result.strip() and not result.startswith("["):
                return result
            last_error = f"{prov}: empty or error response"
        except Exception as e:
            last_error = f"{prov}: {e}"
            continue

    return text  # fallback: return original
