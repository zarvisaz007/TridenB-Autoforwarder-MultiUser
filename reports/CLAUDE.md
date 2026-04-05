# Reports Module — Agent Instructions

## What This Is

Self-contained AI finance report engine inside the TridenB Autoforwarder project. Located at `reports/` relative to project root. Uses local Ollama (`qwen2.5:1.5b`) for all LLM work — no cloud APIs needed.

## Critical Rules

- **DO NOT modify anything in `rewriter/`** — that's a separate module with its own concerns
- **DO NOT change the Ollama model** without confirming with the user — the current model was specifically chosen for low RAM usage on a 16GB Mac Mini
- **DO NOT touch the forwarder logic in main.py** (event handlers, filters, send_copy, etc.) — this module is isolated from forwarding
- The module must remain **async-compatible** — all LLM calls go through `asyncio.to_thread()`, never block the event loop
- Messages fed to the engine are dicts with `text_content` (str) and `timestamp` (int unix) keys — maintain this interface

## File Map

| File | Purpose | Key exports |
|------|---------|-------------|
| `reports/__init__.py` | Package exports | `generate_report`, `ReportScheduler` |
| `reports/config.py` | All config: model, prompts, chunk size, report types | `REPORT_CONFIG` dict |
| `reports/engine.py` | Core analysis: chunk → LLM → synthesize | `generate_report()` |
| `reports/scheduler.py` | Recurring schedule CRUD + background loop | `ReportScheduler`, `create_schedule`, `list_schedules`, `delete_schedule`, `toggle_schedule` |

## Integration Points in main.py

These functions in `main.py` form the UI layer for this module:

| Function | Line | What it does |
|----------|------|-------------|
| `finance_report_menu(client)` | ~1314 | Top-level menu (option 14): one-time vs recurring |
| `report_one_time(client)` | ~1116 | Fetches msgs from Telegram via `client.iter_messages()`, runs engine |
| `report_recurring_menu()` | ~1185 | CRUD submenu for scheduled reports |
| `_select_channel_for_report()` | ~1044 | Channel picker (tasks + DB + manual ID) |
| `_select_report_type()` | ~1092 | Report type picker (5 built-in + custom) |
| `_create_recurring_report()` | ~1258 | Interactive schedule creation wizard |

Lifecycle hooks:
- `start_forwarder()` creates `ReportScheduler(db, log_fn=add_log)` and calls `.start()`
- `stop_forwarder()` calls `report_scheduler.stop()`

## How to Add a New Report Type

1. Add entry to `REPORT_CONFIG["report_types"]` in `config.py`:
   ```python
   "my_type": {
       "name": "Display Name",
       "prompt": "System prompt for the LLM...",
   },
   ```
2. That's it — the UI and engine pick it up automatically from the config.

## How to Change the LLM Provider

The engine uses Ollama's `/api/chat` endpoint directly (no SDK). To swap providers:
1. Modify `_ollama_analyze()` in `engine.py`
2. Update config in `config.py`
3. The function signature must remain: `async def _ollama_analyze(messages_text, system_prompt) -> str`

## Testing

Run from project root:
```bash
# Test engine with real DB data
python3 -c "
import asyncio
from database import db
from reports import generate_report
messages = db.get_messages_by_date_range(-1001653858095, 0, 9999999999)
print(asyncio.run(generate_report(messages, report_type='summary')))
"

# Test scheduler CRUD
python3 -c "
from reports.scheduler import create_schedule, list_schedules, delete_schedule
s = create_schedule(-1001234, 'Test', 'daily', '09:00')
print(list_schedules())
delete_schedule(s['id'])
"
```

## Current State (2026-04-06)

- All 5 report types working (summary, signals, sentiment, pnl, custom)
- One-time reports fetch from Telegram directly (any channel)
- Recurring reports fetch from local DB (forwarded messages only)
- Scheduler starts/stops with forwarder
- Model: qwen2.5:1.5b (986MB), timeout 120s, keep_alive 60s
- Chunk size: 3000 chars per LLM call
- Accessible via Telegram bot (bot_handlers/reports.py wraps this module for multi-user use)
- Bot mode uses bot_database.py for message storage instead of the CLI's database.py
- Admin can view per-user report activity from CLI dashboard (admin/ package)
