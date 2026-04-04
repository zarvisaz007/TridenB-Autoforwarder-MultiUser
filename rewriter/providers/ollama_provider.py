import json
import urllib.request
import asyncio
from ..config import REWRITE_CONFIG


async def ollama_rewrite(text, system_prompt):
    cfg = REWRITE_CONFIG["ollama"]
    url = cfg["url"].replace("/api/generate", "/api/chat")
    payload = {
        "model": cfg["model"],
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": "Stock is going up tomorrow. Buy at 100."},
            {"role": "assistant", "content": "Expect upward movement in the stock tomorrow. Enter a position at 100."},
            {"role": "user", "content": text},
        ],
        "stream": False,
        "keep_alive": "60s",
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})

    def _request():
        with urllib.request.urlopen(req, timeout=cfg["timeout"]) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            return result.get("message", {}).get("content", "").strip()

    return await asyncio.to_thread(_request)
