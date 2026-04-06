"""
Main interactive CLI dashboard loop.
"""

import time

import bot_forwarder
from bot_database import get_all_users, get_all_tasks, get_all_statistics, get_all_queries
from admin.helpers import (
    clear, header, line, ainput,
    green, red, yellow, cyan, bold, dim, format_number, sanitize,
)
from admin.views import (
    view_users, view_tasks, view_stats, view_channels,
    view_logs, view_queries, pause_everything, resume_everything,
)

# Set from run_bot.py so queries view can send replies
_bot_instance = None


def set_bot(bot):
    global _bot_instance
    _bot_instance = bot


async def run_dashboard():
    """Main dashboard loop — runs until user exits."""
    while True:
        clear()
        header("Ultimate Autoforwarder — Admin Dashboard")

        await _print_summary()
        await _print_recent_messages()

        print()
        print("  " + line(55))
        print("  {}  Users Overview        {}  Channels".format(bold("1"), bold("4")))
        print("  {}  All Tasks              {}  Live Logs".format(bold("2"), bold("5")))
        print("  {}  Global Stats           {}  Queries / Messages".format(bold("3"), bold("6")))
        print()
        print("  {}  Pause ALL tasks        {}  Resume ALL tasks".format(bold("P"), bold("R")))
        print("  {}  Refresh                {}  Exit (bot keeps running)".format(bold("7"), bold("0")))
        print()

        try:
            choice = await ainput("  > ")
        except (EOFError, KeyboardInterrupt):
            break

        choice = choice.strip().upper()
        if choice == "1":
            await view_users()
        elif choice == "2":
            await view_tasks()
        elif choice == "3":
            await view_stats()
        elif choice == "4":
            await view_channels()
        elif choice == "5":
            await view_logs()
        elif choice == "6":
            await view_queries(_bot_instance)
        elif choice == "P":
            await pause_everything()
        elif choice == "R":
            await resume_everything()
        elif choice == "7":
            continue
        elif choice == "0":
            print()
            print("  {} Dashboard closed. Bot is still running.".format(dim("*")))
            print("  {} Press Ctrl+C to stop the bot.".format(dim("*")))
            print()
            break


async def _print_summary():
    """Print quick summary stats."""
    users = await get_all_users()
    all_tasks = await get_all_tasks()
    all_stats = await get_all_statistics()

    connected = sum(1 for u in users if u["auth_state"] == "CONNECTED")
    pending = sum(1 for u in users if u["auth_state"] == "PENDING")
    active_clients = len(bot_forwarder.user_clients)
    enabled_tasks = sum(1 for t in all_tasks if t["enabled"])
    paused_tasks = sum(1 for t in all_tasks if t["paused"])
    total_msgs = sum(s.get("total_messages", 0) for s in all_stats)
    today_msgs = sum(s.get("today_count", 0) for s in all_stats)

    # Check for unreplied queries
    try:
        queries = await get_all_queries()
        unreplied = sum(1 for q in queries if not q.get("replied_at"))
    except Exception:
        unreplied = 0

    print("  {} {} online, {} pending, {} total".format(
        bold("Users:"), green(str(connected)), yellow(str(pending)), dim(str(len(users)))))
    print("  {} {} active, {} paused / {} total".format(
        bold("Tasks:"), green(str(enabled_tasks)),
        yellow(str(paused_tasks)) if paused_tasks else "0",
        dim(str(len(all_tasks)))))
    print("  {} {}    {} {} today    {} {}".format(
        bold("Clients:"), green(str(active_clients)) if active_clients else red("0"),
        bold("Msgs:"), yellow(str(today_msgs)),
        bold("All-time:"), format_number(total_msgs)))

    if unreplied:
        print("  {} {}".format(bold("Queries:"), red("{} unreplied".format(unreplied))))

    print("  {} {}".format(bold("Time:"), dim(time.strftime("%Y-%m-%d %H:%M:%S"))))


async def _print_recent_messages():
    """Show last few log entries across all users as a quick glance."""
    users = await get_all_users()

    all_recent = []
    for u in users:
        logs = bot_forwarder.get_user_logs(u["id"], 3)
        for entry in logs:
            all_recent.append(entry)

    if all_recent:
        print()
        print("  {}".format(bold("Recent Activity:")))
        # Show last 5 across all users
        for entry in all_recent[-5:]:
            print("    {}".format(dim(sanitize(entry))))
