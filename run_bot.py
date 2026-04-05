#!/usr/bin/env python3
"""
TridenB Autoforwarder — Multi-User Bot + Admin Dashboard
Run this single file to start everything.
"""

import os
import sys
import asyncio
import logging
from dotenv import load_dotenv

load_dotenv()

# ─── Logging Setup ───

LOG_FORMAT = "%(asctime)s [%(name)-18s] %(levelname)-5s %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

logging.basicConfig(level=logging.INFO, format=LOG_FORMAT, datefmt=DATE_FORMAT)
# Quiet noisy libraries
logging.getLogger("telethon").setLevel(logging.WARNING)
logging.getLogger("aiogram").setLevel(logging.WARNING)
logging.getLogger("aiosqlite").setLevel(logging.WARNING)

logger = logging.getLogger("bot.main")

# ─── Colors for terminal ───


def c(text, code):
    return "\033[{}m{}\033[0m".format(code, text)


def green(t):  return c(t, "32")
def red(t):    return c(t, "31")
def yellow(t): return c(t, "33")
def cyan(t):   return c(t, "36")
def bold(t):   return c(t, "1")
def dim(t):    return c(t, "2")


BOT_TOKEN = os.getenv("BOT_TOKEN", "")


async def start_bot():
    """Start the Aiogram bot — runs forever until cancelled."""
    from aiogram import Bot, Dispatcher
    from bot_handlers import (
        auth, menu, tasks, forwarder_ctl, filters,
        rewriting, statistics, reports, export_import, admin,
    )

    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()

    # Wire up admin module with dispatcher storage for cross-user FSM
    admin.dp_storage = dp.storage

    async def _on_startup(bot_instance: Bot):
        me = await bot_instance.get_me()
        admin.bot_id = me.id
        logger.info("Bot ID set: {}".format(me.id))

    dp.startup.register(_on_startup)

    # Include all routers (order matters — auth first for /start)
    dp.include_router(auth.router)
    dp.include_router(menu.router)
    dp.include_router(tasks.router)
    dp.include_router(forwarder_ctl.router)
    dp.include_router(filters.router)
    dp.include_router(rewriting.router)
    dp.include_router(statistics.router)
    dp.include_router(reports.router)
    dp.include_router(export_import.router)
    dp.include_router(admin.router)

    logger.info("Bot started polling...")

    try:
        await dp.start_polling(bot)
    except asyncio.CancelledError:
        pass
    finally:
        from bot_forwarder import stop_report_scheduler
        await stop_report_scheduler()
        logger.info("Bot stopped.")


async def main():
    # Validate environment
    api_id = os.getenv("API_ID")
    api_hash = os.getenv("API_HASH")

    if not api_id or not api_hash:
        print(red("ERROR: API_ID and API_HASH must be set in .env"))
        sys.exit(1)

    if not BOT_TOKEN:
        print(red("ERROR: BOT_TOKEN must be set in .env"))
        sys.exit(1)

    # Initialize database
    from bot_database import init_db
    await init_db()

    # Load all active Telethon clients
    from bot_forwarder import load_all_active_clients, start_report_scheduler
    started = await load_all_active_clients()
    logger.info("Active Telethon clients loaded: {}".format(started))

    # Start report scheduler
    await start_report_scheduler()

    # Start the bot in a background task
    bot_task = asyncio.create_task(start_bot())

    print()
    print(green("  Bot started! Polling for messages in background."))
    print()

    # Run interactive CLI admin dashboard
    from admin_cli import run_dashboard
    await run_dashboard()

    # Dashboard exited — bot keeps running until Ctrl+C
    print("  {}".format(dim("Tip: Run this file again to reopen the dashboard.")))
    print("  {}".format(dim("Press Ctrl+C to stop the bot.")))

    try:
        await bot_task
    except (KeyboardInterrupt, asyncio.CancelledError):
        bot_task.cancel()
        try:
            await bot_task
        except asyncio.CancelledError:
            pass
        print("\n  Bot stopped.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n  Shutdown complete.")
