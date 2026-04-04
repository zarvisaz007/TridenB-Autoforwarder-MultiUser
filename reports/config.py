import os
from dotenv import load_dotenv
load_dotenv()

REPORT_CONFIG = {
    "ollama": {
        "url": "http://127.0.0.1:11434/api/chat",
        "model": os.getenv("OLLAMA_REPORT_MODEL", os.getenv("OLLAMA_REWRITE_MODEL", "qwen2.5:1.5b")),
        "timeout": 120,
        "keep_alive": "60s",
    },
    "chunk_size": 3000,  # max chars per LLM call (split large message sets)
    "report_types": {
        "summary": {
            "name": "Market Summary",
            "prompt": (
                "You are an expert financial analyst. Analyze these trading channel messages. "
                "Produce a concise Markdown report with sections:\n"
                "## Market Overview\n## Key Signals (Buy/Sell/Hold)\n## Performance Summary\n## Notable Events\n"
                "Preserve all numbers, tickers, and dates exactly. Ignore chatter and memes."
            ),
        },
        "signals": {
            "name": "Trading Signals Extract",
            "prompt": (
                "You are a trading signal extractor. From these messages, extract every trading signal. "
                "Format as a Markdown table with columns: Time | Ticker/Asset | Action (Buy/Sell/Hold) | "
                "Entry Price | Target | Stop Loss | Status (Hit/Missed/Open). "
                "Only include actual signals, skip general discussion."
            ),
        },
        "sentiment": {
            "name": "Sentiment Analysis",
            "prompt": (
                "You are a market sentiment analyst. Analyze the tone and sentiment of these trading messages. "
                "Produce a Markdown report: overall sentiment (Bullish/Bearish/Neutral), confidence level, "
                "key themes, notable shifts in sentiment over the period, and a brief conclusion."
            ),
        },
        "pnl": {
            "name": "P&L Tracker",
            "prompt": (
                "You are a P&L tracking analyst. From these messages, identify all completed trades "
                "(entry + exit or target hit). Calculate approximate P&L for each. "
                "Format as Markdown with a summary table and total estimated P&L. "
                "Mark trades still open. Use exact numbers from messages."
            ),
        },
        "custom": {
            "name": "Custom Report",
            "prompt": None,  # user provides
        },
    },
    "schedules_file": os.path.join(os.path.dirname(__file__), "..", "report_schedules.json"),
}
