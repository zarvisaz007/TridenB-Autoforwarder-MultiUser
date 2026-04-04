import os
from dotenv import load_dotenv
load_dotenv()

REWRITE_CONFIG = {
    "default_prompt": (
        "You are a rewriting tool. The user sends you a message and you reply "
        "with ONLY a rewritten version using different words but the same meaning. "
        "Preserve all numbers, names, and data. Never explain, never ask questions, "
        "never add anything extra. Reply with ONLY the rewritten text."
    ),
    "provider_order": ["ollama", "openrouter"],  # fallback chain
    "ollama": {
        "url": "http://127.0.0.1:11434/api/generate",
        "model": os.getenv("OLLAMA_REWRITE_MODEL", "qwen2.5:1.5b"),
        "timeout": 30,
    },
    "openrouter": {
        "url": "https://openrouter.ai/api/v1/chat/completions",
        "api_key": os.getenv("OPENROUTER_API_KEY", ""),
        "model": os.getenv("OPENROUTER_REWRITE_MODEL", "google/gemma-3n-e4b-it:free"),
        "timeout": 30,
    },
}
