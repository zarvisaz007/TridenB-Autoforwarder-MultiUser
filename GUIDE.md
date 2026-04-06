# Ultimate Autoforwarder — Complete Guide

Everything you need to know to run and use the bot.

---

## Quick Start

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```
This installs: `telethon`, `python-dotenv`, `aiogram`, `aiosqlite`

### 2. Setup .env File
Create a `.env` file in the project root:
```
API_ID=your_telegram_api_id
API_HASH=your_telegram_api_hash
BOT_TOKEN=your_bot_token
ADMIN_IDS=your_telegram_user_id
PHONE=+your_phone_number
```

- **API_ID / API_HASH**: Get from https://my.telegram.org
- **BOT_TOKEN**: Get from @BotFather on Telegram
- **ADMIN_IDS**: Your Telegram user ID (find it via @userinfobot). Comma-separate multiple admins.
- **PHONE**: Only needed for CLI mode

### 3. Run the Bot
```bash
python3 run_bot.py
```

That's it! The bot starts, prints an admin dashboard to your terminal, and begins polling for messages.

### 4. Open Telegram
Find your bot on Telegram and send `/start`.

---

## How Users Connect

1. User sends `/start` to the bot
2. Bot asks for their phone number (e.g. `+1234567890`)
3. Telegram sends them an OTP code
4. User enters the code WITH SPACES (e.g. `1 2 3 4 5`) — this prevents Telegram from blocking the code
5. If they have 2FA enabled, bot asks for their password (message is auto-deleted)
6. Done! Their Telegram session is now linked to the bot

---

## Main Menu (What Users See)

After connecting, users see a categorized menu:

| Category | What's Inside |
|----------|--------------|
| **Channels** | Get channel IDs — tap any channel to copy its ID |
| **My Tasks** | Create, list, edit, toggle, duplicate, delete tasks |
| **Forwarder** | Start/stop forwarding, pause tasks, view live status |
| **Filters & AI** | Edit per-task filters, configure AI rewriting |
| **Analytics** | Stats, message threads, logs, AI finance reports |
| **Import/Export** | Backup and restore tasks as JSON files |
| **Contact Admin** | Send queries/messages to the admin, view replies |
| **Admin Panel** | (Admin only) User management, channel overview, transfers |

---

## Creating a Forwarding Task

1. Go to **My Tasks** → **Create Task**
2. Enter a task name (e.g. "Signals Forward")
3. Enter the source channel ID (e.g. `-1001234567890`)
4. Enter destination channel IDs (comma-separated)
5. Done! You'll see options to **Setup Filters** or go back

### Where to Find Channel IDs
Go to **Channels** → **Get Channel IDs**. The bot lists all your channels and groups. Tap any channel's "Copy ID" button to get its ID.

---

## Filters (Per-Task)

Each task has its own filter settings:

| Filter | Type | What It Does |
|--------|------|-------------|
| **Blacklist Words** | List | Drop message if it contains any of these words |
| **Whitelist Words** | List | Only forward if message contains at least one of these |
| **Regex Blacklist** | List | Drop message if it matches any regex pattern |
| **Clean Words** | List | Remove these words/phrases from the message text |
| **Regex Clean** | List | Remove text matching these regex patterns |
| **Clean URLs** | Toggle | Strip all URLs from messages |
| **Clean Usernames** | Toggle | Strip all @mentions from messages |
| **Skip Images** | Toggle | Don't forward image messages |
| **Skip Audio** | Toggle | Don't forward audio/voice messages |
| **Skip Videos** | Toggle | Don't forward video messages |
| **Delay (seconds)** | Number | Wait N seconds before forwarding |
| **Image Delete (days)** | Number | Auto-delete forwarded images after N days |
| **AI Rewrite** | Toggle | Rewrite message text with AI before forwarding |

### How to Set Filters
- After creating a task, tap **Setup Filters**
- Or go to **Filters & AI** → **Edit Filters** → pick a task
- Toggle filters tap to switch ON/OFF
- List filters: send comma-separated values, type `clear` to remove all
- Number filters: send a number, type `cancel` to go back

---

## AI Rewriting

Rewrites message text before forwarding to avoid copyright issues.

### Setup
1. Go to **Filters & AI** → **AI Rewrite Config**
2. Pick a task
3. Turn ON/OFF
4. Optionally set a custom prompt (e.g. "Paraphrase for trading context")

### How It Works
- Uses **Ollama** (local, free) as primary provider
- Falls back to **OpenRouter** (cloud) if Ollama is down
- Set models in `.env`: `OLLAMA_REWRITE_MODEL`, `OPENROUTER_API_KEY`

---

## AI Finance Reports

Generate AI-powered analysis of forwarded messages.

### One-Time Reports
1. Go to **Analytics** → **AI Finance Reports** → **One-Time Report**
2. Pick a source channel
3. Set lookback days (how far back to analyze)
4. Choose report type: Summary, Signals, Sentiment, P&L, or Custom
5. Wait for AI to generate the report

### Recurring Reports
Set up automated reports on a schedule (daily/weekly/monthly).

### Report Types
| Type | What It Generates |
|------|------------------|
| **Summary** | Market overview, key signals, notable events |
| **Signals** | Table of trading signals (ticker, action, entry, target, SL) |
| **Sentiment** | Bullish/bearish/neutral analysis with confidence score |
| **P&L** | Completed trades with profit/loss calculation |
| **Custom** | Your own prompt — analyze anything |

---

## Forwarder Status

After starting the forwarder, go to **Forwarder** → **Forwarder Status** to see:
- Connection status (green/red)
- Active tasks count
- Messages forwarded today
- All-time message count
- Recent activity log
- Refresh button for live updates

---

## Admin Panel (Admin Only)

Accessible from the main menu. Restricted to user IDs listed in `ADMIN_IDS` in `.env`.

### Views

| View | What It Shows |
|------|-------------|
| **All Users** | Every connected user: phone (masked), status, active client, task count, message count, last active |
| **All Tasks** | Every task across all users: name, status, source/dest, AI flag |
| **Global Stats** | Total messages, today's count, images, active clients, per-user breakdown |
| **User Channels** | For each user: their channels with owner/admin/member role and subscriber count |
| **Transfer Ownership** | Transfer channel ownership from a user to yourself (see below) |

### Channel Ownership Transfer

This lets the admin take ownership of a user's channel.

**How it works:**
1. Go to **Admin Panel** → **Transfer Ownership**
2. Pick a connected user
3. Browse their channels (only shows channels they OWN)
4. Tap **Transfer** on a channel
5. Confirm on the warning screen
6. The channel owner receives a message asking for their 2FA password
7. They enter it (message is auto-deleted for security)
8. Ownership transfers to you
9. Both parties get notified

**Requirements:**
- The channel owner must have 2FA enabled
- You (admin) must be a member of the target channel
- Transfer request expires after 5 minutes
- Only one pending transfer per user at a time

---

## Admin CLI Dashboard

When you run `python3 run_bot.py`, the bot starts in the background and an interactive admin dashboard appears in your terminal.

### Dashboard Menu
| Option | What It Does |
|--------|-------------|
| **1 - Users Overview** | All users with full phone, status, client, tasks, messages. Enter a number to drill into a user |
| **2 - All Tasks** | Every task across all users with source/dest and ON/OFF/PAUSED/AI status |
| **3 - Global Stats** | Total messages, today count, images, active clients, per-user breakdown |
| **4 - Channels** | Per-user channel list with Owner/Admin/Member role and subscriber counts |
| **5 - Live Logs** | Auto-refreshing logs every 3 seconds. Ctrl+C to exit |
| **6 - Queries** | View user messages/queries and reply from terminal |
| **P - Pause ALL** | Pause every task across all users |
| **R - Resume ALL** | Resume all paused tasks |

### Drill-Down User View
From Users Overview, enter a user's number to see:
- Full details: phone, join date, last active, client status
- Usage stats: total messages, today, this week, images
- All their tasks with status flags
- All their channels with Owner/Admin/Member roles and subscriber counts
- Recent forwarder logs
- **P** to pause all their tasks, **R** to resume

### Query / Message System
Users can send queries to you through the bot:
1. User taps **Contact Admin** in their main menu
2. User types their message
3. You see it in the dashboard under **Queries** (option 6)
4. Enter the query number, type your reply
5. Reply is sent directly to the user on Telegram

Unreplied query count shows on the dashboard summary so you don't miss anything.

---

## Import / Export

### Export
Go to **Import/Export** → **Export Tasks**. The bot sends you a `.json` file with all your tasks and their filter configs.

### Import
Go to **Import/Export** → **Import Tasks**. Send a `.json` file in the same format. Tasks are created from the file.

---

## Safety Features

| Feature | Description |
|---------|------------|
| **Loop Protection** | Task auto-pauses if it forwards 10+ messages in 10 seconds |
| **OTP Space Trick** | Users enter OTP with spaces to prevent Telegram from blocking the login code message |
| **Password Auto-Delete** | 2FA passwords are deleted from chat immediately after entry |
| **Session Isolation** | Each user has their own Telethon session file — no cross-contamination |
| **Keepalive Loop** | Background loop keeps Telethon connections alive |
| **Flood Wait Handling** | Respects Telegram's rate limits automatically |

---

## File Structure

```
project/
├── run_bot.py              ← START HERE (bot + admin dashboard)
├── main.py                 ← CLI mode (independent)
├── bot_database.py         ← Multi-tenant database (5 tables)
├── bot_forwarder.py        ← Telethon client pool + forwarding
├── admin/                  ← CLI admin dashboard package
│   ├── cli.py              ← Main interactive menu loop
│   ├── views.py            ← All dashboard views
│   └── helpers.py          ← Terminal colors + formatting
├── bot_handlers/           ← All bot UI handlers
│   ├── auth.py             ← Login flow
│   ├── menu.py             ← Main menu
│   ├── tasks.py            ← Task management
│   ├── forwarder_ctl.py    ← Forwarder controls
│   ├── filters.py          ← Filter editing
│   ├── rewriting.py        ← AI rewrite config
│   ├── statistics.py       ← Stats display
│   ├── reports.py          ← AI reports
│   ├── export_import.py    ← JSON backup/restore
│   ├── admin.py            ← Telegram admin panel + transfers
│   └── queries.py          ← User query/message system
├── rewriter/               ← AI rewrite engine
├── reports/                ← AI report engine
├── sessions/               ← Telethon session files (gitignored)
├── .env                    ← Credentials (gitignored)
├── requirements.txt        ← Python dependencies
├── GUIDE.md                ← This file
└── memory.md               ← Project context for AI agents
```

---

## Troubleshooting

| Problem | Solution |
|---------|---------|
| Bot doesn't start | Check `.env` has valid `API_ID`, `API_HASH`, `BOT_TOKEN` |
| Bot starts but is completely unresponsive | Was caused by wrong `_on_startup` signature — fixed in current version. Ensure you're running the latest `run_bot.py`. |
| Buttons show infinite loading spinner | Was caused by unhandled exceptions in callback handlers — `CallbackErrorMiddleware` now catches these automatically. |
| User can't connect | Make sure they enter phone with `+` country code |
| OTP fails | User must enter code WITH SPACES: `1 2 3 4 5` |
| Forwarder not forwarding | Check task is enabled (green), not paused, and forwarder is started |
| Channel ID not found | User must be a member of the channel. Start forwarder first. |
| Admin panel shows "Access denied" | Set your Telegram user ID in `ADMIN_IDS` in `.env` |
| Transfer fails "not a member" | Join the target channel before transferring ownership |
| Transfer screen disappears without redirect | Fixed — admin.py now redirects to main menu after expired/missing transfers. |
| AI rewrite not working | Install Ollama and pull a model: `ollama pull gemma3:1b` |
| Duplicate messages sent on import/export | Fixed — `export_import.py` now edits the existing message instead of sending a new one. |
