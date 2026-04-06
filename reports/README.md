# AI Finance Reports Module

Self-contained report generation engine for the Ultimate Autoforwarder. Powered by local Ollama LLM (`qwen2.5:1.5b` — 986MB RAM). Runs independently without impacting forwarder performance.

## Architecture

```
reports/
├── __init__.py       # Exports: generate_report, ReportScheduler
├── config.py         # Report types, prompts, Ollama config, chunk sizing
├── engine.py         # Core: message chunking, LLM analysis, multi-chunk synthesis
├── scheduler.py      # Recurring report CRUD + background scheduler loop
└── README.md         # This file
```

### Integration with main.py

The module hooks into `main.py` in these places:

- **Menu option 14** calls `finance_report_menu(client)` (line ~1314)
  - Sub-option 1: `report_one_time(client)` — fetches messages from Telegram, runs engine
  - Sub-option 2: `report_recurring_menu()` — CRUD for scheduled reports
- **Forwarder start** (`start_forwarder`) creates a `ReportScheduler` instance and calls `.start()`
- **Forwarder stop** (`stop_forwarder`) calls `report_scheduler.stop()`
- Helper functions in main.py (not in this module):
  - `_select_channel_for_report()` — channel picker UI (line ~1044)
  - `_select_report_type()` — report type picker UI (line ~1092)
  - `_create_recurring_report()` — interactive schedule creation (line ~1258)

### Data Flow

```
One-Time Report:
  User picks channel + date range
  → client.iter_messages() fetches from Telegram directly
  → engine.py chunks messages → sends to Ollama → synthesizes
  → prints report to terminal (optionally saves .md file)

Recurring Report:
  Scheduler._loop() checks every 60s for due schedules
  → db.get_messages_by_date_range() fetches from local SQLite
  → engine.py chunks → Ollama → synthesis
  → stored in scheduler._last_reports[schedule_id]
  → viewable via menu option 14 > 2 > 4
```

**Key difference**: One-time reports fetch from **Telegram** (any channel the account is in). Recurring reports fetch from the **local DB** (only channels with active forwarding tasks).

## Files in Detail

### config.py

- `REPORT_CONFIG["ollama"]` — Ollama endpoint, model name, timeout, keep_alive
  - Model defaults to `OLLAMA_REPORT_MODEL` env var, falls back to `OLLAMA_REWRITE_MODEL`, then `qwen2.5:1.5b`
  - Timeout: 120s (reports analyze more text than rewrites)
  - keep_alive: 60s (keeps model warm between chunks)
- `REPORT_CONFIG["chunk_size"]` — max chars per LLM call (default 3000). Large message sets are split into chunks.
- `REPORT_CONFIG["report_types"]` — 5 built-in types, each with a system prompt:
  - `summary` — Market Overview, Key Signals, Performance Summary, Notable Events
  - `signals` — Extracts signals into a Markdown table (Ticker, Action, Entry, Target, SL, Status)
  - `sentiment` — Bullish/Bearish/Neutral analysis with confidence and key themes
  - `pnl` — Identifies completed trades, calculates P&L, marks open trades
  - `custom` — User provides their own prompt
- `REPORT_CONFIG["schedules_file"]` — path to `report_schedules.json` (project root, gitignored)

### engine.py

Public API:
```python
async def generate_report(messages, report_type="summary", custom_prompt=None, progress_cb=None) -> str
```

- `messages` — list of dicts with keys: `text_content` (str), `timestamp` (int unix)
- `report_type` — key from `REPORT_CONFIG["report_types"]`
- `custom_prompt` — string, used only when `report_type="custom"`
- `progress_cb` — optional `callable(str)` for progress updates
- Returns: Markdown-formatted report string

Internal flow:
1. `_chunk_messages()` splits messages into chunks of `chunk_size` chars
2. If single chunk: one `_ollama_analyze()` call
3. If multi-chunk: analyze each chunk separately, then a synthesis pass combines partial reports into one cohesive final report
4. `_ollama_analyze()` sends to Ollama `/api/chat` endpoint via `asyncio.to_thread()` (non-blocking)
5. 1-second delay between chunks to avoid RAM spikes

### scheduler.py

**CRUD functions** (module-level, used by main.py UI):
- `create_schedule(source_channel_id, channel_name, frequency, time_of_day, ...)` — creates and persists a schedule
- `list_schedules()` — returns all schedules from JSON
- `delete_schedule(schedule_id)` — removes by ID
- `toggle_schedule(schedule_id)` — flips enabled/disabled, recomputes next_run

**Schedule JSON shape** (`report_schedules.json`):
```json
{
  "schedules": [
    {
      "id": 1,
      "source_channel_id": -1001234567890,
      "channel_name": "Trading Signals",
      "frequency": "daily",           // "daily" | "weekly" | "monthly"
      "time_of_day": "08:00",
      "report_type": "summary",
      "custom_prompt": null,
      "lookback_days": 1,             // how many days of messages to analyze
      "enabled": true,
      "last_run": 1712345678,
      "next_run": 1712400000,
      "created_at": 1712300000,
      "day_of_week": 0,               // only for weekly (0=Mon..6=Sun)
      "day_of_month": 1               // only for monthly (1-31)
    }
  ]
}
```

**`ReportScheduler` class** (instantiated by main.py):
- `__init__(db, log_fn)` — takes a `DatabaseHandler` instance and a logging function
- `.start()` — creates an `asyncio.create_task` that runs `_loop()`
- `.stop()` — cancels the loop task
- `.get_last_report(schedule_id)` — returns `{"text": str, "generated_at": int, "message_count": int}` or None
- `._loop()` — runs every 60 seconds, calls `_check_due()`
- `._check_due()` — reads schedules JSON, runs any whose `next_run <= now`, updates `last_run` and `next_run`
- `._run_report(schedule)` — fetches messages from DB by date range, calls `generate_report()`, stores result

**`_compute_next_run(schedule)`** — computes next execution timestamp:
- Daily: tomorrow at `time_of_day` (or today if not yet passed)
- Weekly: next `day_of_week` at `time_of_day`
- Monthly: next `day_of_month` at `time_of_day` (clamps to month's max days)

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `OLLAMA_REPORT_MODEL` | (falls back to OLLAMA_REWRITE_MODEL, then qwen2.5:1.5b) | Ollama model for report generation |
| `OLLAMA_REWRITE_MODEL` | `qwen2.5:1.5b` | Shared fallback with rewriter module |

## Runtime Files (gitignored)

- `report_schedules.json` — persisted recurring schedules
- `report_*.md` — saved one-time reports

## Known Limitations / Future Work

- Recurring reports only use the local DB (messages must be forwarded through a task). One-time reports fetch from Telegram directly.
- No delivery mechanism for recurring reports yet (they're stored in memory, viewable via menu). Could add: save to file, send to a Telegram channel, email, etc.
- The `chunk_size` of 3000 chars is conservative for `qwen2.5:1.5b`. Could be tuned up for models with larger context windows.
- No caching — re-generates from scratch every time. Could hash message content and skip if unchanged.
- Schedule persistence is simple JSON. For many schedules or concurrent access, could migrate to SQLite.
