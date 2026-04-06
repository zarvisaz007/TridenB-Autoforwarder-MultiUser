#!/usr/bin/env python3
"""
Ultimate Autoforwarder — Multi-User Bot + Admin Dashboard
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
logging.getLogger("telethon").setLevel(logging.WARNING)
logging.getLogger("aiogram").setLevel(logging.INFO)
logging.getLogger("aiosqlite").setLevel(logging.WARNING)

logger = logging.getLogger("bot.main")


def green(t):
    return "\033[32m{}\033[0m".format(t)


def red(t):
    return "\033[31m{}\033[0m".format(t)


def dim(t):
    return "\033[2m{}\033[0m".format(t)


BOT_TOKEN = os.getenv("BOT_TOKEN", "")

# Shared bot instance for CLI to send replies
_bot_instance = None


async def start_bot():
    """Start the Aiogram bot — runs forever until cancelled."""
    global _bot_instance

    from aiogram import Bot, Dispatcher, BaseMiddleware
    from aiogram.types import CallbackQuery, TelegramObject, BotCommand
    from aiogram.types import MenuButtonCommands
    from bot_handlers import (
        auth, menu, tasks, forwarder_ctl, filters,
        rewriting, statistics, reports, export_import, admin, queries,
    )

    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()

    # Global error-handling middleware for callback queries.
    # Prevents the bot from appearing unresponsive when a handler
    # raises an exception (e.g. MessageNotModified, MessageToEditNotFound).
    class CallbackErrorMiddleware(BaseMiddleware):
        async def __call__(self, handler, event: TelegramObject, data: dict):
            try:
                return await handler(event, data)
            except Exception as exc:
                logger.error("Handler error: %s", exc)
                if isinstance(event, CallbackQuery):
                    try:
                        await event.answer(
                            "Something went wrong. Please try /start.",
                            show_alert=True,
                        )
                    except Exception:
                        pass

    dp.callback_query.middleware(CallbackErrorMiddleware())

    _bot_instance = bot

    # Wire up admin module
    admin.dp_storage = dp.storage

    async def _on_startup(**kwargs):
        b = kwargs.get("bot", bot)
        me = await b.get_me()
        admin.bot_id = me.id
        logger.info("Bot ID set: {}".format(me.id))

        # Register bot commands — makes the menu button appear in bottom-left
        commands = [
            BotCommand(command="start", description="Open main menu"),
            BotCommand(command="menu", description="Show main menu"),
            BotCommand(command="status", description="Forwarder status"),
            BotCommand(command="tasks", description="View my tasks"),
            BotCommand(command="stats", description="View statistics"),
            BotCommand(command="logs", description="View recent logs"),
            BotCommand(command="help", description="Get help"),
        ]
        await b.set_my_commands(commands)
        await b.set_chat_menu_button(menu_button=MenuButtonCommands())
        logger.info("Bot commands registered (%d commands)", len(commands))

    dp.startup.register(_on_startup)

    # Include all routers
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
    dp.include_router(queries.router)

    # Delete any stale webhook — if one is set, polling receives nothing
    try:
        wh = await bot.get_webhook_info()
        if wh.url:
            logger.warning("Webhook was set to %s — deleting it so polling works", wh.url)
            await bot.delete_webhook(drop_pending_updates=False)
    except Exception as e:
        logger.error("Webhook check failed: %s", e)

    me = await bot.get_me()
    logger.info("Bot started polling as @%s (id=%s)...", me.username, me.id)

    try:
        await dp.start_polling(bot, allowed_updates=["message", "callback_query"])
    except asyncio.CancelledError:
        pass
    finally:
        from bot_forwarder import stop_report_scheduler
        await stop_report_scheduler()
        logger.info("Bot stopped.")


async def main():
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

    # Start NetGuard network monitor
    from netguard import start_netguard
    if start_netguard():
        print(green("  NetGuard network monitor active."))
    else:
        print(dim("  NetGuard skipped (Node.js not found or monitor.js missing)."))

    # Start the bot in a background task
    bot_task = asyncio.create_task(start_bot())

    # Small delay so bot_instance is set, then check it didn't crash
    await asyncio.sleep(2)
    if bot_task.done():
        exc = bot_task.exception()
        if exc:
            print(red("  ERROR: Bot failed to start: {}".format(exc)))
            import traceback
            traceback.print_exception(type(exc), exc, exc.__traceback__)
            sys.exit(1)

    print()
    print(green("  Bot started! Polling for messages in background."))
    print()

    # Give CLI access to the bot instance for sending replies
    from admin.cli import run_dashboard, set_bot
    set_bot(_bot_instance)

    # Run interactive CLI admin dashboard
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
        pass
    finally:
        from netguard import stop_netguard
        stop_netguard()
        print("\n  Shutdown complete.")
