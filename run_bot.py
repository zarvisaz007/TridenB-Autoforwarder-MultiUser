#!/usr/bin/env python3
"""
TridenB Autoforwarder — Multi-User Bot + Admin Dashboard
Run this single file to start everything.
"""

import os
import sys
import time
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

def c(text, code): return f"\033[{code}m{text}\033[0m"
def green(t): return c(t, "32")
def red(t): return c(t, "31")
def yellow(t): return c(t, "33")
def cyan(t): return c(t, "36")
def bold(t): return c(t, "1")
def dim(t): return c(t, "2")


BOT_TOKEN = os.getenv("BOT_TOKEN", "8775446304:AAHGNz-ZX2yrmUyyxAkQkXMsPPeMpo7TrhM")


async def print_admin_dashboard():
    """Print a comprehensive admin dashboard to terminal."""
    from bot_database import get_all_users, get_all_tasks, get_all_statistics

    print()
    print(cyan("  ╔══════════════════════════════════════════════════════╗"))
    print(cyan("  ║       TridenB Autoforwarder — Admin Dashboard       ║"))
    print(cyan("  ║              Multi-User Bot Edition                  ║"))
    print(cyan("  ╚══════════════════════════════════════════════════════╝"))
    print()

    users = await get_all_users()
    all_tasks = await get_all_tasks()
    all_stats = await get_all_statistics()

    stats_by_user = {s["user_id"]: s for s in all_stats}
    tasks_by_user = {}
    for t in all_tasks:
        tasks_by_user.setdefault(t["user_id"], []).append(t)

    connected = [u for u in users if u["auth_state"] == "CONNECTED"]
    pending = [u for u in users if u["auth_state"] == "PENDING"]

    print(f"  {bold('Users:')} {green(str(len(connected)))} connected, {yellow(str(len(pending)))} pending, {dim(str(len(users)))} total")
    print(f"  {bold('Tasks:')} {len(all_tasks)} total across all users")
    print()

    if users:
        print(f"  {bold('User ID'):<18} {bold('Phone'):<18} {bold('Status'):<14} {bold('Tasks'):<8} {bold('Messages'):<10} {bold('Last Active')}")
        print(f"  {'─' * 85}")

        for u in users:
            uid = str(u["id"])
            phone = u.get("phone", "?")
            # Mask phone for privacy
            if len(phone) > 6:
                phone = phone[:4] + "****" + phone[-3:]

            if u["auth_state"] == "CONNECTED":
                status = green("CONNECTED")
            elif u["auth_state"] == "PENDING":
                status = yellow("PENDING")
            else:
                status = red("DISCONNECTED")

            user_tasks = tasks_by_user.get(u["id"], [])
            enabled_count = sum(1 for t in user_tasks if t["enabled"])
            task_info = f"{enabled_count}/{len(user_tasks)}"

            user_stat = stats_by_user.get(u["id"])
            msg_count = str(user_stat["total_messages"]) if user_stat else "0"

            last_active = u.get("last_active")
            if last_active:
                la_str = time.strftime("%m-%d %H:%M", time.localtime(last_active))
            else:
                la_str = "Never"

            print(f"  {uid:<18} {phone:<18} {status:<14} {task_info:<8} {msg_count:<10} {la_str}")

        print(f"  {'─' * 85}")
    print()

    if all_tasks:
        print(f"  {bold('─── All Tasks ───')}")
        print(f"  {bold('ID'):<5} {bold('User'):<14} {bold('Name'):<22} {bold('Source'):<18} {bold('Dests'):<6} {bold('Status')}")
        print(f"  {'─' * 80}")
        for t in all_tasks:
            status_parts = []
            if t["enabled"]:
                status_parts.append(green("ON"))
            else:
                status_parts.append(red("OFF"))
            if t["paused"]:
                status_parts.append(yellow("PAUSED"))
            if t["filters"].get("rewrite_enabled"):
                status_parts.append(cyan("AI"))

            name = t["name"][:20]
            dest_count = str(len(t.get("destination_channel_ids", [])))
            status_str = " ".join(status_parts)
            print(f"  {t['id']:<5} {str(t['user_id']):<14} {name:<22} {t['source_channel_id']:<18} {dest_count:<6} {status_str}")
        print(f"  {'─' * 80}")
        print()


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

    # Print admin dashboard
    await print_admin_dashboard()

    # Load all active Telethon clients
    from bot_forwarder import load_all_active_clients, start_report_scheduler
    started = await load_all_active_clients()
    logger.info(f"Active Telethon clients loaded: {started}")

    # Start report scheduler
    await start_report_scheduler()

    # Create and start Aiogram bot
    from aiogram import Bot, Dispatcher
    from bot_handlers import auth, menu, tasks, forwarder_ctl, filters, rewriting, statistics, reports, export_import, admin

    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()

    # Wire up admin module with dispatcher storage for cross-user FSM
    admin.dp_storage = dp.storage

    async def _on_startup(bot_instance: Bot):
        me = await bot_instance.get_me()
        admin.bot_id = me.id
        logger.info(f"Bot ID set: {me.id}")

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

    print(f"  {green('Bot started!')} Polling for messages...")
    print(f"  {dim('Press Ctrl+C to stop.')}")
    print()

    try:
        await dp.start_polling(bot)
    except KeyboardInterrupt:
        pass
    finally:
        from bot_forwarder import stop_report_scheduler
        await stop_report_scheduler()
        logger.info("Bot stopped.")


if __name__ == "__main__":
    asyncio.run(main())
