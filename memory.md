# TridenB Autoforwarder — Multi-User Bot Edition

## What This Project Does
Multi-user Telegram autoforwarder with THREE interfaces:
1. **CLI** (`main.py`) — original single-user terminal interface
2. **Bot** (`run_bot.py`) — multi-user Telegram bot with inline menus, admin panel, and per-user sessions
3. **Admin CLI** (`run_bot.py` dashboard) — interactive terminal admin panel running alongside the bot

Each user connects their own Telegram account via OTP through the bot, gets independent tasks, filters, AI rewriting, reports, and message forwarding — all controlled through inline keyboard menus.

## Credentials
- Stored in `.env` (never committed)
- `API_ID`, `API_HASH` — Telegram API credentials
- `BOT_TOKEN` — Aiogram bot token
- `ADMIN_IDS` — comma-separated Telegram user IDs for admin access
- `PHONE` — used by CLI mode only

## Architecture

### Bot Mode (Multi-User)
```
run_bot.py                  — Single entry point (bot + CLI dashboard)
├── bot_database.py         — Multi-tenant async SQLite (WAL mode)
├── bot_forwarder.py        — Per-user Telethon client pool + event handlers
├── admin/                  — CLI admin dashboard package
│   ├── cli.py              — Main interactive menu loop
│   ├── views.py            — All dashboard views (users, tasks, stats, channels, logs, queries)
│   └── helpers.py          — Terminal colors, formatting, async input
└── bot_handlers/
    ├── auth.py             — OTP/2FA login flow
    ├── menu.py             — Categorized inline menu system
    ├── tasks.py            — Task CRUD with filter setup
    ├── forwarder_ctl.py    — Start/stop/status + channel ID picker
    ├── filters.py          — 13 filter types (boolean/list/number)
    ├── rewriting.py        — AI rewrite toggle + prompt editor
    ├── statistics.py       — Per-task stats and message threads
    ├── reports.py          — One-time + recurring AI finance reports
    ├── export_import.py    — JSON backup/restore
    ├── admin.py            — Telegram admin panel + channel ownership transfer
    └── queries.py          — User query/message system (contact admin)
```

### CLI Mode (Single-User)
```
main.py                     — All 14+ menu options in terminal
├── database.py             — Synchronous SQLite handler
├── rewriter/               — AI rewrite engine (Ollama/OpenRouter)
└── reports/                — AI finance report engine (Ollama)
```

## Database
- **Bot mode**: `bot_data.db` — 5 tables: users, tasks, message_map, report_schedules, queries
- **CLI mode**: `autoforwarder.db` — separate single-user database
- Both gitignored

## Sessions
- Stored in `sessions/` directory (gitignored)
- Named `user_{telegram_id}.session`
- Created during OTP auth, reused on subsequent connections

## Key Features
- 16+ features accessible via bot inline menus
- Per-user Telethon sessions (MTProto)
- Full filter chain: whitelist, blacklist, regex, URL/username cleaning, media skipping
- AI rewriting via Ollama (local) with OpenRouter fallback
- AI finance reports (summary, signals, sentiment, P&L, custom)
- Edit/delete sync across forwarded messages
- Reply threading preservation
- Loop protection (10 msgs in 10s = auto-pause)
- Image auto-cleanup after N days
- Telegram admin panel: user management, channel overview, ownership transfer
- Interactive CLI admin dashboard: drill-down user details, usage stats, channels, pause controls
- Query/message system: users contact admin via bot, admin replies from terminal
- Import/export tasks as JSON

## Admin CLI Dashboard
Run `python3 run_bot.py` — bot starts in background, interactive dashboard in foreground:
- **Users Overview**: full phone numbers, drill into any user for tasks/channels/stats/logs
- **All Tasks**: every task across all users with status
- **Global Stats**: total messages, today count, per-user breakdown
- **Channels**: per-user channel list with Owner/Admin/Member roles + subscriber counts
- **Live Logs**: auto-refreshing logs (3s), Ctrl+C to exit
- **Queries**: view and reply to user messages from terminal
- **Pause/Resume**: pause all tasks globally or per-user

## Current Status (2026-04-06)
Multi-user bot fully implemented. Interactive CLI admin dashboard with drill-down user views, query system, and pause controls. All features working. Admin panel on both Telegram and terminal. CLI mode (`main.py`) untouched and still works independently.

## How to Run
```bash
# Install dependencies
pip install -r requirements.txt

# Set up .env with API_ID, API_HASH, BOT_TOKEN, ADMIN_IDS

# Start the bot + admin dashboard
python3 run_bot.py
```

## Key Files
- `run_bot.py` — bot + admin dashboard entry point (start here)
- `main.py` — CLI entry point (independent)
- `admin/` — CLI admin dashboard package
- `bot_database.py` — all database operations
- `bot_forwarder.py` — Telethon client management + forwarding logic
- `bot_handlers/` — all bot UI handlers
- `.env` — credentials (never committed)
- `GUIDE.md` — complete user guide
