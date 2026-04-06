# Replacer Module

Targeted text replacement engine for the Ultimate Autoforwarder. Swaps usernames, words, URLs by domain, phone numbers, and Telegram channel links before messages are forwarded.

## Architecture

```
replacer/
    __init__.py     # Exports: apply_replacements
    engine.py       # Core replacement logic (pure text, no I/O)
    README.md       # This file
```

## How It Works

The replacer runs inside `apply_filters()` in `main.py`, **after** clean_words/regex_clean but **before** `clean_urls` and `clean_usernames`. This means:

1. Replacer swaps targeted items first (specific usernames, specific domain URLs)
2. Then `clean_urls` / `clean_usernames` can remove whatever is left as a safety net

### Processing Order

1. **Channel links** — `t.me/old_slug` to `t.me/new_slug` (runs first so URLs aren't removed)
2. **URL domain rules** — Match URL domains, swap with replacement URL. Optionally remove unmatched URLs
3. **Username mappings** — `@old` to `@new` (case-insensitive)
4. **Phone mappings** — Direct string replacement
5. **Word/phrase mappings** — Direct string replacement (case-sensitive)

## Configuration

Stored per-task at `task["filters"]["replacements"]` in `tasks.json`:

```json
{
    "enabled": true,
    "usernames": {
        "old_channel": "my_channel"
    },
    "words": {
        "OldBrand": "MyBrand",
        "join premium": "join our group"
    },
    "urls": {
        "domain_map": {
            "cosmofeed.com": "https://cosmofeed.com/my-page"
        },
        "remove_unmatched": true
    },
    "phones": {
        "+911234567890": "+919876543210"
    },
    "channel_links": {
        "old_group_name": "my_group_name"
    }
}
```

## UI Access

Edit Task (option 5) > Filters > option 14 (Replacements) opens the replacement submenu:

```
--- Replacements ---
1. Enable/Disable
2. @Username mappings    (old:new pairs)
3. Word/phrase mappings  (old:new pairs)
4. URL domain rules      (domain:replacement_url pairs)
5. Remove unmatched URLs (y/n)
6. Phone mappings        (old:new pairs)
7. Channel link mappings (old_slug:new_slug pairs)
8. Clear all replacements
0. Back
```

Input format for all mappings: comma-separated `old:new` pairs.

## Interaction with Other Filters

- **AI Rewrite**: Replacements run before rewrite — the AI rewrites already-replaced text
- **Remove URLs** (`clean_urls`): Runs after replacer — removes any URLs the replacer didn't handle
- **Remove @usernames** (`clean_usernames`): Runs after replacer — removes any @mentions the replacer didn't swap

This lets you combine: "replace MY URLs, strip all competitor URLs" by enabling both URL domain rules and Remove URLs.

## API

```python
from replacer import apply_replacements

result = apply_replacements(text, replace_config)
# Returns modified text if changes were made, None otherwise
```

Synchronous, pure text processing — no async, no I/O, no external dependencies.
