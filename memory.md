# TridenB Autoforwarder — Memory

## What This Project Does
Local CLI tool that forwards Telegram messages from source channels to destination channels using a personal user account (MTProto via Telethon). No bot token.

## Credentials
- Stored in `.env` (never committed)
- API_ID=29363636, API_HASH=dd4f18f6956a38dc18087c7495181258
- Phone: +918544130087

## Session
- Telethon saves session to `tridenb_autoforwarder.session` after first auth
- Subsequent runs skip OTP

## Task Storage
- `tasks.json` — runtime file, excluded from git
- Schema: list of task objects with source/dest channel IDs, enabled flag, filters

## Filter Behavior
- `blacklist_words`: drop entire message if any word matches (case-insensitive)
- `clean_words`: remove specific strings from text
- `clean_urls`: strip `https?://\S+` patterns
- `clean_usernames`: strip `@word` patterns
- `skip_images/audio/videos`: drop media messages entirely
- No text mod → `forward_messages()` (preserves media + formatting)
- Text modified → `send_message()` (text only)

## Current Status (2026-03-15)
Options 1, 2, 3 complete. First real task created ("Options expert").
Next: verify Option 4 (Toggle), 5 (Edit Filters), 6 (Delete), 7 (Run Forwarder).
See `tasks/progress.md` for checklist.

## Key Files
- `main.py` — all logic, single file
- `tasks.json` — auto-created, runtime persistence
- `.env` — credentials
- `tasks/progress.md` — feature verification checklist
